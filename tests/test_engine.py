import subprocess
from pathlib import Path

import pytest

from agentcomms.engine import (
    api_errors,
    classify_ack,
    classify_delivery,
    envelope,
    match_dialog,
    pane_ready,
    receiver_hits,
)
from agentcomms.model import Ack, Delivery
from agentcomms.procs import ProcRow, descendants, find_agent_pid, parse_ps

CLAUDE_READY = """\
 ▐▛███▛█   Claude Code v2.1.310
❯ Try "refactor <filepath>"
────────────────────────────
  ⏵⏵ bypass permissions on (shift+tab to cycle) · ← for agents
"""

CODEX_READY = """\
  >_ OpenAI Codex (v0.164.0)
› Ask Codex to do anything
  GPT-6-Luna low · ~/wrksp/_scratch/agent-comms/runs/r1/work/codex
  ? for shortcuts
"""

CODEX_TRUST = """\
  Do you trust the contents of this directory? Working with untrusted contents comes with higher risk.
› 1. Yes, continue
  2. No, quit
"""


def test_envelope_puts_ack_instruction_before_body():
    assert envelope("0a1b2c3d", "body") == 'ACK-REQUEST 0a1b2c3d: reply with exactly "ACK 0a1b2c3d". body'


def test_ready_panes_are_recognised():
    assert pane_ready("claude", CLAUDE_READY)
    assert pane_ready("codex", CODEX_READY)


def test_dialog_blocks_readiness_and_is_matched():
    assert match_dialog("codex", CODEX_TRUST).label == "trust-dir"
    assert pane_ready("codex", CODEX_TRUST) is False


def test_delivery_classification():
    hit = [(1.0, "user", "x")]
    assert classify_delivery(True, hit) is Delivery.DELIVERED
    assert classify_delivery(True, []) is Delivery.LOST
    assert classify_delivery(False, []) is Delivery.REJECTED


def test_ack_classification():
    assert classify_ack(True, ["ACK 0a1b2c3d"], "0a1b2c3d") is Ack.ACKED
    assert classify_ack(True, ["sure"], "0a1b2c3d") is Ack.MODEL_NONCOMPLIANT
    assert classify_ack(False, [], "0a1b2c3d") is Ack.NONE


def test_agent_pid_found_below_sops_exec():
    rows = parse_ps("""\
  100     1   100 /bin/zsh /Users/me/ac/bin/sops-exec /v/2.1.310 --session-id s
  101   100   100 sops exec-env secrets.yaml /v/2.1.310 --session-id s
  102   101   100 /v/2.1.310 --session-id s
  103   102   100 /bin/zsh -c sleep 1
  500     1   500 /v/2.1.310 --resume other
""")
    assert rows[0] == ProcRow(100, 1, 100, "/bin/zsh /Users/me/ac/bin/sops-exec /v/2.1.310 --session-id s")
    assert descendants(rows, {100}) == {100, 101, 102, 103}
    assert find_agent_pid(rows, 100, "/v/2.1.310") == 102


def test_queue_and_api_error_entries_are_not_receiver_hits():
    entries = [(1.0, "queue", "ACK-REQUEST tk"), (2.0, "api_error", "tk 429"), (3.0, "assistant", "ACK tk"),
               (4.0, "user", "ACK-REQUEST tk")]
    assert receiver_hits(entries, "tk") == [(4.0, "user", "ACK-REQUEST tk")]
    assert api_errors(entries) == ["tk 429"]


def test_claude_transcript_is_resolved_again_after_launch(tmp_path):
    from dataclasses import replace

    from agentcomms.engine import Engine
    from agentcomms.model import Target
    from agentcomms.paths import Layout
    home, work = tmp_path / "home", tmp_path / "work"
    odd = home / "projects" / "hashed-dir"
    odd.mkdir(parents=True)
    (odd / "sid.jsonl").write_text("")
    target = Target(run_id="r", agent="claude", host="tmux", backend="none", work_dir=work, home_dir=home,
                    session_id="sid", host_ref="agentcomms:r-claude", backend_ref=None,
                    transcript=home / "projects" / "encoded" / "sid.jsonl", agent_pid=None)
    transcript = Engine(Layout(tmp_path)).transcript_for(replace(target))
    assert transcript.path == odd / "sid.jsonl"


class StubTranscript:
    def __init__(self, idle):
        self.idle_state = idle

    def is_idle(self):
        return self.idle_state


class StubTmux:
    def __init__(self, pane: str):
        self.pane = pane

    def capture(self, host_ref: str) -> str:
        return self.pane


def test_unknown_idle_falls_back_to_pane_readiness(tmp_path):
    from pathlib import Path

    from agentcomms.engine import Engine
    from agentcomms.model import Target
    from agentcomms.paths import Layout
    pi_ready = "────────────────────────\n> \n────────────────────────\n(openrouter) deepseek • thinking off\n"
    target = Target("r", "pi", "tmux", "none", Path("/w"), Path("/h"), None, "agentcomms:r-pi", None, None, None)
    engine = Engine(Layout(tmp_path))
    engine.tmux = StubTmux(pi_ready)
    assert engine.idle(target, StubTranscript(None)) is True
    assert engine.idle(target, StubTranscript(False)) is False
    engine.tmux = StubTmux("Working...")
    assert engine.idle(target, StubTranscript(None)) is False


def test_login_screens_are_recognised_as_auth_failures():
    from agentcomms.engine import auth_screen
    assert auth_screen("claude", " Select login method:\n ❯ 1. Claude account with subscription\n") == (
        "Select login method")
    assert auth_screen("codex", "  Sign in with ChatGPT to use Codex\n") == "Sign in with ChatGPT"
    assert auth_screen("claude", CLAUDE_READY) is None


def test_auth_failure_is_a_pausing_env_error():
    from agentcomms.engine import AuthRequiredError, failure_delivery, failure_note
    error = AuthRequiredError("codex shows a login/auth screen: 'Sign in with ChatGPT'")
    assert failure_delivery(error) is Delivery.ENV_ERROR
    assert failure_note(error).startswith("auth-required: AuthRequiredError: codex shows")


def test_digit_free_tokens_are_hex_letters_only():
    from agentcomms.engine import DIGIT_FREE, new_token
    tokens = [new_token(DIGIT_FREE) for _ in range(50)]
    assert all(len(t) == 8 and set(t) <= set("abcdef") for t in tokens)
    assert all(len(t) == 8 and set(t) <= set("0123456789abcdef") for t in (new_token() for _ in range(50)))


def test_resume_refuses_a_session_the_run_does_not_own(tmp_path):
    from pathlib import Path

    import pytest

    from agentcomms import manifest
    from agentcomms.engine import Engine, Launched
    from agentcomms.model import Manifest, Target
    from agentcomms.paths import Layout
    from agentcomms.profiles import Binary

    layout = Layout(tmp_path)
    run_id = "20261024-000000-abcd"
    target = Target(run_id, "codex", "tmux", "none", layout.work_dir(run_id, "codex"),
                    layout.home_dir(run_id, "codex"), "sid-owned", f"agentcomms:{run_id}-codex", None, None, 7)
    manifest.save(layout, Manifest(run_id, [7], [target], [], []))
    launched = Launched(target, Binary("codex", Path("/c/codex"), "0.164.0"), {}, Path(), "", [])
    engine = Engine(layout, environ={"PATH": "/bin"})
    started = []
    engine.start = lambda *a: started.append(a)
    with pytest.raises(manifest.OwnershipError, match="session sid-other"):
        engine.resume(Manifest(run_id, [7], [target], [], []), launched, "sid-other")
    assert started == []
    engine.resume(Manifest(run_id, [7], [target], [], []), launched, "sid-owned")
    assert started[0][3] == "sid-owned"


def test_codex_startup_placeholder_is_not_ready(fixtures):
    startup = (fixtures / "codex" / "pane-startup.txt").read_text()
    ready = (fixtures / "codex" / "pane-ready.txt").read_text()
    assert pane_ready("codex", startup) is False
    assert pane_ready("codex", ready)
    assert pane_ready("codex", ready + "\n  Waiting for startup · esc cancel\n") is False


def test_codex_with_a_user_status_line_is_ready_once_bootstrap_draws_it(fixtures):
    startup = (fixtures / "codex" / "pane-startup.txt").read_text()
    custom = ("› Ask Codex to do anything\n\n  ? for shortcuts\n"
              "  permissions: YOLO mode · codex · GPT-6-Luna default · Fast off · Context 0% used\n")
    assert pane_ready("codex", custom)
    assert pane_ready("codex", custom + "  Waiting for startup · esc cancel\n") is False
    assert pane_ready("codex", startup) is False


def test_auth_patterns_match_real_logged_out_screens(fixtures):
    from agentcomms.engine import auth_screen
    droid = (fixtures / "auth" / "droid-logged-out.txt").read_text()
    assert auth_screen("droid", droid) == "Please login with your Factory account"
    assert auth_screen("pi", (fixtures / "auth" / "pi-no-key.txt").read_text())
    assert auth_screen("pi", (fixtures / "auth" / "pi-ready.txt").read_text()) is None
    assert auth_screen("codex", (fixtures / "codex" / "pane-ready.txt").read_text()) is None


class FramesHost:
    def __init__(self, frames: list[str]):
        self.frames = frames

    def alive(self, ref):
        return True

    def capture(self, ref):
        return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]


def ready_engine(tmp_path, monkeypatch, frames: list[str]):
    from pathlib import Path

    from agentcomms import engine as engine_mod
    from agentcomms import procs
    from agentcomms.engine import Engine
    from agentcomms.model import Target
    from agentcomms.paths import Layout
    from agentcomms.profiles import Binary
    clock = iter(range(0, 10_000))
    monkeypatch.setattr(engine_mod.time, "monotonic", lambda: float(next(clock)))
    monkeypatch.setattr(engine_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(procs, "ps_rows", lambda: [])
    monkeypatch.setattr(procs, "find_agent_pid", lambda *a: 42)
    monkeypatch.setattr(procs, "alive", lambda pid: True)
    engine = Engine(Layout(tmp_path))
    engine.host_for = lambda kind: FramesHost(frames)
    target = Target("r", "pi", "tmux", "none", Path("/w"), Path("/h"), None, "agentcomms:r-pi", None, None, None)
    return engine, target, Binary("pi", Path("/p"), "1.4.0")


def test_an_auth_screen_that_appears_just_before_the_ready_timeout_still_pauses(tmp_path, monkeypatch, fixtures):
    import pytest

    from agentcomms import engine as engine_mod
    from agentcomms.engine import AuthRequiredError
    no_key = (fixtures / "auth" / "pi-no-key.txt").read_text()
    monkeypatch.setattr(engine_mod, "READY_TIMEOUT_S", {"pi": 40.0})
    engine, target, binary = ready_engine(tmp_path, monkeypatch, ["starting"] * 19 + [no_key])
    with pytest.raises(AuthRequiredError, match="pi shows a login/auth screen"):
        engine.await_ready(target, binary, 1)


def test_a_startup_frame_without_the_provider_is_not_an_auth_screen(tmp_path, monkeypatch, fixtures):
    no_key = (fixtures / "auth" / "pi-no-key.txt").read_text()
    ready = (fixtures / "auth" / "pi-ready.txt").read_text()
    engine, target, binary = ready_engine(tmp_path, monkeypatch, [no_key, ready])
    target, how, dialogs = engine.await_ready(target, binary, 1)
    assert (target.agent_pid, how, dialogs) == (42, "pane-regex", [])


def test_an_auth_screen_that_stays_up_pauses_with_auth_required(tmp_path, monkeypatch, fixtures):
    import pytest

    from agentcomms.engine import AuthRequiredError
    no_key = (fixtures / "auth" / "pi-no-key.txt").read_text()
    engine, target, binary = ready_engine(tmp_path, monkeypatch, [no_key])
    with pytest.raises(AuthRequiredError, match="pi shows a login/auth screen"):
        engine.await_ready(target, binary, 1)


def resume_fixture(tmp_path, mods, agent="claude"):
    from pathlib import Path

    from agentcomms import manifest
    from agentcomms.engine import Engine, Launched
    from agentcomms.model import Manifest, Target
    from agentcomms.paths import Layout
    from agentcomms.profiles import Binary

    layout = Layout(tmp_path)
    run_id = "20261024-000000-abcd"
    target = Target(run_id, agent, "tmux", "none", layout.work_dir(run_id, agent), layout.home_dir(run_id, agent),
                    "sid-1", f"agentcomms:{run_id}-{agent}", None, None, 7)
    m = Manifest(run_id, [7], [target], [], [])
    manifest.save(layout, m)
    launched = Launched(target, Binary(agent, Path(f"/v/{agent}"), "1"), {}, Path(), "", [], mods=mods)
    engine = Engine(layout, environ={"PATH": "/bin"})
    started = []
    engine.start = lambda *a: started.append(a)
    engine.resume(m, launched, "sid-1")
    return layout, run_id, started[0][2]


def test_resume_keeps_the_adapters_launch_args(tmp_path):
    from agentcomms.model import LaunchMods
    mods = LaunchMods(host="tmux", extra_args=("--mcp-config", "/h/channel-mcp.json"))
    _, _, argv = resume_fixture(tmp_path, mods)
    assert argv[argv.index("--resume") + 1] == "sid-1"
    assert argv[-2:] == ["--mcp-config", "/h/channel-mcp.json"]


def test_resume_runs_a_launcher_bridge_through_its_launcher(tmp_path):
    from agentcomms.model import LaunchMods
    mods = LaunchMods(host="tmux", launcher=("/vendor/hcom", "claude"))
    _, _, argv = resume_fixture(tmp_path, mods)
    assert argv[1:5] == ["/vendor/hcom", "claude", "--resume", "sid-1"]


def test_resume_puts_the_resume_args_in_the_shim_for_an_args_in_shim_launcher(tmp_path):
    from agentcomms.model import LaunchMods
    mods = LaunchMods(host="tmux", launcher=("node", "cci.ts", "--tui"), args_in_shim=True,
                      extra_args=("--settings", "{}"))
    layout, run_id, argv = resume_fixture(tmp_path, mods)
    shim = (layout.run_dir(run_id) / "bin" / "claude" / "claude").read_text()
    assert argv[1:] == ["node", "cci.ts", "--tui"]
    assert "/v/claude --resume sid-1" in shim and "--settings '{}'" in shim


def test_wait_for_token_finds_the_reply_in_a_thread_created_after_the_first_lookup(tmp_path, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace

    from agentcomms import engine as engine_mod
    from agentcomms.engine import Engine
    from agentcomms.model import Target
    from agentcomms.paths import Layout

    def thread(name, entries):
        return SimpleNamespace(path=Path(name), entries=lambda: entries, is_idle=lambda: True,
                               find_token=lambda tok: [e for e in entries if tok in e[2]])

    bridge = thread("bridge.jsonl", [(1.0, "user", "startup")])
    user = thread("user.jsonl", [(2.0, "user", "ACK-REQUEST ab12: warm-up"), (3.0, "assistant", "ACK ab12")])
    threads = [[bridge], [bridge, user]]
    monkeypatch.setattr(engine_mod.time, "sleep", lambda s: None)
    engine = Engine(Layout(tmp_path))
    engine.all_transcripts = lambda target: threads.pop(0) if len(threads) > 1 else threads[0]
    engine.transcript_for = lambda target: bridge
    engine.host_of = lambda target: SimpleNamespace(alive=lambda ref: True)
    target = Target("r", "codex", "tmux", "none", Path("/w"), Path("/h"), None, "agentcomms:r-codex", None, None, 1)
    found, finished = engine.wait_for_token(target, "ab12", 30.0)
    assert (found.path, finished) == (Path("user.jsonl"), True)


def test_stopping_a_backend_child_that_ignores_sigterm_leaves_no_zombie():
    from agentcomms import backends, procs
    proc = subprocess.Popen(["/bin/sh", "-c", "trap '' TERM; sleep 30"], start_new_session=True)
    try:
        backends.stop_group(proc.pid, grace_s=0.5, kill_wait_s=3.0)
        assert procs.alive(proc.pid) is False
    finally:
        proc.kill()


class ReadoptSetup:
    run_id = "20261028-000000-abcd"
    agent_bin = "/pinned/codex-0.165.0/bin/codex"

    def __init__(self, tmp_path, monkeypatch, rows, old_pid=50, old_identity="old-id", new_identity="new-id",
                 live_checks=False):
        from agentcomms import engine as engine_mod
        from agentcomms import manifest, procs
        from agentcomms.engine import Engine
        from agentcomms.model import Manifest, Target
        from agentcomms.paths import Layout
        from agentcomms.profiles import Binary

        self.layout = Layout(tmp_path)
        self.target = Target(self.run_id, "codex", "tmux", "none", self.layout.work_dir(self.run_id, "codex"),
                             self.layout.home_dir(self.run_id, "codex"), None, f"agentcomms:{self.run_id}-codex",
                             None, None, old_pid)
        self.m = Manifest(self.run_id, [111], [self.target], [], [], identities={old_pid: old_identity})
        manifest.save(self.layout, self.m)
        self.binary = Binary("codex", Path(self.agent_bin), "0.165.0")
        self.engine = Engine(self.layout, environ={"PATH": "/bin"})
        self.engine.tmux = FakePane()
        monkeypatch.setattr(procs, "ps_rows", lambda: rows)
        if not live_checks:
            monkeypatch.setattr(procs, "running", lambda pid, identity: False)
            monkeypatch.setattr(procs, "identities", lambda pids: {p: new_identity for p in pids})
        monkeypatch.setitem(engine_mod.READY_TIMEOUT_S, "codex", 0.3)
        monkeypatch.setattr(engine_mod.time, "sleep", lambda s: None)

    def readopt(self):
        return self.engine.readopt_agent(self.m, self.target, self.binary)


class FakePane:
    kind = "tmux"

    def pane_pid(self, host_ref):
        return 200

    def alive(self, host_ref):
        return True

    def capture(self, host_ref):
        return CODEX_READY


RESPAWNED_ROWS = [ProcRow(200, 1, 200, "sh"), ProcRow(201, 200, 200, f"{ReadoptSetup.agent_bin} --no-daemon")]


def test_readopt_records_the_respawned_agent_in_the_manifest(tmp_path, monkeypatch):
    from agentcomms import manifest

    setup = ReadoptSetup(tmp_path, monkeypatch, RESPAWNED_ROWS)
    m, target, respawned = setup.readopt()
    saved = manifest.load(setup.layout, setup.run_id)
    assert (respawned, target.agent_pid) == (True, 201)
    assert saved.pgids == [111, 200]
    assert saved.identities[201] == "new-id"
    assert [t.agent_pid for t in saved.targets] == [201]
    assert m == saved


def test_readopt_refuses_a_target_the_manifest_does_not_own(tmp_path, monkeypatch):
    from dataclasses import replace

    from agentcomms import manifest

    setup = ReadoptSetup(tmp_path, monkeypatch, RESPAWNED_ROWS)
    setup.target = replace(setup.target, work_dir=tmp_path / "elsewhere")
    with pytest.raises(manifest.OwnershipError):
        setup.readopt()
    assert manifest.load(setup.layout, setup.run_id).pgids == [111]


def test_readopt_never_adopts_an_agent_outside_the_pane(tmp_path, monkeypatch):
    from agentcomms.engine import AgentLostError

    rows = [ProcRow(200, 1, 200, "sh"), ProcRow(300, 1, 300, f"{ReadoptSetup.agent_bin} --no-daemon")]
    setup = ReadoptSetup(tmp_path, monkeypatch, rows)
    with pytest.raises(AgentLostError, match="no agent process is in the pane"):
        setup.readopt()


def test_readopt_of_a_dead_agent_that_nothing_respawned_is_a_lost_agent(tmp_path, monkeypatch):
    from agentcomms.engine import AgentLostError

    setup = ReadoptSetup(tmp_path, monkeypatch, [ProcRow(200, 1, 200, "sh")])
    setup.engine.tmux.alive = lambda host_ref: False
    with pytest.raises(AgentLostError, match="gone and nothing respawned it"):
        setup.readopt()


def test_readopt_skips_a_running_agent_whose_identity_matches(tmp_path, monkeypatch):
    import os
    from dataclasses import replace

    from agentcomms import procs

    pid = os.getpid()
    ident = procs.identities({pid})[pid]
    setup = ReadoptSetup(tmp_path, monkeypatch, RESPAWNED_ROWS, old_pid=pid, old_identity=ident, live_checks=True)
    assert setup.readopt() == (setup.m, setup.target, False)
    setup.m = replace(setup.m, identities={pid: "another-start-time"})
    _, target, respawned = setup.readopt()
    assert (target.agent_pid, respawned) == (201, True)


def test_a_recycled_pid_does_not_count_as_the_running_agent():
    import os

    from agentcomms import procs

    pid = os.getpid()
    assert procs.running(pid, procs.identities({pid})[pid]) is True
    assert procs.running(pid, "another-process-started-at-another-time") is False
    assert procs.running(pid, None) is False


def test_a_zombie_does_not_count_as_the_running_agent():
    import subprocess
    import time

    from agentcomms import procs

    child = subprocess.Popen(["/usr/bin/true"])
    try:
        deadline = time.monotonic() + 5
        while procs.state(child.pid) != "Z" and time.monotonic() < deadline:
            time.sleep(0.05)
        assert procs.state(child.pid).startswith("Z")
        assert procs.running(child.pid, procs.identities({child.pid})[child.pid]) is False
    finally:
        child.wait()


def test_a_group_that_exits_on_sigterm_is_not_sent_sigkill(monkeypatch):
    import os
    import signal
    import subprocess

    from agentcomms import backends

    signals = []
    real = os.killpg
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: signals.append(sig) or real(pgid, sig))
    proc = subprocess.Popen(["/bin/sh", "-c", "sleep 30"], start_new_session=True)
    backends.stop_group(proc.pid, grace_s=3.0)
    assert signals == [signal.SIGTERM]


def test_a_group_that_ignores_sigterm_is_sent_sigkill_before_it_is_reaped(monkeypatch):
    import os
    import signal
    import subprocess

    from agentcomms import backends

    signals = []
    real = os.killpg
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: signals.append(sig) or real(pgid, sig))
    proc = subprocess.Popen(["/bin/sh", "-c", "trap '' TERM; echo ready; sleep 30"], start_new_session=True,
                            stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline() == "ready\n"
    backends.stop_group(proc.pid, grace_s=0.5, kill_wait_s=3.0)
    assert signals == [signal.SIGTERM, signal.SIGKILL]
    proc.stdout.close()


def test_check_versions_compares_the_codex_daemon_version_as_well_as_the_binary(tmp_path, monkeypatch):
    from agentcomms import profiles
    from agentcomms.engine import Engine, Launched
    from agentcomms.paths import Layout

    binary = profiles.Binary("codex", Path("/pinned/codex"), "0.165.0")
    launched = Launched(None, binary, {"codex": "0.165.0", "codex_daemon": "0.165.0"}, Path(), "", [],
                        env={"CODEX_HOME": "/run/home"})
    engine = Engine(Layout(tmp_path), environ={"PATH": "/bin"})
    monkeypatch.setattr(engine, "resolve", lambda agent: binary)
    seen = []

    def daemon_version(b, env=None):
        seen.append(env)
        return reported[0]

    monkeypatch.setattr(profiles, "codex_daemon_version", daemon_version)
    reported = ["0.165.0"]
    assert engine.check_versions(launched) is True
    reported[0] = "0.166.0"
    assert engine.check_versions(launched) is False
    assert seen == [{"CODEX_HOME": "/run/home"}] * 2
