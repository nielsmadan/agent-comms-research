import json
import signal
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcomms import backends, isolation, manifest, procs, sandbox, scoring, shortlist
from agentcomms.adapters import gc_nudge
from agentcomms.hosts import tmux, zellij, zmx
from agentcomms.model import Manifest, SendReceipt, Target
from agentcomms.paths import Layout
from agentcomms.procs import ProcRow
from agentcomms.scenarios.s9 import classify
from agentcomms.senders import guard

RUN = "20261029-010000-beef"


def target(layout: Layout, agent: str, home: Path, backend: str = "none", run_id: str = RUN) -> Target:
    return Target(run_id, agent, "tmux", backend, layout.work_dir(run_id, agent), home, None,
                  f"agentcomms:{run_id}-{agent}", None, None, None)


def test_snapshot_purge_removes_only_snapshots_of_a_codex_home_inside_the_run(tmp_path):
    layout = Layout(tmp_path / "repo")
    inside = layout.home_dir(RUN, "codex")
    outside = tmp_path / "user" / ".codex"
    for home in (inside, outside):
        (home / "shell_snapshots").mkdir(parents=True)
        (home / "shell_snapshots" / "a.sh").write_text("export X=1\n")
    m = Manifest(RUN, [], [target(layout, "codex", outside), target(layout, "codex", inside)], [], [])
    assert manifest.purge_env_snapshots(layout, m) == ["removed 1 Codex shell snapshots (exported env)"]
    assert (outside / "shell_snapshots" / "a.sh").exists()
    assert list((inside / "shell_snapshots").iterdir()) == []


def test_a_codex_backend_with_a_home_outside_the_run_is_refused_before_it_starts(tmp_path, monkeypatch):
    run_dir = tmp_path / "runs" / RUN
    user = tmp_path / "user"
    spec = backends.BackendSpec("codex-daemon", ["codex", "app-server", "daemon", "start"],
                                {"CODEX_HOME": str(user / ".codex")}, str(tmp_path), None, str(tmp_path / "log"))
    assert backends.spec_problem(spec, run_dir, user).startswith(f"CODEX_HOME {user / '.codex'} is not under")
    sibling = tmp_path / "runs" / "20261029-010000-ffff" / "home" / "codex"
    for kind in ("codex-daemon", "codex-app-server"):
        other = backends.BackendSpec(kind, spec.argv, {"CODEX_HOME": str(sibling)}, str(tmp_path), None, "log")
        assert backends.spec_problem(other, run_dir, user) == f"CODEX_HOME {sibling} is not under {run_dir / 'home'}"

    def started(*a, **k):
        raise AssertionError("a process was started")
    monkeypatch.setattr(backends.subprocess, "run", started)
    monkeypatch.setattr(backends.subprocess, "Popen", started)
    with pytest.raises(isolation.IsolationError, match="is not under"):
        backends.start(spec, run_dir, user)


def test_a_registered_service_pid_counts_only_with_its_cwd_inside_the_runs_home(tmp_path, monkeypatch):
    run_dir = tmp_path / "runs" / RUN
    registration = tmp_path / "service.json"
    registration.write_text(json.dumps({"pid": 4242}))
    monkeypatch.setattr(procs, "alive", lambda pid: True)
    monkeypatch.setattr(procs, "cwds", lambda pids: {4242: str(tmp_path / "user" / ".local")})
    assert backends.service_pid_in_run(registration, run_dir) is None
    monkeypatch.setattr(procs, "cwds", lambda pids: {4242: str(run_dir / "home" / "opencode")})
    assert backends.service_pid_in_run(registration, run_dir) == 4242


def test_cleanup_never_stops_a_registered_service_running_outside_the_run(tmp_path, monkeypatch):
    layout = Layout(tmp_path / "repo")
    home = layout.home_dir(RUN, "opencode")
    (home / "state" / "opencode").mkdir(parents=True)
    (home / "state" / "opencode" / "service.json").write_text(json.dumps({"pid": 4242}))
    stopped = []
    monkeypatch.setattr(procs, "alive", lambda pid: True)
    monkeypatch.setattr(procs, "cwds", lambda pids: {4242: "/Users/someone"})
    monkeypatch.setattr(backends, "stop_group", lambda pid, **k: stopped.append(pid))
    assert manifest.stop_registered_services(layout, Manifest(RUN, [], [target(layout, "opencode", home)], [], [])) \
        == []
    assert stopped == []


def test_cleanup_signals_only_bridge_daemons_whose_identity_still_matches(monkeypatch):
    m = Manifest(RUN, [], [], [], ["bridge-daemon:10", "codex-daemon:11", "bridge-daemon:12"],
                 {10: "a", 11: "b", 12: "c"})
    signalled = []
    monkeypatch.setattr(procs, "identities", lambda pids: {p: i for p, i in {10: "a", 11: "b", 12: "reused"}.items()
                                                           if p in pids})
    monkeypatch.setattr(procs, "alive", lambda pid: True)
    monkeypatch.setattr(manifest, "_signal", lambda pids, sig: signalled.append((set(pids), sig)))
    assert manifest.stop_bridge_daemons(m, grace_s=0.0) == ["stopped bridge daemon pid 10"]
    assert signalled == [({10}, signal.SIGTERM), ({10}, signal.SIGKILL)]


def test_cleanup_keeps_credentials_while_harness_processes_remain(tmp_path, monkeypatch):
    layout = Layout(tmp_path / "repo")
    purged = []
    monkeypatch.setattr(manifest, "_tmux",
                        lambda layout, *args, socket="agentcomms": subprocess.CompletedProcess(args, 1, "", ""))
    monkeypatch.setattr(manifest, "SOCKET_DIR", tmp_path / "ac")
    monkeypatch.setattr(manifest, "CLAUDE_SOCK_DIR", tmp_path / "cc-socks")
    monkeypatch.setattr(manifest, "run_pids", lambda layout, m, rows: {999999})
    monkeypatch.setattr(manifest, "sweep", lambda layout, m, grace_s: 0)
    monkeypatch.setattr(manifest, "purge_run_credentials", lambda layout, m: purged.append("creds") or [])
    monkeypatch.setattr(manifest, "purge_env_snapshots", lambda layout, m: purged.append("snapshots") or [])
    manifest.save(layout, Manifest(RUN, [], [target(layout, "opencode", layout.home_dir(RUN, "opencode"))], [], []))
    report = manifest.cleanup(layout, RUN, grace_s=0.0, kill_server=False)
    assert report[-1] == "remaining harness processes: 1"
    assert purged == []


def test_live_runs_leaves_out_the_excluded_sibling_runs(tmp_path, monkeypatch):
    layout = Layout(tmp_path / "repo")
    first, second = "20261029-010000-aaaa", "20261029-010001-bbbb"
    for run_id in (first, second):
        manifest.save(layout, Manifest(run_id, [], [], [], []))
    monkeypatch.setattr(procs, "ps_rows", lambda: [])
    monkeypatch.setattr(manifest, "run_pids", lambda layout, m, rows: {123})
    assert manifest.live_runs(layout, frozenset({first})) == [second]


def test_owned_pids_do_not_extend_to_a_sibling_run_dir(tmp_path):
    run_dir = tmp_path / "runs" / RUN
    rows = [ProcRow(11, 1, 11, "claude"), ProcRow(12, 1, 12, "claude")]
    cwd_map = {11: str(run_dir) + "x/work", 12: str(run_dir / "work")}
    assert procs.owned_pids(rows, {11, 12}, cwd_map, run_dir) == {12}


def test_vendored_processes_need_the_vendor_dir_itself(tmp_path):
    vendor = tmp_path / "vendor"
    rows = [ProcRow(1, 0, 1, f"{tmp_path}/vendor-other/bin/x"), ProcRow(2, 0, 2, f"{vendor.resolve()}/hcom/bin/hcom")]
    assert procs.vendored(rows, vendor) == {2}


def manifest_dict(tmp_path: Path, pid: int, idents: dict | None, backends_list: list | None = None) -> dict:
    home = tmp_path / "runs" / RUN / "home" / "claude"
    home.mkdir(parents=True, exist_ok=True)
    data = {"run_id": RUN, "pgids": [], "sockets": [], "backends": backends_list or [],
            "targets": [{"agent": "claude", "agent_pid": pid, "home_dir": str(home), "backend_ref": None}]}
    if idents is not None:
        data["identities"] = idents
    return data


def test_a_legacy_target_without_identity_and_a_dead_pid_is_not_owned(tmp_path):
    data = manifest_dict(tmp_path, 4242, None, ["codex-daemon:4242"])
    assert guard.owned_pid(data, 4242, {}) is False
    assert guard.live_backends(data, "codex-daemon", {}) == []
    with pytest.raises(guard.GuardError, match="not the process"):
        guard.check_claude_target(data, Path(data["targets"][0]["home_dir"]), 4242, {})


def test_a_claude_target_must_match_its_config_dir_as_well_as_pid_and_identity(tmp_path):
    data = manifest_dict(tmp_path, 4242, {"4242": "id-1"})
    other = tmp_path / "runs" / RUN / "home" / "other"
    with pytest.raises(guard.GuardError, match="is not a target"):
        guard.check_claude_target(data, other, 4242, {4242: "id-1"})


def test_only_the_registry_socket_dir_holds_an_owned_claude_socket():
    assert guard.owned_claude_socket("/tmp/cc-socks/42.sock", 42) is True
    assert guard.owned_claude_socket("/tmp/elsewhere/42.sock", 42) is False


def test_the_runs_root_itself_is_not_a_run_dir(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    with pytest.raises(guard.GuardError, match="is not inside"):
        guard.run_dir_for(runs, runs)


class Recorded:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs.get("env"), kwargs.get("cwd")))
        return subprocess.CompletedProcess(argv, 0, "", "")


def test_zmx_teardown_runs_with_the_runs_own_zmx_state(tmp_path, monkeypatch):
    run = Recorded()
    monkeypatch.setattr(zmx.subprocess, "run", run)
    state = tmp_path / f"{RUN}-zmx"
    zmx.ZmxHost(Path("/v/zmx")).stop(zmx.make_ref(state, "recv"))
    assert run.calls == [(["/v/zmx", "kill", "recv", "--force"], zmx.zmx_env(state), state)]


def test_zellij_teardown_runs_with_the_runs_own_zellij_state(tmp_path, monkeypatch):
    run = Recorded()
    monkeypatch.setattr(zellij.subprocess, "run", run)
    state = tmp_path / f"{RUN}-zj"
    zellij.ZellijHost(Path("/v/zellij")).stop(zellij.make_ref(state, "recv"))
    env = zellij.zellij_env(state)
    assert run.calls == [(["/v/zellij", "kill-session", "recv"], env, state),
                         (["/v/zellij", "delete-session", "--force", "recv"], env, state),
                         (zellij.action_argv(Path("/v/zellij"), "recv", "list-panes", "--all", "--json"), env, state)]


def test_tmux_stop_kills_the_session_by_exact_name(tmp_path, monkeypatch):
    run = Recorded()
    monkeypatch.setattr(tmux.subprocess, "run", run)
    tmux.TmuxHost(tmp_path / "tmux.conf").stop(f"agentcomms:{RUN}-claude")
    [(argv, _, _)] = run.calls
    assert argv[-3:] == ["kill-session", "-t", f"={RUN}-claude"]


SAFETY = {"run_id": "r", "stage": "extensive", "agent": "droid", "mechanism": "m", "delivery": "delivered",
          "intact": True, "draft_fate": "n/a", "harmful": False, "notes": "", "versions": {"droid": "0.251.0"}}


def test_safety_counts_only_safety_scenarios_while_other_good_records_raise_k():
    base = ([SAFETY | {"scenario": "S2", "delivery": "queued"}] * 3
            + [SAFETY | {"scenario": "S7", "draft_fate": "merged"}] * 3
            + [SAFETY | {"scenario": "S3", "harmful": True}])
    more = [*base, SAFETY | {"scenario": "S1"}, SAFETY | {"scenario": "S4"}]
    before = shortlist.score(shortlist.with_equivalence(shortlist.counted_records(base))[("droid", "m")])
    after = shortlist.score(shortlist.with_equivalence(shortlist.counted_records(more))[("droid", "m")])
    assert (before.safety_k, after.safety_k) == (3, 3)
    assert after.k == before.k + 2


S9_TOKEN = "1d9d1d74"
S9_REQUEST = f'ACK-REQUEST {S9_TOKEN}: reply with exactly "ACK {S9_TOKEN}". relay'
S9_FWD = ("to-b.txt", S9_TOKEN)
S9_BACK = (f"reply-{S9_TOKEN}.txt", f"ACK {S9_TOKEN}")
A_SENT = (10.0, "tool_use", "send.sh < /r/s9/to-b.txt")
B_SEEN = (11.0, "user", f"framed: {S9_REQUEST}")
A_GETS = (13.0, "peer", f"<frame from b> ACK {S9_TOKEN}")


def b_send(ts: float):
    return (ts, "tool_use", f"send-a < /r/s9/reply-{S9_TOKEN}.txt")


def test_a_b_send_before_b_received_the_message_is_not_a_reply():
    v = classify([A_SENT, A_GETS], [b_send(10.9), B_SEEN], S9_TOKEN, S9_FWD, S9_BACK)
    assert (v.roundtrip, v.blocker) == (False, "b-did-not-reply")


def test_a_b_send_after_a_already_had_the_reply_is_not_the_reply():
    v = classify([A_SENT, A_GETS], [B_SEEN, b_send(14.0)], S9_TOKEN, S9_FWD, S9_BACK)
    assert (v.roundtrip, v.blocker) == (False, "b-did-not-reply")


def test_an_a_send_after_the_reply_arrived_does_not_cancel_the_round_trip():
    v = classify([A_SENT, A_GETS, b_send(14.0)], [B_SEEN, b_send(12.0)], S9_TOKEN, S9_FWD, S9_BACK)
    assert (v.roundtrip, v.blocker) == (True, None)


def scored(scenario: str, **fields) -> bool:
    return scoring.is_good({"scenario": scenario, "delivery": "delivered", "intact": True, "harmful": False,
                            "draft_fate": "n/a", "notes": ""} | fields)


def test_s8_is_good_only_when_the_push_rendered():
    assert scored("S8", notes="rendered=yes") is True
    assert scored("S8", notes="rendered=no") is False
    assert scored("S8", notes="rendered=reply-only") is False


def test_s6_is_good_only_when_the_down_message_was_rejected_or_queued():
    assert scored("S6", notes="down=queued; session=same") is True
    assert scored("S6", notes="down=rejected") is True
    assert scored("S6", notes="down=lost") is False


def test_s11_is_not_good_when_the_send_changed_the_model():
    assert scored("S11") is True
    assert scored("S11", harmful=True) is False


class FakePopen:
    seen: dict = {}

    def __init__(self, argv, **kwargs):
        FakePopen.seen = {"argv": argv, "env": kwargs["env"]}
        self.pid, self.returncode = 77, 0

    def communicate(self, text, timeout):
        return "queued", ""


def test_the_sandboxed_sender_runs_the_agents_sender_inside_nono(tmp_path, monkeypatch):
    adapter = SimpleNamespace(name="pi-ext", kind="native", sender_argv=lambda t: ["python3", "-I", "s.py"])
    monkeypatch.setattr(sandbox.subprocess, "Popen", FakePopen)
    sender = sandbox.SandboxedSender(adapter, "pi", "/n/nono", tmp_path / "user",
                                     {"PATH": "/usr/bin", "XDG_CONFIG_HOME": "/r/c"})
    receipt = sender.send(SimpleNamespace(work_dir=tmp_path), "hi")
    assert receipt.accepted is True
    assert FakePopen.seen["argv"][:6] == ["/n/nono", "run", "--no-audit", "-p", "pi-local", "--"]
    assert FakePopen.seen["argv"][-3:] == ["python3", "-I", "s.py"]
    assert not any(k.startswith("XDG_") for k in FakePopen.seen["env"])


def test_the_sandboxed_terminal_sender_runs_tmux_inside_nono(tmp_path):
    class Terminal:
        name, kind = "tmux-paste", "terminal"

        def __init__(self, host):
            self.host = host

        def send(self, target, text):
            Terminal.used = self.host
            return SendReceipt(True, 1.0, 1.0)

    sender = sandbox.SandboxedSender(Terminal(tmux.TmuxHost(tmp_path / "tmux.conf")), "claude", "/n/nono",
                                     tmp_path / "user", {"PATH": "/usr/bin"})
    sender.send(SimpleNamespace(work_dir=tmp_path), "hi")
    assert isinstance(Terminal.used, sandbox.SandboxedTmuxHost)
    assert Terminal.used.prefix[:6] == ["/n/nono", "run", "--silent", "--no-audit", "-p", "claude-local"]


@pytest.mark.parametrize("key", ["HOME", "GC_HOME", "GC_CITY", "GC_CEILING_DIRECTORIES"])
def test_gc_refuses_each_pinned_variable_outside_the_run(tmp_path, key):
    env = {k: str(tmp_path / k.lower()) for k in ("HOME", "GC_HOME", "GC_CITY", "GC_CEILING_DIRECTORIES")}
    with pytest.raises(isolation.IsolationError, match=key):
        gc_nudge.require_run_env(env | {key: "/Users/u"}, tmp_path)


def test_start_server_launches_through_a_private_env_file(tmp_path, monkeypatch):
    seen = {}

    class Proc:
        pid = 4321

    def popen(argv, **kwargs):
        seen["argv"] = argv
        return Proc()
    monkeypatch.setattr(backends.subprocess, "Popen", popen)
    monkeypatch.setattr(backends, "wait_socket", lambda sock, timeout: True)
    spec = backends.BackendSpec("opencode-server", ["/v/opencode", "serve"],
                                {"PATH": "/usr/bin", "OPENCODE_PASSWORD": "pw-123"}, str(tmp_path), "http://x:1",
                                str(tmp_path / "backend.log"))
    assert backends.start_server(spec) == 4321
    assert seen["argv"][:2] == ["/usr/bin/env", "-i"]
    assert not any("pw-123" in a for a in seen["argv"])
    secret = backends.secret_env_file(spec)
    assert secret.stat().st_mode & 0o777 == 0o600 and "pw-123" in secret.read_text()
