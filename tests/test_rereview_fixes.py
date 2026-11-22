import asyncio
import os
import signal
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcomms import backends, manifest, procs
from agentcomms.model import Manifest, Target
from agentcomms.paths import Layout
from agentcomms.procs import ProcRow

RUN_ID = "20261029-000000-abcd"


@pytest.fixture
def kills(monkeypatch):
    sent = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: sent.append((pid, sig)))
    monkeypatch.setattr(os, "killpg", lambda pid, sig: sent.append((-pid, sig)))
    monkeypatch.setattr(procs, "alive", lambda pid: True)
    return sent


def identities_seq(monkeypatch, *seq):
    calls = iter(seq)
    monkeypatch.setattr(procs, "identities", lambda pids: next(calls))


def test_opencode_db_with_sessions_but_no_message_table_is_schema_drift(tmp_path):
    from agentcomms.transcripts import opencode

    path = tmp_path / "opencode.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE session_v2 (id TEXT, directory TEXT, parent_id TEXT, time_created INTEGER)")
    conn.execute("CREATE TABLE session_inbox (id TEXT, session_id TEXT, payload TEXT, time_created INTEGER)")
    conn.execute("INSERT INTO session_v2 VALUES ('ses_1', ?, NULL, 1)", (str(tmp_path.resolve()),))
    conn.commit()
    conn.close()
    assert opencode.find_sessions(path, tmp_path) == ["ses_1"]
    with pytest.raises(opencode.SchemaDriftError, match="no such table: session_message"):
        opencode.read_session(path, "ses_1")


def test_opencode_db_before_init_still_reads_as_no_sessions(tmp_path):
    from agentcomms.transcripts import opencode

    path = tmp_path / "opencode.db"
    sqlite3.connect(path).close()
    assert opencode.find_sessions(path, tmp_path) == []


def test_backend_terminate_spares_a_pid_reused_during_the_grace_period(monkeypatch, kills):
    monkeypatch.setattr(backends, "wait_exited", lambda pid, group, timeout_s: False)
    identities_seq(monkeypatch, {4242: "a"}, {4242: "someone-else"})
    backends.terminate(4242, False, 0.0)
    assert kills == [(4242, signal.SIGTERM)]


def test_backend_terminate_sigkills_the_same_survivor(monkeypatch, kills):
    monkeypatch.setattr(backends, "wait_exited", lambda pid, group, timeout_s: False)
    identities_seq(monkeypatch, {4242: "a"}, {4242: "a"})
    backends.terminate(4242, False, 0.0)
    assert kills == [(4242, signal.SIGTERM), (4242, signal.SIGKILL)]


def test_backend_terminate_sigkills_a_group_whose_leader_already_exited(monkeypatch, kills):
    monkeypatch.setattr(backends, "wait_exited", lambda pid, group, timeout_s: False)
    identities_seq(monkeypatch, {4242: "a"}, {})
    backends.terminate(4242, True, 0.0)
    assert kills == [(-4242, signal.SIGTERM), (-4242, signal.SIGKILL)]


def test_claude_bg_stop_spares_a_pid_reused_during_the_grace_period(monkeypatch, kills):
    from agentcomms.hosts import claude_bg

    identities_seq(monkeypatch, {4242: "a"}, {4242: "someone-else"})
    claude_bg.stop_pids([4242], grace_s=0.0)
    assert kills == [(4242, signal.SIGTERM)]


def test_s6_kill_spares_a_pid_reused_during_the_grace_period(monkeypatch, kills):
    from agentcomms.scenarios import s6

    monkeypatch.setattr(s6, "KILL_GRACE_S", 0.0, raising=False)
    monkeypatch.setattr(s6, "poll", lambda check, timeout, interval: check())
    identities_seq(monkeypatch, {4242: "a"}, {4242: "someone-else"})
    cell = SimpleNamespace(engine=SimpleNamespace(check_owned=lambda target: None))
    assert s6.kill(cell, SimpleNamespace(agent_pid=4242)) == "SIGTERM"
    assert kills == [(4242, signal.SIGTERM)]


def test_vendored_provenance_needs_vendored_code_as_the_program(tmp_path):
    vendor = tmp_path / "vendor"
    v = f"{vendor.resolve()}/"
    rows = [ProcRow(40, 1, 40, f"/usr/bin/node {v}agent-intercom-pi/node_modules/tsx/cli.mjs {v}broker/broker.ts"),
            ProcRow(41, 1, 41, f"{v}bin/gc supervisor run"),
            ProcRow(42, 1, 42, f"/usr/bin/vim {v}agent-intercom-pi/index.ts"),
            ProcRow(43, 1, 43, f"/opt/homebrew/bin/rg broker {v}")]
    assert procs.runs_vendored(rows, vendor) == {40, 41}


def test_a_harness_child_from_another_run_is_not_adopted(tmp_path, monkeypatch, capsys):
    from agentcomms.engine import Engine

    layout = Layout(tmp_path)
    engine = Engine(layout, environ={"HOME": str(tmp_path)})
    m = Manifest(RUN_ID, [], [], [], [])
    manifest.save(layout, m)
    harness = os.getpid()
    monkeypatch.setattr(procs, "ps_rows", lambda: [ProcRow(harness, 1, harness, "python -m agentcomms.cli matrix"),
                                                   ProcRow(50, harness, 50, "/usr/bin/other-runs-backend")])
    monkeypatch.setattr(procs, "cwds", lambda pids: {50: "/Users/u"})
    monkeypatch.setattr(procs, "identities", lambda pids: {p: f"id-{p}" for p in pids})
    m = engine.track(m, "bridge-daemon", [50])
    assert m.backends == []
    assert "not tracking bridge-daemon pid 50" in capsys.readouterr().err
    m = engine.track(m, "recorder", [50], spawned=frozenset({50}))
    assert m.backends == ["recorder:50"]


def test_zmx_stop_raises_when_the_session_survives_the_kill(tmp_path, monkeypatch):
    from agentcomms.hosts import zmx

    host = zmx.ZmxHost(Path("/v/zmx"))
    monkeypatch.setattr(host, "run", lambda state, argv, check=True: "")
    monkeypatch.setattr(host, "sessions", lambda state: {"recv": {"pid": "1"}})
    with pytest.raises(zmx.ZmxError, match="still listed after kill"):
        host.stop(zmx.make_ref(tmp_path, "recv"))


def test_zmx_stop_reports_a_timed_out_kill_as_a_host_error(tmp_path, monkeypatch):
    from agentcomms.hosts import zmx

    def run(state, argv, check=True):
        raise subprocess.TimeoutExpired(argv, 30)
    host = zmx.ZmxHost(Path("/v/zmx"))
    monkeypatch.setattr(host, "run", run)
    with pytest.raises(zmx.ZmxError, match="TimeoutExpired"):
        host.stop(zmx.make_ref(tmp_path, "recv"))


def test_zmx_start_keeps_its_own_error_when_the_cleanup_stop_times_out(tmp_path, monkeypatch):
    from agentcomms.hosts import zmx

    monkeypatch.setattr(zmx, "SESSION_UP_S", 0.0)
    monkeypatch.setattr(zmx, "spawn_in_pty", lambda *a, **k: SimpleNamespace(close=lambda: None))
    host = zmx.ZmxHost(Path("/v/zmx"))

    def run(state, argv, check=True):
        if argv[1] == "kill":
            raise subprocess.TimeoutExpired(argv, 30)
        return ""
    monkeypatch.setattr(host, "run", run)
    monkeypatch.setattr(host, "sessions", lambda state: {})
    with pytest.raises(zmx.ZmxError, match="did not appear"):
        host.start("recv", ["/bin/true"], {}, tmp_path, state_dir=tmp_path / "state")


def zmx_target(layout: Layout, state: Path) -> Target:
    work = layout.work_dir(RUN_ID, "codex")
    return Target(RUN_ID, "codex", "zmx", "none", work, layout.home_dir(RUN_ID, "codex"), None,
                  f"zmx:{state}:recv", None, None, None)


def test_a_failed_multiplexer_stop_is_reported_and_keeps_its_state_dir(tmp_path, monkeypatch):
    from agentcomms import hosts

    class FailingHost:
        def __init__(self, kind):
            pass

        def stop(self, ref):
            raise RuntimeError("zmx session recv still listed after kill")
    monkeypatch.setattr(hosts, "make_host", FailingHost)
    sockets = tmp_path / "ac"
    state = sockets / f"{RUN_ID}-zmx"
    state.mkdir(parents=True)
    layout = Layout(tmp_path / "repo")
    report, survived = manifest.stop_multiplexer_sessions(Manifest(RUN_ID, [], [zmx_target(layout, state)], [], []))
    assert report == ["note: stopping zmx session recv failed: RuntimeError: zmx session recv still listed after kill"]
    assert survived == {state}
    assert manifest.remove_run_socket_dirs(RUN_ID, sockets, keep=frozenset(survived)) == [
        f"left socket dir {state} (its multiplexer session did not stop)"]
    assert state.is_dir()


def test_an_iterm_tab_created_after_a_cancel_is_closed(monkeypatch, tmp_path):
    import iterm2 as pkg

    from agentcomms.hosts import iterm2

    session = SimpleNamespace(session_id="cell1", closed=False)

    async def close(force=False):
        session.closed = True
    session.async_close = close
    created = asyncio.Event()

    class Holder:
        async def async_create_tab(self, profile_customizations=None, select=True):
            created.set()
            await asyncio.sleep(0.05)
            return SimpleNamespace(current_session=session)

    async def get_app(connection):
        return object()

    async def ensure_holder(connection, app, notes):
        return Holder()

    async def current_focus(app):
        return None
    monkeypatch.setattr(pkg, "async_get_app", get_app)
    monkeypatch.setattr(iterm2, "ensure_holder", ensure_holder)
    monkeypatch.setattr(iterm2, "current_focus", current_focus)

    class CancellingLoop:
        tasks: dict = {}

        def call(self, make, timeout=30.0):
            async def main():
                task = asyncio.ensure_future(make(object()))
                await created.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                await asyncio.sleep(0.1)
            asyncio.run(main())
            raise TimeoutError
    host = iterm2.ItermHost(loop=CancellingLoop())
    with pytest.raises(TimeoutError):
        host.start("cell", ["/bin/true"], {}, tmp_path)
    assert session.closed is True


def test_user_config_inventory_shows_an_unclassified_integration():
    from agentcomms import cli, userconfig

    line = cli.inventory_line(userconfig.classify("codex", "hook", "post-to-slack"))
    assert line == f"- hook post-to-slack -> {userconfig.UNCLASSIFIED}"


def test_zellij_stop_raises_when_the_session_survives_the_kill(tmp_path, monkeypatch):
    from agentcomms.hosts import zellij

    host = zellij.ZellijHost(Path("/v/zellij"))
    monkeypatch.setattr(host, "run", lambda state, argv, check=True: "")
    monkeypatch.setattr(host, "pane_listed", lambda ref: True)
    with pytest.raises(zellij.ZellijError, match="still has a pane"):
        host.stop(zellij.make_ref(tmp_path, "recv"))
