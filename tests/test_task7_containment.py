import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from agentcomms import cli, isolation, manifest, procs
from agentcomms.adapters import agent_deck, csd, gc_nudge, hcom, intercom
from agentcomms.adapters.bridge import CliResult, contained_path, tools_dir
from agentcomms.engine import Engine, Launched
from agentcomms.hosts.tmux import socket_args
from agentcomms.model import Manifest, Target
from agentcomms.paths import SOCKET_DIR, Layout
from agentcomms.procs import ProcRow
from agentcomms.profiles import Binary
from agentcomms.scenarios.s9 import attribution, classify

RUN = "20261027-180000-c0de"
SOPS = "/Users/u/ac/bin/sops-exec"
TOKEN = "1d9d1d74"
REQUEST = f'ACK-REQUEST {TOKEN}: reply with exactly "ACK {TOKEN}". relay; reply via reply-{TOKEN}.txt'
FWD = ("to-b.txt", TOKEN)
BACK = (f"reply-{TOKEN}.txt", f"ACK {TOKEN}")


def work(tmp_path: Path, slot: str) -> Path:
    path = tmp_path / "runs" / RUN / "work" / slot
    path.mkdir(parents=True, exist_ok=True)
    return path


def exec_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


class Calls:
    def __init__(self, stdout: str = ""):
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self.stdout = stdout

    def __call__(self, argv, env, stdin=None, cwd=None, timeout_s=30.0):
        self.calls.append((list(argv), dict(env)))
        return CliResult(0, self.stdout, "")

    def find(self, word: str) -> tuple[list[str], dict[str, str]]:
        return next(c for c in self.calls if word in c[0])


class FakeHost:
    def alive(self, ref: str) -> bool:
        return True


class FakeProc:
    pid = 4321

    def poll(self):
        return None


def user_path(tmp_path: Path) -> str:
    mise_shims = tmp_path / "user" / ".local" / "share" / "mise" / "shims"
    exec_file(mise_shims / "gc")
    exec_file(tmp_path / "user" / ".local" / "bin" / "mise")
    exec_file(tmp_path / "user" / "brew" / "agent-deck")
    exec_file(tmp_path / "user" / "sops" / "sops")
    return ":".join([str(mise_shims), str(tmp_path / "user" / ".local" / "bin"), str(tmp_path / "user" / "brew"),
                     str(tmp_path / "user" / "sops"), "/usr/bin", "/bin"])


def agent_env(tmp_path: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    return {"PATH": user_path(tmp_path), "HOME": "/Users/u", "CLAUDE_CONFIG_DIR": str(tmp_path / "h")} | (extra or {})


def script_argv(script: Path) -> list[str]:
    return shlex.split(script.read_text().splitlines()[-1])


def env_words(argv: list[str]) -> dict[str, str]:
    return dict(w.split("=", 1) for w in argv if "=" in w and not w.startswith(("-", "/")))


@pytest.fixture
def gc_launch(tmp_path, monkeypatch):
    calls = Calls(json.dumps([{"alias": "recv-claude", "session_name": "recv-claude"}]))
    monkeypatch.setattr(gc_nudge, "run_cli", calls)
    monkeypatch.setattr(gc_nudge, "vendored", lambda p: p)
    monkeypatch.setattr(gc_nudge, "free_port", lambda: 45678)
    monkeypatch.setattr(gc_nudge.subprocess, "Popen", lambda *a, **k: FakeProc())
    adapter = gc_nudge.GcNudge(FakeHost())
    cwd = work(tmp_path, "claude")
    ref = adapter.start_session("s", [SOPS, "/bin/2.1.311", "--model", "haiku"], agent_env(tmp_path), cwd)
    return adapter, cwd, ref, calls


def test_gc_runs_its_own_supervisor_port_city_and_tmux_server(gc_launch):
    _adapter, cwd, ref, calls = gc_launch
    home = gc_nudge.gc_home(cwd)
    assert (home / "supervisor.toml").read_text() == '[supervisor]\nport = 45678\nbind = "127.0.0.1"\n'
    assert ref == f"agentcomms-{RUN}-claude:recv-claude"
    listing, env = calls.find("list")
    assert listing[listing.index("--city") + 1] == str(gc_nudge.city_dir(cwd))
    assert (env["HOME"], env["GC_HOME"]) == (str(home), str(home))
    send = script_argv(gc_nudge.send_script(cwd))
    assert send[send.index("--city") + 1] == str(gc_nudge.city_dir(cwd))
    assert env_words(send)["GC_CITY"] == str(gc_nudge.city_dir(cwd))
    assert script_argv(gc_nudge.shim_dir(cwd) / "tmux")[2:4] == ["-S", str(SOCKET_DIR / f"agentcomms-{RUN}-claude")]


def test_gc_agent_shell_resolves_gc_to_the_run_pinned_vendored_wrapper(gc_launch, tmp_path):
    _adapter, cwd, _ref, _calls = gc_launch
    shim = script_argv(gc_nudge.shim_dir(cwd) / f"ac-{cwd.name}")
    inner = shim[shim.index(SOPS):]
    assert inner[1] == "/usr/bin/env"
    pins = env_words(inner[:inner.index("/bin/2.1.311")])
    run = tmp_path / "runs" / RUN
    assert pins["HOME"] == str(gc_nudge.agent_home(cwd))
    assert (pins["GC_CITY"], pins["GC_CEILING_DIRECTORIES"]) == (str(gc_nudge.city_dir(cwd)), str(run))
    tool = tools_dir(cwd) / "gc"
    assert shutil.which("gc", path=pins["PATH"]) == str(tool)
    assert shutil.which("mise", path=pins["PATH"]) is None
    assert str(tmp_path / "user" / "sops") in pins["PATH"].split(":")
    wrapped = script_argv(tool)
    assert wrapped[wrapped.index(str(gc_nudge.GC)) + 1:][:2] == ["--city", str(gc_nudge.city_dir(cwd))]
    assert env_words(wrapped)["GC_HOME"] == str(gc_nudge.gc_home(cwd))
    hook_path = f"{pins['HOME']}/go/bin:{pins['HOME']}/.local/bin:{pins['PATH']}"
    assert Path(shutil.which("gc", path=hook_path)).resolve() == tool.resolve()


def test_gc_refuses_an_env_that_leaves_the_run(tmp_path, monkeypatch):
    with pytest.raises(isolation.IsolationError, match="HOME"):
        gc_nudge.require_run_env({"HOME": "/Users/u", "GC_HOME": str(tmp_path)}, tmp_path)


def test_gc_records_its_version_only_for_the_reviewed_binary(tmp_path, monkeypatch):
    binary = tmp_path / "gc"
    binary.write_bytes(b"not gc")
    monkeypatch.setattr(gc_nudge, "vendored", lambda p: binary)
    gc_nudge.gc_version.cache_clear()
    try:
        assert gc_nudge.gc_version().startswith("unknown (sha256 ")
    finally:
        gc_nudge.gc_version.cache_clear()


def test_agent_deck_runs_on_the_harness_tmux_server_with_a_pinned_notify_tool(tmp_path, monkeypatch):
    calls = Calls(json.dumps({"sessions": [{"title": "s", "tmux_session": "agentdeck_s_1"}]}))
    monkeypatch.setattr(agent_deck, "run_cli", calls)
    monkeypatch.setattr(agent_deck, "vendored", lambda p: p)
    cwd = work(tmp_path, "codex")
    env = agent_env(tmp_path, {"CODEX_HOME": str(tmp_path / "codex-home")})
    ref = agent_deck.AgentDeck(FakeHost()).start_session("s", [SOPS, "/bin/codex"], env, cwd)
    assert ref == "agentcomms:agentdeck_s_1"
    added, ad_env = calls.find("add")
    assert added[added.index("--tmux-socket") + 1] == "agentcomms"
    assert ad_env["HOME"] == str(agent_deck.ad_home(cwd))
    assert calls.find("codex-hooks")[1]["CODEX_HOME"] == str(tmp_path / "codex-home")
    shim_text = (agent_deck.shim_dir(cwd) / "ac-codex").read_text()
    assert '"AGENTDECK_INSTANCE_ID=${AGENTDECK_INSTANCE_ID-}"' in shim_text
    path = env_words(script_argv(agent_deck.shim_dir(cwd) / "ac-codex"))["PATH"]
    tool = tools_dir(cwd) / "agent-deck"
    assert shutil.which("agent-deck", path=path) == str(tool)
    wrapped = script_argv(tool)
    assert env_words(wrapped)["CODEX_HOME"] == str(tmp_path / "codex-home")
    assert env_words(wrapped)["XDG_CONFIG_HOME"].startswith(str(agent_deck.ad_home(cwd)))
    assert '"AGENTDECK_INSTANCE_ID=${AGENTDECK_INSTANCE_ID-}"' in tool.read_text()


def test_csd_keeps_its_worker_dir_in_the_run(tmp_path, monkeypatch):
    calls = Calls()
    monkeypatch.setattr(csd, "run_cli", calls)
    monkeypatch.setattr(csd, "vendored", lambda p: p)
    monkeypatch.setattr(csd, "node", lambda: "/bin/node")
    cwd = work(tmp_path, "claude")
    ref = csd.Csd(FakeHost()).start_session("w1", [SOPS, "/bin/claude", "--session-id", "x"], agent_env(tmp_path), cwd)
    assert ref == "agentcomms:w1"
    _launch, env = calls.find("launch")
    assert env["CSD_WORKER_DIR"] == str(tmp_path / "runs" / RUN / "csd")
    assert env["HOME"] == str(csd.csd_home(cwd))
    assert env_words(script_argv(csd.send_script(cwd)))["CSD_WORKER_DIR"] == env["CSD_WORKER_DIR"]


def test_codex_intercom_launch_points_every_component_at_the_run_broker(tmp_path, monkeypatch):
    monkeypatch.setattr(intercom, "node", lambda: "/bin/node")
    monkeypatch.setattr(intercom, "vendored", lambda p: p)
    cwd = work(tmp_path, "codex")
    mods = intercom.Intercom().launch_mods("codex", cwd, tmp_path)
    flags = dict(zip(mods.launcher[::1], mods.launcher[1::1], strict=False))
    configs = [mods.launcher[i + 1] for i, a in enumerate(mods.launcher) if a == "-c"]
    run_dir = str(SOCKET_DIR / f"{RUN}-ic")
    assert f"mcp_servers.codex-intercom.env.PI_CODING_AGENT_DIR={json.dumps(run_dir)}" in configs
    assert flags["--cwd"] == str(cwd)
    assert mods.env["PI_CODING_AGENT_DIR"] == run_dir


def test_intercom_sender_talks_only_to_the_run_broker(tmp_path, monkeypatch):
    cwd = work(tmp_path, "pi")
    calls = Calls(json.dumps([{"name": "pi", "cwd": str(cwd)}]))
    monkeypatch.setattr(intercom, "run_cli", calls)
    monkeypatch.setattr(intercom, "node", lambda: "/bin/node")
    monkeypatch.setattr(intercom, "vendored", lambda p: p)
    target = Target(RUN, "pi", "tmux", "none", cwd, tmp_path, None, "agentcomms:x", None, None, None)
    intercom.Intercom().send(target, "hi")
    assert {c[1]["PI_CODING_AGENT_DIR"] for c in calls.calls} == {str(SOCKET_DIR / f"{RUN}-ic")}
    assert {c[1]["HOME"] for c in calls.calls} == {str(SOCKET_DIR / f"{RUN}-ic")}


@pytest.mark.parametrize(("adapter", "tool"), [("gc-nudge", "gc"), ("agent-deck", "agent-deck"), ("hcom", "hcom")])
def test_bridge_instructed_tools_resolve_to_vendored_run_pinned_binaries(tmp_path, monkeypatch, adapter, tool):
    for module in (gc_nudge, agent_deck):
        listing = {"sessions": [{"title": "s", "tmux_session": "t", "alias": "recv-claude",
                                 "session_name": "recv-claude"}]}
        monkeypatch.setattr(module, "run_cli", Calls(json.dumps(listing)))
        monkeypatch.setattr(module, "vendored", lambda p: p)
    if adapter == "hcom" and not hcom.HCOM.is_file():
        pytest.skip(f"gitignored vendor entry absent: {hcom.HCOM}")
    monkeypatch.setattr(gc_nudge, "free_port", lambda: 45678)
    monkeypatch.setattr(gc_nudge.subprocess, "Popen", lambda *a, **k: FakeProc())
    cwd = work(tmp_path, "claude")
    run = tmp_path / "runs" / RUN
    env = agent_env(tmp_path)
    if adapter == "hcom":
        mods = hcom.Hcom().launch_mods("claude", cwd, tmp_path)
        path, pinned = ":".join([*mods.path_prepend, env["PATH"]]), mods.env
    elif adapter == "gc-nudge":
        gc_nudge.GcNudge(FakeHost()).start_session("s", [SOPS, "/bin/claude"], env, cwd)
        shim = script_argv(gc_nudge.shim_dir(cwd) / "ac-claude")
        path = env_words(shim[shim.index(SOPS):])["PATH"]
        pinned = env_words(script_argv(tools_dir(cwd) / tool))
    else:
        agent_deck.AgentDeck(FakeHost()).start_session("s", [SOPS, "/bin/claude"], env, cwd)
        path = env_words(script_argv(agent_deck.shim_dir(cwd) / "ac-claude"))["PATH"]
        pinned = env_words(script_argv(tools_dir(cwd) / tool))
    found = Path(shutil.which(tool, path=path) or "/missing")
    assert found.is_relative_to(run) or found.is_relative_to(hcom.HCOM.parent)
    state = {k: v for k, v in pinned.items() if k in ("HOME", "GC_HOME", "GC_CITY", "HCOM_DIR", "XDG_CONFIG_HOME")}
    assert state and all(Path(v).is_relative_to(run) for v in state.values())


def test_contained_path_drops_user_installs_and_version_manager_shims(tmp_path):
    path = contained_path(user_path(tmp_path), ("/run/tools",), ("gc", "mise"))
    assert path.split(":")[0] == "/run/tools"
    assert shutil.which("gc", path=path) is None and shutil.which("mise", path=path) is None
    assert shutil.which("sops", path=path) == str(tmp_path / "user" / "sops" / "sops")


def test_contained_path_drops_an_empty_version_manager_shims_dir(tmp_path):
    empty = tmp_path / "other" / "mise" / "shims"
    empty.mkdir(parents=True)
    path = contained_path(f"{empty}:/usr/bin", ("/run/tools",), ("gc", "mise"))
    assert path.split(":") == ["/run/tools", "/usr/bin"]


def test_codex_config_turns_off_shell_snapshots(tmp_path):
    config = isolation.codex_config(tmp_path / "w", tmp_path, "m", "low")
    assert "[features]\nshell_snapshot = false\n" in config


def test_cleanup_purges_codex_shell_snapshots_of_the_run(tmp_path):
    layout = Layout(tmp_path)
    home = layout.home_dir(RUN, "codex")
    (home / "shell_snapshots").mkdir(parents=True)
    (home / "shell_snapshots" / "a.sh").write_text("export X=1\n")
    target = Target(RUN, "codex", "tmux", "none", layout.work_dir(RUN, "codex"), home, None, "agentcomms:x", None,
                    None, None)
    m = Manifest(RUN, [], [target], [], [])
    assert manifest.purge_env_snapshots(layout, m) == ["removed 1 Codex shell snapshots (exported env)"]
    assert list((home / "shell_snapshots").iterdir()) == []


def test_vendored_bridge_processes_running_in_the_run_are_swept(tmp_path, monkeypatch):
    layout = Layout(tmp_path)
    run_dir = layout.run_dir(RUN)
    gc_proc = ProcRow(70, 1, 70, f"{(tmp_path / 'vendor').resolve()}/gc/bin/gc supervisor run")
    monkeypatch.setattr(procs, "cwds", lambda pids: {70: str(run_dir / "gc" / "claude" / "city")} if 70 in pids else {})
    monkeypatch.setattr(procs, "identities", lambda pids: {})
    m = Manifest(RUN, [], [], [], [])
    assert manifest.run_pids(layout, m, [gc_proc, ProcRow(71, 1, 71, "/usr/bin/gc supervisor run")]) == {70}


def test_user_gc_supervisors_are_told_apart_from_vendored_ones(tmp_path):
    rows = [ProcRow(1, 1, 1, "/Users/u/.local/share/mise/installs/gascity/1.4.0/gc supervisor run"),
            ProcRow(2, 1, 2, f"{(tmp_path / 'vendor').resolve()}/gc/bin/gc supervisor run")]
    assert isolation.gc_supervisors(rows, tmp_path / "vendor") == [1]


@pytest.fixture
def guarded(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gc").mkdir()
    (home / ".gc" / "events.jsonl").write_text("{}\n")
    monkeypatch.setenv("HOME", str(home))
    layout = Layout(tmp_path / "repo")
    monkeypatch.setattr(cli, "default_layout", lambda: layout)
    monkeypatch.setattr(manifest, "cleanup", lambda layout, run_id, kill_server=True: [])
    monkeypatch.setattr(manifest, "remaining_pids", lambda layout, run_id: set())
    monkeypatch.setattr(manifest, "refuse_if_live", lambda layout, exclude=frozenset(): None)
    monkeypatch.setattr(isolation, "global_config_hashes", lambda: {})
    monkeypatch.setattr(isolation, "user_state_mtimes", lambda agent: {})
    monkeypatch.setattr(procs, "ps_rows", lambda: [])
    return home, layout


WATCHED = [".gc/settings.json", ".gc/nudges/n.json", ".gc/scripts/gc-beads-bd.sh", ".pi/agent/intercom/outbox/x.json",
           ".hcom/hcom.db", ".agent-deck/state.db", ".config/agent-deck/config.toml",
           "Library/LaunchAgents/com.gascity.supervisor.x.plist"]


def writing_launch(home: Path, rel: str):
    def launch(self, m, agent, mode="auto", adapter=None, label=None):
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        (home / rel).write_text("x")
        raise RuntimeError("receiver failed")
    return launch


@pytest.mark.parametrize("rel", WATCHED)
def test_a_run_that_writes_bridge_state_in_the_user_home_stops(guarded, monkeypatch, rel):
    home, _layout = guarded
    monkeypatch.setattr(Engine, "launch", writing_launch(home, rel))
    assert cli.main(["run", "--agent", "claude", "--adapter", "gc-nudge"]) == 5


def test_growing_supervisor_logs_are_measured_and_attributed_not_stopped(guarded, monkeypatch, capsys):
    home, layout = guarded

    def launch(self, m, agent, mode="auto", adapter=None, label=None):
        with open(home / ".gc" / "events.jsonl", "a") as f:
            f.write("{}\n")
        raise RuntimeError("receiver failed")
    monkeypatch.setattr(Engine, "launch", launch)
    assert cli.main(["run", "--agent", "claude", "--adapter", "gc-nudge"]) == 6
    assert "~/.gc/events.jsonl +3 B; attributed to unattributed" in capsys.readouterr().err
    [run] = [p for p in layout.runs.iterdir() if p.is_dir()]
    assert "events.jsonl +3 B" in (run / "bridge-guard.txt").read_text()


def test_launch_send_and_cleanup_are_guarded(guarded, monkeypatch):
    home, layout = guarded
    monkeypatch.setattr(Engine, "launch", writing_launch(home, ".gc/settings.json"))
    assert cli.main(["launch", "--agent", "claude", "--adapter", "gc-nudge"]) == 5
    (home / ".gc" / "settings.json").unlink()

    def cleanup(layout, run_id, kill_server=True):
        (home / ".hcom").mkdir(exist_ok=True)
        return []
    target = Target(RUN, "claude", "tmux", "none", layout.work_dir(RUN, "claude"), layout.home_dir(RUN, "claude"),
                    None, "agentcomms:x", None, None, 7)
    manifest.save(layout, Manifest(RUN, [], [target], [], []))
    monkeypatch.setattr(manifest, "cleanup", cleanup)
    assert cli.main(["cleanup", RUN]) == 5
    monkeypatch.setattr(manifest, "assert_owned", lambda *a: None)

    class Sender:
        agents = frozenset({"claude"})

        def send(self, target, text):
            (home / ".gc" / "nudges").mkdir()
            from agentcomms.adapters.native import now, receipt
            return receipt(now(), True, "ok")
    monkeypatch.setattr(cli, "make_adapter", lambda name, hosts: Sender())
    assert cli.main(["send", "--run", RUN, "--adapter", "gc-nudge", "--text", "hi"]) == 5


def test_launch_guard_also_runs_when_launch_succeeds(guarded, monkeypatch, capsys):
    home, layout = guarded
    rel = "Library/LaunchAgents/com.gascity.supervisor.plist"

    def launch(self, m, agent, mode="auto", adapter=None, label=None):
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        (home / rel).write_text("x")
        target = Target(m.run_id, "claude", "tmux", "none", layout.work_dir(m.run_id, "claude"),
                        layout.home_dir(m.run_id, "claude"), None, "agentcomms:x", None, None, 7)
        return m, Launched(target, Binary("claude", Path("/bin/claude"), "1"), {}, Path("p"), "pane-regex", [])
    monkeypatch.setattr(Engine, "launch", launch)
    assert cli.main(["launch", "--agent", "claude", "--adapter", "gc-nudge"]) == 5
    assert f"~/{rel}" in capsys.readouterr().err


def entries_a(*extra):
    return [(10.0, "tool_use", "send.sh < /r/s9/to-b.txt"), *extra]


B_SEEN = (11.0, "user", f"framed: {REQUEST}")
B_SENDS = (12.0, "tool_use", f"send-a < /r/s9/reply-{TOKEN}.txt")
A_GETS = (13.0, "peer", f"<frame from b> ACK {TOKEN}")


def test_s9_round_trip_needs_b_to_reply_after_receiving_through_a_pushed_entry():
    v = classify(entries_a(A_GETS), [B_SEEN, B_SENDS], TOKEN, FWD, BACK)
    assert (v.roundtrip, v.blocker, v.b_replied, v.a_reply) == (True, None, True, A_GETS)


def test_s9_no_credit_when_a_sends_the_reply_itself():
    a = entries_a((10.5, "tool_use", f"send-a < /r/s9/reply-{TOKEN}.txt"), A_GETS)
    v = classify(a, [B_SEEN], TOKEN, FWD, BACK)
    assert (v.roundtrip, v.blocker) == (False, "b-did-not-reply")
    both = classify(a, [B_SEEN, B_SENDS], TOKEN, FWD, BACK)
    assert (both.roundtrip, both.blocker) == (False, "a-sent-reply")


def test_s9_no_credit_when_a_polls_for_the_reply():
    v = classify(entries_a((13.0, "tool_result", f"[event] b: ACK {TOKEN}")), [B_SEEN, B_SENDS], TOKEN, FWD, BACK)
    assert (v.roundtrip, v.blocker) == (False, "reply-polled")


def test_s9_no_credit_for_a_reply_recorded_before_b_received_the_message():
    v = classify(entries_a((10.8, "peer", f"ACK {TOKEN}")), [B_SEEN, B_SENDS], TOKEN, FWD, BACK)
    assert (v.roundtrip, v.blocker) == (False, "reply-before-receipt")


def test_s9_no_credit_without_a_reply_from_b():
    v = classify(entries_a(A_GETS), [B_SEEN], TOKEN, FWD, BACK)
    assert (v.roundtrip, v.blocker, v.b_replied) == (False, "b-did-not-reply", False)


def test_s9_a_tool_route_quoting_the_request_is_the_forward_send_not_a_reply():
    a = [(10.0, "tool_use", json.dumps({"to": "b", "message": REQUEST})), A_GETS]
    b = [B_SEEN, (12.0, "tool_use", json.dumps({"message": f"ACK {TOKEN}", "summary": f"ack ACK-REQUEST {TOKEN}"}))]
    v = classify(a, b, TOKEN, ("to-b.txt", TOKEN), BACK)
    assert (v.roundtrip, v.blocker) == (True, None)


def test_attribution_matches_whole_identities_only():
    assert attribution("Message id: 7781234-aa\nbody", "body", ("81234",)) == "none"
    assert attribution("From pid 81234 (x)\nbody", "body", ("81234",)) == "mechanism"
    assert attribution("body for zola-2", "body for zola-2", ("zola",)) == "none"


def test_startup_turn_is_waited_out_and_timed_before_the_cell(monkeypatch):
    engine = Engine.__new__(Engine)

    class T:
        def entries(self):
            return [(1.0, "user", "[city] recv • now\n\nRun `gc prime` to initialize your context.")]
    monkeypatch.setattr(Engine, "transcript_for", lambda self, t: T())
    waited = []
    monkeypatch.setattr(Engine, "wait_idle", lambda self, t, timeout, settle_s=2.0: waited.append(timeout) or True)
    note = engine.await_startup_turn(None, gc_nudge.GcNudge.startup_marker)
    assert note.startswith("startup-turn=") and note.endswith("s")
    assert waited == [150.0]


def test_cleanup_kills_only_the_runs_own_per_city_tmux_servers(tmp_path, monkeypatch):
    sockets = tmp_path / "ac"
    sockets.mkdir()
    for name in (f"agentcomms-{RUN}-claude", f"agentcomms-{RUN}-codex", "agentcomms-20261027-000000-ffff-claude",
                 "agentcomms", "cadet-city", f"{RUN}-ic"):
        (sockets / name).write_text("")
    assert manifest.run_tmux_sockets(RUN, sockets) == [f"agentcomms-{RUN}-claude", f"agentcomms-{RUN}-codex"]
    assert socket_args(f"agentcomms-{RUN}-claude") == ["-S", str(SOCKET_DIR / f"agentcomms-{RUN}-claude")]
    assert socket_args("agentcomms") == ["-L", "agentcomms"]


def test_bridge_daemons_are_stopped_before_sessions_only_with_their_identity():
    m = Manifest(RUN, [], [], [], ["bridge-daemon:10", "codex-daemon:11", "bridge-daemon:12"],
                 {10: "a", 11: "b", 12: "c"})
    assert manifest.bridge_daemons(m, {10: "a", 11: "b", 12: "other"}) == {10}


def test_harness_tmux_refs_accept_only_harness_sockets():
    from agentcomms.hosts.tmux import TmuxError, split_ref
    assert split_ref(f"agentcomms-{RUN}-claude:recv") == (f"agentcomms-{RUN}-claude", "recv")
    for bad in ("cadet-city:mayor", "default:x", "agentcomms-../x:y"):
        with pytest.raises(TmuxError):
            split_ref(bad)


def test_user_home_comes_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cli.user_home() == str(tmp_path) and os.environ["HOME"] == str(tmp_path)


def test_cleanup_of_a_finished_codex_cell_leaves_no_shell_snapshot(tmp_path, monkeypatch):
    layout = Layout(tmp_path)
    home = layout.home_dir(RUN, "codex")
    (home / "shell_snapshots").mkdir(parents=True)
    (home / "shell_snapshots" / "s.sh").write_text("export X=1\n")
    target = Target(RUN, "codex", "tmux", "none", layout.work_dir(RUN, "codex"), home, None, f"agentcomms:{RUN}-codex",
                    None, None, None)
    manifest.save(layout, Manifest(RUN, [], [target], [], []))
    monkeypatch.setattr(manifest, "_tmux",
                        lambda layout, *args, socket="agentcomms": subprocess.CompletedProcess(args, 1, "", ""))
    monkeypatch.setattr(manifest, "run_tmux_sockets", lambda run_id: [])
    monkeypatch.setattr(manifest, "run_pids", lambda layout, m, rows: set())
    monkeypatch.setattr(manifest, "SOCKET_DIR", tmp_path / "ac")
    monkeypatch.setattr(manifest, "CLAUDE_SOCK_DIR", tmp_path / "cc-socks")
    report = manifest.cleanup(layout, RUN, kill_server=False)
    assert "removed 1 Codex shell snapshots (exported env)" in report
    assert list((home / "shell_snapshots").iterdir()) == []
