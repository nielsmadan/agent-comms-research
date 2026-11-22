import errno
import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from agentcomms import checkpoint, cli, isolation, manifest, profiles
from agentcomms.engine import Engine, Launched
from agentcomms.hosts.errors import HostError
from agentcomms.hosts.tmux import TmuxError
from agentcomms.model import Ack, Delivery, DraftFate, Manifest, Target
from agentcomms.paths import Layout
from agentcomms.profiles import Binary, ProfileError
from agentcomms.records import ResultRecord


@pytest.fixture
def layout(tmp_path, monkeypatch) -> Layout:
    layout = Layout(tmp_path)
    monkeypatch.setattr(cli, "default_layout", lambda: layout)
    monkeypatch.setattr(manifest, "cleanup", lambda layout, run_id, kill_server=True: [])
    monkeypatch.setattr(manifest, "stop_idle_server", lambda layout: False)
    monkeypatch.setattr(isolation, "global_config_hashes", lambda: {})
    monkeypatch.setattr(isolation, "user_state_mtimes", lambda agent: {})
    monkeypatch.setattr(isolation, "bridge_snapshot", lambda home: {})
    monkeypatch.setattr(manifest, "remaining_pids", lambda layout, run_id: set())
    return layout


def run(*extra: str) -> int:
    return cli.main(["run", "--agent", "opencode", "--adapter", "tmux-paste", *extra])


def raw(layout: Layout) -> list[dict]:
    return [json.loads(line) for line in layout.raw_jsonl.read_text().splitlines()]


def raising(error: Exception):
    def launch(self, m, agent, mode="auto", adapter=None):
        raise error
    return launch


def test_isolation_failure_is_recorded_as_skipped_error(layout, monkeypatch):
    missing = Path.home() / ".local" / "share" / "opencode" / "auth.json"
    monkeypatch.setattr(Engine, "launch", raising(isolation.IsolationError(f"{missing} missing")))
    assert run() == 6
    [record] = raw(layout)
    assert record["delivery"] == "error"
    assert record["notes"] == "skipped: cannot isolate; IsolationError: ~/.local/share/opencode/auth.json missing"


@pytest.mark.parametrize(("error", "delivery"), [
    (ProfileError("cannot parse version from ''"), "error"),
    (FileNotFoundError(errno.ENOENT, "No such file", "/x"), "error"),
    (subprocess.TimeoutExpired(["opencode", "--version"], 60), "env_error"),
    (PermissionError(errno.EPERM, "Operation not permitted", "/x"), "env_error"),
    (TmuxError("tmux new-session failed: server exited unexpectedly"), "env_error"),
])
def test_cell_failures_split_into_error_and_retryable_env_error(layout, monkeypatch, error, delivery):
    monkeypatch.setattr(Engine, "launch", raising(error))
    assert run() == (6 if delivery == "error" else 0)
    [record] = raw(layout)
    assert (record["delivery"], record["notes"].split(":")[0]) == (delivery, type(error).__name__)
    cell = {k: record[k] for k in checkpoint.CELL_KEYS}
    assert len(checkpoint.pending_cells([cell], [record], resume=True)) == (1 if delivery == "env_error" else 0)


def test_ownership_failure_stops_the_batch_without_a_record(layout, monkeypatch, capsys):
    monkeypatch.setattr(Engine, "launch", raising(manifest.OwnershipError("pid 9 is not in run r's process groups")))
    assert run() == 7
    assert layout.raw_jsonl.exists() is False
    assert "STOP: ownership check failed for run" in capsys.readouterr().err
    assert "pid 9 is not in run r's process groups" in layout.progress_md.read_text()


def test_safety_checks_run_after_cleanup_raises(layout, monkeypatch, capsys):
    def broken_cleanup(layout, run_id, kill_server=True):
        raise sqlite3.DatabaseError("file is not a database")

    monkeypatch.setattr(manifest, "cleanup", broken_cleanup)
    monkeypatch.setattr(Engine, "launch", raising(ProfileError("x")))
    monkeypatch.setattr(cli, "session_problems", lambda layout, engine, run_id: ["opencode auth link replaced"])
    assert run() == 4
    err = capsys.readouterr().err
    assert "STOP: cleanup of" in err and "STOP: opencode auth link replaced" in err
    progress = layout.progress_md.read_text()
    assert "DatabaseError: file is not a database" in progress and "opencode auth link replaced" in progress


def test_record_survives_failed_version_recheck(layout, monkeypatch):
    def launch(self, m, agent, mode="auto", adapter=None):
        target = Target(m.run_id, agent, "tmux", "none", layout.work_dir(m.run_id, agent),
                        layout.home_dir(m.run_id, agent), "ses_x", f"agentcomms:{m.run_id}-{agent}", None, None, 1)
        binary = Binary(agent, Path("/o/opencode"), "2.1.4")
        return m, Launched(target, binary, {"opencode": "2.1.4"}, layout.root / "pane.log", "pane-regex", [])

    def run_cell(self, m, launched, adapter, scenario, stage, rep):
        return ResultRecord(m.run_id, stage, "opencode", launched.versions, adapter.name, "tmux", "none", "S1", rep,
                            "raw", Delivery.DELIVERED, True, DraftFate.NA, Ack.ACKED, False, 0, 0.1)

    def check_versions(self, launched):
        raise ProfileError("opencode --version printed nothing")

    monkeypatch.setattr(Engine, "launch", launch)
    monkeypatch.setattr(Engine, "run_cell", run_cell)
    monkeypatch.setattr(Engine, "resolved_session", lambda self, m, target: m)
    monkeypatch.setattr(Engine, "check_versions", check_versions)
    assert run() == 3
    assert [(r["delivery"], r["ack"]) for r in raw(layout)] == [("delivered", "acked")]
    assert ("opencode version re-check failed (ProfileError: opencode --version printed nothing); batch aborted"
            in layout.progress_md.read_text())


def credential_db(home: Path) -> Path:
    db = isolation.opencode_db(home)
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE credential (id text PRIMARY KEY, label text NOT NULL, value text NOT NULL)")
        conn.execute("INSERT INTO credential VALUES ('c1', 'API key', 'v')")
    return db


def credential_rows(db: Path) -> int:
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT count(*) FROM credential").fetchone()[0]


def test_cleanup_purges_credentials_only_inside_the_run(tmp_path):
    layout = Layout(tmp_path / "repo")
    run_id = "20261024-000000-abcd"
    inside = credential_db(layout.home_dir(run_id, "opencode"))
    outside = credential_db(tmp_path / "elsewhere")

    def target(home: Path, ref: str) -> Target:
        return Target(run_id, "opencode", "tmux", "none", layout.work_dir(run_id, "opencode"), home, None, ref,
                      None, None, None)

    m = Manifest(run_id, [], [target(layout.home_dir(run_id, "opencode"), "agentcomms:a"),
                              target(tmp_path / "elsewhere", "agentcomms:b")], [], [])
    assert manifest.purge_run_credentials(layout, m) == [
        f"removed 1 credential rows from runs/{run_id}/home/opencode/data/opencode/opencode.db"]
    assert (credential_rows(inside), credential_rows(outside)) == (0, 1)


def test_cleanup_reports_a_purge_failure_as_a_note(tmp_path):
    layout = Layout(tmp_path)
    run_id = "20261024-000000-abcd"
    db = isolation.opencode_db(layout.home_dir(run_id, "opencode"))
    db.parent.mkdir(parents=True)
    db.write_text("not a database")
    target = Target(run_id, "opencode", "tmux", "none", layout.work_dir(run_id, "opencode"),
                    layout.home_dir(run_id, "opencode"), None, "agentcomms:a", None, None, None)
    assert manifest.purge_run_credentials(layout, Manifest(run_id, [], [target], [], [])) == [
        f"note: credential purge failed for runs/{run_id}/home/opencode/data/opencode/opencode.db: "
        "DatabaseError: file is not a database"]


def test_leftover_processes_after_cleanup_fail_the_cell(layout, monkeypatch, capsys):
    monkeypatch.setattr(Engine, "launch", raising(ProfileError("x")))
    monkeypatch.setattr(manifest, "remaining_pids", lambda layout, run_id: {4242})
    assert run() == 9
    assert "STOP: 1 harness processes still running after cleanup of" in capsys.readouterr().err


def matrix(*extra: str) -> int:
    return cli.main(["matrix", "--agents", "claude,codex", "--adapters", "tmux-paste", *extra])


def full_record(cell: dict, delivery: str, notes: str = "") -> dict:
    return {**cell, "run_id": "r", "delivery": delivery, "notes": notes, "ack": "none", "latency_s": None,
            "harmful": False, "intact": None, "draft_fate": "n/a", "versions": {}, "retries": 0, "evidence": [],
            "sent_sha256": None, "recv_sha256": None, "ts": 0.0}


def fake_run_one(outcomes: dict[tuple[str, str], list[tuple[int, str, str]]], calls: list[tuple[str, str]]):
    def run_one(layout, progress, cell, keep=False, mode=None, exclude=cli.no_exclusions, on_run=None,
                kill_server=True):
        key = (cell["agent"], cell["scenario"])
        calls.append(key)
        status, delivery, notes = outcomes[key].pop(0)
        record = full_record(cell, delivery, notes)
        checkpoint.append_record(layout.raw_jsonl, record)
        return cli.CellResult(status, record)
    return run_one


def test_matrix_runs_every_cell_and_renders_the_matrix(layout, monkeypatch):
    calls = []
    outcomes = {(a, s): [(0, "delivered", "")] for a in ("claude", "codex") for s in ("S1", "S4")}
    monkeypatch.setattr(cli, "run_one", fake_run_one(outcomes, calls))
    assert matrix("--scenarios", "S1,S4") == 0
    assert calls == [("claude", "S1"), ("claude", "S4"), ("codex", "S1"), ("codex", "S4")]
    assert "| claude | tmux-paste | tmux | none | 26 | raw | 0/1 | 0/1 |" in layout.matrix_md.read_text()
    assert "None queued." in layout.progress_md.read_text()


def test_matrix_runs_a_plan_file_in_its_order_and_resumes_recorded_reps(layout, monkeypatch, tmp_path):
    import json
    calls = []
    outcomes = {("pi", "S5"): [(0, "delivered", "")], ("claude", "S2"): [(0, "delivered", "")]}
    monkeypatch.setattr(cli, "run_one", fake_run_one(outcomes, calls))
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([{"agent": "pi", "mechanism": "pi-ext", "scenario": "S5", "rep": 2},
                                {"agent": "claude", "mechanism": "claude-channel", "scenario": "S2", "rep": 1},
                                {"agent": "claude", "mechanism": "claude-channel", "scenario": "S2", "rep": 2}]))
    checkpoint.append_record(layout.raw_jsonl, full_record(
        cli.make_cell("extensive", "claude", "claude-channel", "S2", 2), "delivered"))
    assert cli.main(["matrix", "--stage", "extensive", "--plan", str(plan), "--resume"]) == 0
    assert calls == [("pi", "S5"), ("claude", "S2")]


def test_a_plan_entry_may_name_its_own_stage():
    cells = cli.plan_cells([{"agent": "droid", "mechanism": "tmux-paste", "scenario": "S1", "rep": 1,
                             "stage": "screen"},
                            {"agent": "droid", "mechanism": "tmux-paste", "scenario": "S2", "rep": 1}], "extensive")
    assert [c["stage"] for c in cells] == ["screen", "extensive"]


def test_a_plan_entry_for_an_unsupported_pair_is_refused():
    import pytest
    with pytest.raises(ValueError, match="invalid plan entries"):
        cli.plan_cells([{"agent": "pi", "mechanism": "claude-channel", "scenario": "S1", "rep": 1}], "extensive")


@pytest.mark.parametrize("plan", [
    {"agent": "claude", "mechanism": "tmux-paste", "scenario": "S1", "rep": 1},
    ["claude"],
    [{"agent": "claude", "mechanism": "tmux-paste", "scenario": "S1", "rep": True}],
])
def test_a_malformed_plan_is_refused_before_any_cell_launches(layout, monkeypatch, tmp_path, capsys, plan):
    calls = []
    monkeypatch.setattr(cli, "run_one", fake_run_one({}, calls))
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    assert cli.main(["matrix", "--stage", "extensive", "--plan", str(path)]) == 2
    assert calls == []
    assert capsys.readouterr().err.startswith("matrix: ")


def test_send_to_a_run_whose_receiver_is_gone_is_refused_with_the_ownership_status(layout, monkeypatch, capsys):
    run_id = "20261029-010000-dead"
    target = Target(run_id, "claude", "tmux", "none", layout.work_dir(run_id, "claude"),
                    layout.home_dir(run_id, "claude"), None, f"agentcomms:{run_id}-claude", None, None, 4242)
    manifest.save(layout, Manifest(run_id, [4242], [target], [], []))
    monkeypatch.setattr(cli.procs, "ps_rows", lambda: [])
    monkeypatch.setattr(cli, "make_adapter", lambda name, hosts: pytest.fail("send reached the adapter"))
    assert cli.main(["send", "--run", run_id, "--adapter", "tmux-paste", "--text", "hi"]) == 7
    assert capsys.readouterr().err == f"refused: pid 4242 is not in run {run_id}'s process groups\n"


@pytest.mark.parametrize("argv", [
    ["run", "--agent", "claude", "--adapter", "tmux-paste", "--rep", "0"],
    ["matrix", "--agents", "claude", "--adapters", "tmux-paste", "--reps", "-1"],
    ["s9", "--a", "claude", "--b", "codex", "--fwd", "tmux-paste", "--back", "tmux-paste", "--rep", "0"],
])
def test_a_rep_below_one_is_a_usage_error(argv, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.parser().parse_args(argv)
    assert exit_info.value.code == 2
    assert "must be at least 1" in capsys.readouterr().err


def test_matrix_stops_when_an_agent_version_changes_between_cells(layout, monkeypatch, capsys):
    calls = []
    versions = iter([{"droid": "0.249.0", "os": "27.2"}, {"droid": "0.251.0", "os": "27.2"}])

    def run_one(layout, progress, cell, keep=False, mode=None, exclude=cli.no_exclusions, on_run=None,
                kill_server=True):
        calls.append(cell["scenario"])
        record = {**full_record(cell, "delivered"), "versions": next(versions)}
        checkpoint.append_record(layout.raw_jsonl, record)
        return cli.CellResult(0, record)

    monkeypatch.setattr(cli, "run_one", run_one)
    status = cli.main(["matrix", "--agents", "droid", "--adapters", "tmux-paste", "--scenarios", "S1,S4,S7"])
    assert status == 3
    assert calls == ["S1", "S4"]
    assert "droid 0.249.0 -> 0.251.0" in capsys.readouterr().err


def test_matrix_requeues_a_sleep_env_error_once(layout, monkeypatch):
    calls = []
    outcomes = {("claude", "S1"): [(0, "env_error", "sleep-or-network"), (0, "delivered", "")],
                ("codex", "S1"): [(0, "delivered", "")]}
    monkeypatch.setattr(cli, "run_one", fake_run_one(outcomes, calls))
    assert matrix("--scenarios", "S1") == 0
    assert calls == [("claude", "S1"), ("codex", "S1"), ("claude", "S1")]


def test_matrix_pauses_on_api_errors(layout, monkeypatch, capsys):
    calls = []
    outcomes = {("claude", "S1"): [(0, "env_error", "api-error: 429 rate limited")]}
    monkeypatch.setattr(cli, "run_one", fake_run_one(outcomes, calls))
    assert matrix("--scenarios", "S1") == cli.PAUSED
    assert calls == [("claude", "S1")]
    assert "batch paused" in capsys.readouterr().err
    assert "- pilot codex tmux-paste S1 rep 1" in layout.progress_md.read_text()


def test_matrix_stops_scheduling_after_a_stop_status(layout, monkeypatch):
    calls = []
    outcomes = {("claude", "S1"): [(9, "delivered", "")]}
    monkeypatch.setattr(cli, "run_one", fake_run_one(outcomes, calls))
    assert matrix("--scenarios", "S1") == 9
    assert calls == [("claude", "S1")]


def test_matrix_resume_skips_recorded_cells_and_budget_stops_at_cell_boundary(layout, monkeypatch, capsys):
    calls = []
    outcomes = {("codex", "S1"): [(0, "delivered", "")]}
    monkeypatch.setattr(cli, "run_one", fake_run_one(outcomes, calls))
    checkpoint.append_record(layout.raw_jsonl,
                             full_record(cli.make_cell("pilot", "claude", "tmux-paste", "S1", 1), "delivered"))
    assert matrix("--scenarios", "S1", "--resume") == 0
    assert calls == [("codex", "S1")]
    assert matrix("--scenarios", "S1", "--time-budget", "0") == 0
    assert calls == [("codex", "S1")]
    assert "time budget exhausted; 2 cells left" in capsys.readouterr().out


def test_a_stop_file_ends_the_batch_after_the_running_cell(layout, monkeypatch, capsys):
    calls = []
    outcomes = {("claude", "S1"): [(0, "delivered", "")]}
    inner = fake_run_one(outcomes, calls)

    def run_one(layout, progress, cell, *args, **kwargs):
        result = inner(layout, progress, cell, *args, **kwargs)
        cli.stop_file(layout).write_text("")
        return result

    monkeypatch.setattr(cli, "run_one", run_one)
    cli.stop_file(layout).parent.mkdir(parents=True, exist_ok=True)
    assert matrix("--scenarios", "S1") == 0
    assert calls == [("claude", "S1")]
    assert f"{cli.stop_file(layout)} found; 1 cells left" in capsys.readouterr().out


def test_a_stop_file_left_from_an_earlier_batch_blocks_the_next_one_and_is_kept(layout, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cli, "run_one", fake_run_one({}, calls))
    cli.stop_file(layout).parent.mkdir(parents=True, exist_ok=True)
    cli.stop_file(layout).write_text("")
    assert matrix("--scenarios", "S1") == cli.PAUSED
    assert calls == []
    assert cli.stop_file(layout).exists()
    out = capsys.readouterr()
    assert f"{cli.stop_file(layout)} found; 2 cells left" in out.out
    assert f"STOP: {cli.stop_file(layout)} blocked the batch before its first cell" in out.err


def test_a_stop_file_block_is_not_blamed_on_an_api_or_auth_error(layout, monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_one", fake_run_one({}, []))
    cli.stop_file(layout).parent.mkdir(parents=True, exist_ok=True)
    cli.stop_file(layout).write_text("")
    assert matrix("--scenarios", "S1") == cli.PAUSED
    assert "API/quota/auth" not in capsys.readouterr().err


def test_cleanup_of_an_unknown_run_id_exits_2(layout, monkeypatch, capsys):
    monkeypatch.setattr(manifest, "cleanup", raising(AssertionError("cleaned")))
    assert cli.main(["cleanup", "20261029-000000-zzzz"]) == 2
    assert cli.main(["cleanup", "../../etc"]) == 2
    err = capsys.readouterr().err
    assert "unknown run id: 20261029-000000-zzzz" in err and "unknown run id: ../../etc" in err


def test_not_applicable_cell_is_recorded_without_a_launch(layout, monkeypatch):
    monkeypatch.setattr(Engine, "launch", raising(AssertionError("must not launch")))
    assert cli.main(["run", "--agent", "pi", "--adapter", "tmux-paste", "--scenario", "S3"]) == 0
    [record] = raw(layout)
    assert (record["delivery"], record["notes"]) == ("n/a", "n/a: pi has no approval prompts")


def test_concurrent_matrix_never_runs_two_cells_for_one_agent(layout, monkeypatch):
    import threading
    import time as _time
    active: dict[str, int] = {}
    peak: dict[str, int] = {}
    overlap = [0]
    lock = threading.Lock()

    def run_one(layout, progress, cell, keep=False, mode=None, exclude=cli.no_exclusions, on_run=None,
                kill_server=True):
        with lock:
            active[cell["agent"]] = active.get(cell["agent"], 0) + 1
            peak[cell["agent"]] = max(peak.get(cell["agent"], 0), active[cell["agent"]])
            overlap[0] = max(overlap[0], sum(active.values()))
        _time.sleep(0.05)
        with lock:
            active[cell["agent"]] -= 1
        return cli.CellResult(0, {**cell, "delivery": "delivered", "notes": ""})

    monkeypatch.setattr(cli, "run_one", run_one)
    assert matrix("--stage", "screen", "--scenarios", "S1,S4,S5", "--max-concurrency", "3") == 0
    assert peak == {"claude": 1, "codex": 1}
    assert overlap[0] >= 2


def test_unknown_adapter_is_rejected_before_any_launch(layout, monkeypatch, capsys):
    monkeypatch.setattr(Engine, "launch", raising(AssertionError("must not launch")))
    with pytest.raises(SystemExit):
        matrix("--adapters", "tmux-past")
    assert "unknown: tmux-past" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        run("--adapter", "tmux-past")


def test_stale_live_run_stops_the_batch(layout, monkeypatch, capsys):
    def refuse(layout, exclude=frozenset()):
        raise manifest.LiveRunError("runs with live processes: 20261024-000000-dead")

    monkeypatch.setattr(manifest, "refuse_if_live", refuse)
    assert run() == cli.LIVE_RUN
    assert "STOP: runs with live processes: 20261024-000000-dead" in capsys.readouterr().err


def test_harness_bug_in_a_cell_is_recorded_with_its_traceback_and_stops(layout, monkeypatch, capsys):
    monkeypatch.setattr(Engine, "launch", raising(ValueError("parser bug")))
    assert run() == cli.HARNESS_BUG
    [record] = raw(layout)
    assert record["delivery"] == "error"
    assert record["notes"] == f"harness-bug: ValueError: parser bug; traceback=runs/{record['run_id']}/traceback.txt"
    assert "ValueError: parser bug" in (layout.run_dir(record["run_id"]) / "traceback.txt").read_text()
    assert "STOP: harness bug in opencode tmux-paste S1" in capsys.readouterr().err


def test_crashed_matrix_worker_records_once_and_stops_the_batch(layout, monkeypatch):
    def run_one(*args, **kwargs):
        raise KeyError("boom")

    monkeypatch.setattr(cli, "run_one", run_one)
    assert matrix("--scenarios", "S1") == cli.HARNESS_BUG
    [record] = raw(layout)
    assert (record["agent"], record["delivery"]) == ("claude", "error")
    assert record["notes"].startswith("harness-crash: KeyError: 'boom'; traceback=runs/harness-crash-")
    assert "| claude | tmux-paste | tmux | none | 27 | raw | 0/0 · err 1 |" in layout.matrix_md.read_text()
    assert "- pilot codex tmux-paste S1 rep 1" in layout.progress_md.read_text()


def test_worker_crash_after_its_record_does_not_record_twice(layout, monkeypatch):
    def run_one(layout, progress, cell, *args, **kwargs):
        checkpoint.append_record(layout.raw_jsonl, full_record(cell, "delivered") | {"ts": 9e12})
        raise RuntimeError("tail exploded")

    monkeypatch.setattr(cli, "run_one", run_one)
    assert matrix("--agents", "claude", "--scenarios", "S1") == cli.HARNESS_BUG
    assert [r["delivery"] for r in raw(layout)] == ["delivered"]


def test_config_safety_stop_runs_when_the_auth_link_check_raises(layout, monkeypatch, capsys):
    hashes = iter([{"~/.codex/config.toml": "a"}, {"~/.codex/config.toml": "b"}])
    monkeypatch.setattr(isolation, "global_config_hashes", lambda: next(hashes))
    monkeypatch.setattr(Engine, "launch", raising(ProfileError("x")))

    def broken(layout, engine, run_id):
        raise OSError("manifest unreadable")

    monkeypatch.setattr(cli, "session_problems", broken)
    assert run() == 5
    err = capsys.readouterr().err
    assert "STOP: auth-link check for" in err
    assert "STOP: global config references harness runs: ~/.codex/config.toml" in err


def test_second_receiver_crash_on_a_cell_becomes_a_terminal_error():
    cell = cli.make_cell("pilot", "codex", "tmux-paste", "S4", 1)
    crash = ResultRecord("r2", "pilot", "codex", {}, "tmux-paste", "tmux", "none", "S4", 1, "raw",
                         Delivery.ENV_ERROR, None, DraftFate.NA, Ack.NONE, False, 0, None,
                         notes="ready=pane-regex; receiver-crashed (pane-exited; was lost)")
    assert cli.crash_verdict(crash, []) == crash
    prior = [full_record(cell, "env_error", "receiver-crashed (pid 9 gone; was lost)")]
    escalated = cli.crash_verdict(crash, prior)
    assert escalated.delivery is Delivery.ERROR
    assert escalated.notes == "ready=pane-regex; receiver-crashed-repeatedly (crash 2) (pane-exited; was lost)"
    assert cli.pauses_batch(escalated.to_dict()) is False


def test_retry_errors_reruns_error_cells_on_resume(layout, monkeypatch):
    calls = []
    outcomes = {("claude", "S1"): [(0, "delivered", "")], ("codex", "S1"): [(0, "delivered", "")]}
    monkeypatch.setattr(cli, "run_one", fake_run_one(outcomes, calls))
    checkpoint.append_record(layout.raw_jsonl, full_record(cli.make_cell("pilot", "claude", "tmux-paste", "S1", 1),
                                                           "error", "precondition: modal not visible"))
    checkpoint.append_record(layout.raw_jsonl, full_record(cli.make_cell("pilot", "codex", "tmux-paste", "S1", 1),
                                                           "delivered"))
    assert matrix("--scenarios", "S1", "--resume") == 0
    assert calls == []
    assert matrix("--scenarios", "S1", "--resume", "--retry-errors") == 0
    assert calls == [("claude", "S1")]


def test_run_exit_status_matches_matrix_for_an_error_record(layout, monkeypatch):
    def launch(self, m, agent, mode="auto", adapter=None):
        target = Target(m.run_id, agent, "tmux", "none", layout.work_dir(m.run_id, agent),
                        layout.home_dir(m.run_id, agent), "ses_x", f"agentcomms:{m.run_id}-{agent}", None, None, 1)
        return m, Launched(target, Binary(agent, Path("/o/opencode"), "2.1.4"), {}, layout.root / "p.log", "", [])

    def run_cell(self, m, launched, adapter, scenario, stage, rep):
        return ResultRecord(m.run_id, stage, "opencode", {}, adapter.name, "tmux", "none", "S1", rep, "raw",
                            Delivery.ERROR, None, DraftFate.NA, Ack.NONE, False, 0, None, notes="precondition: x")

    monkeypatch.setattr(Engine, "launch", launch)
    monkeypatch.setattr(Engine, "run_cell", run_cell)
    monkeypatch.setattr(Engine, "resolved_session", lambda self, m, target: m)
    monkeypatch.setattr(Engine, "check_versions", lambda self, launched: True)
    assert run() == 6


def test_pilot_runs_one_cell_at_a_time_and_matrix_leaves_the_tmux_server_to_the_batch(layout, monkeypatch, capsys):
    seen = []

    def run_one(layout, progress, cell, keep=False, mode=None, exclude=cli.no_exclusions, on_run=None,
                kill_server=True):
        seen.append(kill_server)
        return cli.CellResult(0, {**cell, "delivery": "delivered", "notes": ""})

    stopped = []
    monkeypatch.setattr(cli, "run_one", run_one)
    monkeypatch.setattr(manifest, "stop_idle_server", lambda layout: stopped.append(True))
    assert matrix("--scenarios", "S1", "--max-concurrency", "3") == 0
    assert "clamped to 1 for stage pilot" in capsys.readouterr().out
    assert (seen, stopped) == ([False, False], [True])
    assert cli.concurrency("screen", 3) == 3


def test_pausing_records_include_crashes_and_auth_screens():
    assert cli.pauses_batch({"delivery": "env_error", "notes": "receiver-crashed (pane-exited; was lost)"})
    assert cli.pauses_batch({"delivery": "env_error", "notes": "auth-required: AuthRequiredError: x"})
    assert cli.requeues({"delivery": "env_error", "notes": "sleep-or-network"})


def test_cells_carry_the_adapter_backend(monkeypatch):
    from agentcomms import adapters

    class Served(adapters.TmuxPaste):
        @classmethod
        def backend_for(cls, agent):
            return "codex-app-server"

    monkeypatch.setitem(adapters.ADAPTERS, "served", Served)
    assert cli.make_cell("extensive", "codex", "served", "S12", 1)["backend"] == "codex-app-server"
    assert cli.make_cell("pilot", "codex", "tmux-paste", "S1", 1)["backend"] == "none"


def test_launch_refuses_an_adapter_for_another_agent(layout, monkeypatch, capsys):
    launched = []
    monkeypatch.setattr(Engine, "launch", lambda *a, **k: launched.append(a))
    assert cli.main(["launch", "--agent", "claude", "--adapter", "codex-remote-start"]) == 2
    assert "adapter codex-remote-start does not support claude" in capsys.readouterr().err
    assert launched == []
    assert not layout.runs.exists()


def test_a_failed_launch_reports_its_cause_and_cleans_up_the_run(layout, monkeypatch, capsys):
    cleaned = []
    monkeypatch.setattr(manifest, "cleanup", lambda layout, run_id, kill_server=True: cleaned.append(run_id) or
                        ["remaining harness processes: 0"])
    monkeypatch.setattr(Engine, "launch", raising(TmuxError("tmux pipe-pane failed: no server running")))
    assert cli.main(["launch", "--agent", "claude"]) == 1
    [run_id] = [p.name for p in layout.runs.iterdir()]
    assert cleaned == [run_id]
    assert capsys.readouterr().err.splitlines() == [
        f"launch failed for run {run_id}: TmuxError: tmux pipe-pane failed: no server running",
        "cleanup: remaining harness processes: 0"]


def test_launch_refuses_while_an_earlier_run_is_live(layout, monkeypatch, capsys):
    monkeypatch.setattr(manifest, "live_runs", lambda layout, exclude=frozenset(): ["20261029-000000-live"])
    monkeypatch.setattr(Engine, "launch", raising(AssertionError("launched")))
    assert cli.main(["launch", "--agent", "claude"]) == cli.LIVE_RUN
    assert "refused: runs with live processes: 20261029-000000-live" in capsys.readouterr().err


def test_engine_launch_refuses_an_unsupported_adapter_before_building_a_home(tmp_path):
    from agentcomms.adapters import make_adapter
    from agentcomms.engine import UnsupportedAdapterError

    engine = Engine(Layout(tmp_path))
    m = Manifest("20261025-000000-abcd", [], [], [], [])
    with pytest.raises(UnsupportedAdapterError, match="supports codex"):
        engine.launch(m, "claude", "auto", make_adapter("codex-queue", engine.host_for))
    assert not (tmp_path / "runs").exists()


def test_every_record_carries_the_os_version(layout, monkeypatch):
    monkeypatch.setattr(profiles, "os_label", lambda: "27.2 (26B123)")
    record = Engine(layout).plain_record(Manifest("r1", [], [], [], []), "claude", "tmux-paste", "pilot", "S1", 1,
                                         {"claude": "2.1.311"}, Delivery.ERROR, "x", "none", "tmux")
    assert record.versions == {"claude": "2.1.311", "os": "27.2 (26B123)"}


def completed(text: str, code: int = 0):
    return lambda *a, **k: subprocess.CompletedProcess(a, code, stdout=text, stderr="")


def raises(error: Exception):
    def run(*a, **k):
        raise error
    return run


def test_sandbox_probe_finds_not_sandboxed_anywhere_in_the_output():
    assert cli.probe_sandbox(completed("NOT SANDBOXED\n  Not running inside a nono sandbox\n")) is None
    assert cli.probe_sandbox(completed("warning: stale profile cache\nNOT SANDBOXED\n")) is None


def test_sandbox_probe_reports_a_sandboxed_coordinator():
    assert cli.probe_sandbox(completed("SANDBOXED\n  profile: claude-local\n")) == "SANDBOXED"


def test_sandbox_probe_treats_only_a_missing_nono_as_unsandboxed():
    assert cli.probe_sandbox(raises(FileNotFoundError("nono"))) is None


@pytest.mark.parametrize(("run", "state"), [
    (raises(subprocess.TimeoutExpired(["nono"], 15)), "unverifiable: TimeoutExpired"),
    (raises(PermissionError("nono")), "unverifiable: PermissionError"),
    (completed("", 3), "unverifiable: exit 3"),
])
def test_sandbox_probe_refuses_when_the_state_cannot_be_verified(run, state):
    assert cli.probe_sandbox(run) == state


def test_real_probe_wrapper_runs_nono_from_path(tmp_path, monkeypatch):
    nono = tmp_path / "nono"
    nono.write_text("#!/bin/sh\n[ \"$1 $2\" = \"why --self\" ] && echo 'SANDBOXED' && echo '  profile: stub'\n")
    nono.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    assert cli.probe_sandbox(subprocess.run) == "SANDBOXED"
    nono.write_text("#!/bin/sh\necho 'NOT SANDBOXED'\n")
    assert cli.probe_sandbox(subprocess.run) is None


@pytest.mark.parametrize("command", [
    ["run", "--agent", "claude", "--adapter", "tmux-paste"],
    ["matrix", "--agents", "claude", "--adapters", "tmux-paste", "--scenarios", "S1"],
    ["launch", "--agent", "claude"],
    ["hostcheck", "--hosts", "tmux"],
    ["iterm-holder"],
    ["probe-bg"],
    ["probe-claude-link"],
    ["scale"],
    ["s9", "--a", "claude", "--b", "codex", "--fwd", "codex-queue", "--back", "claude-uds-accept"],
])
def test_live_commands_refuse_when_the_coordinator_is_sandboxed(layout, monkeypatch, capsys, command):
    monkeypatch.setattr(cli, "coordinator_sandbox", lambda: "SANDBOXED")
    monkeypatch.setattr(Engine, "launch", raising(AssertionError("launched")))
    monkeypatch.setattr(Engine, "new_run", raising(AssertionError("new run")))
    assert cli.main(command) == cli.SANDBOXED
    assert "refused: the coordinator is sandboxed (SANDBOXED)" in capsys.readouterr().err
    assert not layout.raw_jsonl.exists()


def test_an_unverifiable_sandbox_state_is_refused_as_fail_closed(layout, monkeypatch, capsys):
    monkeypatch.setattr(cli, "coordinator_sandbox", lambda: "unverifiable: TimeoutExpired")
    monkeypatch.setattr(Engine, "new_run", raising(AssertionError("new run")))
    assert cli.main(["probe-bg"]) == cli.SANDBOXED
    err = capsys.readouterr().err
    assert "refused: could not verify that the coordinator is unsandboxed (unverifiable: TimeoutExpired); " \
           "failing closed" in err


def test_nono_mode_is_refused_until_the_launcher_wrapper_exists():
    assert "nono launcher wrapper" in cli.sandbox_refusal("nono", lambda: None, lambda: None)
    assert cli.sandbox_refusal("nono", lambda: "SANDBOXED", lambda: ["nono", "run"]) is None
    assert cli.sandbox_refusal("raw", lambda: None, lambda: None) is None


def test_records_and_cells_carry_the_requested_sandbox_mode(layout):
    cell = cli.make_cell("pilot", "claude", "tmux-paste", "S1", 1, "nono")
    assert cell["sandbox"] == "nono"
    record = Engine(layout, sandbox="nono").plain_record(Manifest("r1", [], [], [], []), "claude", "tmux-paste",
                                                         "pilot", "S1", 1, {}, Delivery.ERROR, "x", "none", "tmux")
    assert record.sandbox == "nono"
    assert [c["sandbox"] for c in cli.matrix_cells("pilot", ["claude"], ["tmux-paste"], ["S1"], 1, "nono")] == ["nono"]


def test_codex_binary_changing_mid_batch_aborts_the_batch(layout, monkeypatch):
    def launch(self, m, agent, mode="auto", adapter=None):
        target = Target(m.run_id, agent, "tmux", "none", layout.work_dir(m.run_id, agent),
                        layout.home_dir(m.run_id, agent), "ses_x", f"agentcomms:{m.run_id}-{agent}", None, None, 1)
        old = Binary("codex", Path("/r/0.164.0-aarch64-apple-darwin/bin/codex"), "0.164.0")
        return m, Launched(target, old, {"codex": "0.164.0"}, layout.root / "pane.log", "pane-regex", [])

    def run_cell(self, m, launched, adapter, scenario, stage, rep):
        return ResultRecord(m.run_id, stage, "codex", launched.versions, adapter.name, "tmux", "none", "S1", rep,
                            "raw", Delivery.DELIVERED, True, DraftFate.NA, Ack.ACKED, False, 0, 0.1)

    updated = Binary("codex", Path("/r/0.165.0-aarch64-apple-darwin/bin/codex"), "0.165.0")
    monkeypatch.setattr(profiles, "resolve", lambda agent, scratch, search_path: updated)
    monkeypatch.setattr(Engine, "launch", launch)
    monkeypatch.setattr(Engine, "run_cell", run_cell)
    monkeypatch.setattr(Engine, "resolved_session", lambda self, m, target: m)
    assert cli.main(["run", "--agent", "codex", "--adapter", "tmux-paste"]) == 3
    assert "codex version changed mid-run; batch aborted" in layout.progress_md.read_text()


def test_version_probe_timeout_after_the_cell_aborts_instead_of_crashing(layout, monkeypatch):
    def launch(self, m, agent, mode="auto", adapter=None):
        target = Target(m.run_id, agent, "tmux", "none", layout.work_dir(m.run_id, agent),
                        layout.home_dir(m.run_id, agent), "ses_x", f"agentcomms:{m.run_id}-{agent}", None, None, 1)
        return m, Launched(target, Binary("codex", Path("/c"), "0.164.0"), {"codex": "0.164.0"},
                           layout.root / "pane.log", "pane-regex", [])

    def run_cell(self, m, launched, adapter, scenario, stage, rep):
        return ResultRecord(m.run_id, stage, "codex", launched.versions, adapter.name, "tmux", "none", "S1", rep,
                            "raw", Delivery.DELIVERED, True, DraftFate.NA, Ack.ACKED, False, 0, 0.1)

    monkeypatch.setattr(profiles, "resolve", raises_resolve(subprocess.TimeoutExpired(["codex", "--version"], 30)))
    monkeypatch.setattr(Engine, "launch", launch)
    monkeypatch.setattr(Engine, "run_cell", run_cell)
    monkeypatch.setattr(Engine, "resolved_session", lambda self, m, target: m)
    assert cli.main(["run", "--agent", "codex", "--adapter", "tmux-paste"]) == 3


def test_version_probe_timeout_at_launch_is_a_retryable_env_error(layout, monkeypatch):
    monkeypatch.setattr(Engine, "launch", raising(subprocess.TimeoutExpired(["codex", "--version"], 30)))
    assert cli.main(["run", "--agent", "codex", "--adapter", "tmux-paste"]) == 0
    assert [r["delivery"] for r in raw(layout)] == ["env_error"]


def raises_resolve(error: Exception):
    def resolve(agent, scratch, search_path):
        raise error
    return resolve


def test_cleanup_needs_a_run_or_the_holder_flag(capsys):
    assert cli.main(["cleanup"]) == 2
    assert "needs a run id" in capsys.readouterr().err


def test_cleanup_with_only_the_holder_flag_closes_just_the_holder(layout, monkeypatch, capsys):
    monkeypatch.setattr(manifest, "close_iterm_holder", lambda: ["closed iTerm2 holder w1"])
    monkeypatch.setattr(manifest, "cleanup", raising(AssertionError("run cleanup")))
    assert cli.main(["cleanup", "--iterm-holder"]) == 0
    assert capsys.readouterr().out == "closed iTerm2 holder w1\n"


def test_error_records_keep_the_hosts_focus_notes(layout):
    class Host:
        def take_notes(self):
            return ["iterm-focus a -> b", "focus_stolen=yes"]
    engine = Engine(layout)
    engine.extra_hosts["iterm2"] = Host()
    record = engine.plain_record(Manifest("r1", [], [], [], []), "claude", "iterm2-text", "pilot", "S1", 1, {},
                                 Delivery.ERROR, "x" * 400, "none", "iterm2")
    assert record.notes.endswith("; iterm-focus a -> b; focus_stolen=yes") and len(record.notes) <= 300


def test_a_stranded_session_is_stopped_when_its_pid_cannot_be_read():
    from agentcomms.engine import pid_or_stop

    class Host:
        stopped = []

        def pane_pid(self, ref):
            raise HostError("gone")

        def stop(self, ref):
            self.stopped.append(ref)
    host = Host()
    with pytest.raises(HostError):
        pid_or_stop(host, "ref1")
    assert host.stopped == ["ref1"]


def test_concurrent_matrix_never_runs_two_cells_of_one_bridge_state_at_once(layout, monkeypatch):
    import threading
    import time as _time
    active: dict[str, int] = {}
    peak: dict[str, int] = {}
    agents_seen: set[str] = set()
    overlap = [0]
    lock = threading.Lock()

    def run_one(layout, progress, cell, keep=False, mode=None, exclude=cli.no_exclusions, on_run=None,
                kill_server=True):
        family = "agent-deck" if cell["mechanism"].startswith("agent-deck") else cell["mechanism"]
        with lock:
            agents_seen.add(cell["agent"])
            active[family] = active.get(family, 0) + 1
            peak[family] = max(peak.get(family, 0), active[family])
            overlap[0] = max(overlap[0], sum(active.values()))
        _time.sleep(0.05)
        with lock:
            active[family] -= 1
        return cli.CellResult(0, {**cell, "delivery": "delivered", "notes": ""})

    monkeypatch.setattr(cli, "run_one", run_one)
    assert cli.main(["matrix", "--stage", "screen", "--agents", "claude,codex,droid", "--adapters",
                     "agent-deck,agent-deck-composer-fallback,gc-nudge", "--scenarios", "S1,S4",
                     "--max-concurrency", "3"]) == 0
    assert peak == {"agent-deck": 1, "gc-nudge": 1}
    assert agents_seen == {"claude", "codex", "droid"}
    assert overlap[0] >= 2


def test_cell_locks_name_the_agent_and_any_shared_bridge_state():
    assert cli.cell_locks(cli.make_cell("screen", "codex", "agent-deck-composer-fallback", "S1", 1)) == frozenset(
        {"agent:codex", "state:agent-deck"})
    assert cli.cell_locks(cli.make_cell("screen", "claude", "intercom-accept", "S1", 1)) == frozenset(
        {"agent:claude", "state:intercom"})
    assert cli.cell_locks(cli.make_cell("screen", "pi", "pi-ext", "S1", 1)) == frozenset({"agent:pi"})


def test_matrix_time_budget_defaults_to_six_hours():
    args = cli.parser().parse_args(["matrix", "--agents", "pi", "--adapters", "tmux-paste"])
    assert args.time_budget == 360.0


def test_a_bridge_adapter_without_a_declared_shared_state_is_locked_by_its_own_name():
    from agentcomms.adapters import ADAPTERS, shared_state_of
    from agentcomms.adapters.bridge import BridgeAdapter

    class NewBridge(BridgeAdapter):
        name = "new-bridge"

    assert shared_state_of(NewBridge) == "new-bridge"
    bridges = [cls for cls in ADAPTERS.values() if cls.kind == "bridge"]
    assert bridges and all(shared_state_of(cls) for cls in bridges)


def test_run_time_budget_defaults_to_six_hours():
    args = cli.parser().parse_args(["run", "--agent", "pi", "--adapter", "tmux-paste"])
    assert args.time_budget == 360.0


def test_matrix_plans_only_agent_adapter_pairs_the_adapter_supports():
    cells = cli.matrix_cells("screen", ["claude", "pi"], ["tmux-paste", "pi-ext", "claude-channel"], ["S1"], 1)
    assert [(c["agent"], c["mechanism"]) for c in cells] == [
        ("claude", "tmux-paste"), ("claude", "claude-channel"), ("pi", "tmux-paste"), ("pi", "pi-ext")]
