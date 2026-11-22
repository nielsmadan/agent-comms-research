import hashlib
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest

from agentcomms import backends, manifest
from agentcomms.model import Manifest, Target
from agentcomms.paths import Layout

RUN_ID = "20261029-000000-abcd"


def codex_target(layout: Layout, home: Path, backend: str, agent: str = "codex") -> Target:
    work = layout.work_dir(RUN_ID, agent)
    return Target(run_id=RUN_ID, agent=agent, host="tmux", backend=backend, work_dir=work, home_dir=home,
                  session_id=None, host_ref=f"agentcomms:{RUN_ID}-{agent}", backend_ref=f"/tmp/ac/{RUN_ID}.sock",
                  transcript=None, agent_pid=None)


@pytest.fixture
def fake_user_home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "user"
    (home / ".codex").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.mark.parametrize("backend", ["codex-app-server", "codex-daemon", "none"])
def test_user_config_codex_home_never_yields_a_removable_daemon_socket(tmp_path, fake_user_home, backend):
    layout = Layout(tmp_path / "repo")
    user_codex = Path.home() / ".codex"
    m = Manifest(RUN_ID, [], [codex_target(layout, user_codex, backend)], [], [f"{backend}:4242"])
    derived = frozenset(manifest.derived_codex_sockets(layout, m))
    users = backends.codex_daemon_socket(fake_user_home / ".codex")
    assert users.name not in derived
    assert manifest.socket_removable(users, layout, derived) is False


def test_daemon_socket_is_derived_only_for_a_harness_daemon_in_the_run(tmp_path):
    layout = Layout(tmp_path / "repo")
    run_home = layout.home_dir(RUN_ID, "codex")
    daemon = Manifest(RUN_ID, [], [codex_target(layout, run_home, "codex-daemon")], [], [])
    embedded = Manifest(RUN_ID, [], [codex_target(layout, run_home, "none")], [], [])
    assert manifest.derived_codex_sockets(layout, daemon) == {backends.codex_daemon_socket(run_home).name}
    assert manifest.derived_codex_sockets(layout, embedded) == set()


def test_cleanup_after_a_user_config_codex_cell_leaves_the_users_daemon_socket(tmp_path, fake_user_home,
                                                                               monkeypatch):
    layout = Layout(tmp_path / "repo")
    daemon_dir = tmp_path / "codex-daemon-501"
    daemon_dir.mkdir()
    monkeypatch.setattr(backends, "CODEX_DAEMON_SOCK_DIR", daemon_dir)
    monkeypatch.setattr(manifest, "_tmux",
                        lambda layout, *args, socket="agentcomms": subprocess.CompletedProcess(args, 1, "", ""))
    monkeypatch.setattr(manifest, "SOCKET_DIR", tmp_path / "ac")
    monkeypatch.setattr(manifest, "CLAUDE_SOCK_DIR", tmp_path / "cc-socks")
    users = backends.codex_daemon_socket(fake_user_home / ".codex")
    users.write_text("")
    listen = tmp_path / "ac" / f"{RUN_ID}.sock"
    link = daemon_dir / hashlib.sha256(str(listen).encode()).hexdigest()
    link.write_text("")
    m = Manifest(RUN_ID, [], [codex_target(layout, fake_user_home / ".codex", "codex-app-server")], [listen],
                 ["codex-app-server:4242"])
    manifest.save(layout, m)
    report = manifest.cleanup(layout, RUN_ID, grace_s=0.1, kill_server=False)
    assert users.exists()
    assert f"removed socket {link}" in report
    assert all(users.name not in line for line in report)


def test_registered_service_is_read_only_from_a_home_inside_the_run(tmp_path, monkeypatch):
    layout = Layout(tmp_path / "repo")
    run_home = layout.home_dir(RUN_ID, "opencode")
    outside = tmp_path / "user" / ".local" / "share" / "opencode-home"
    read = []
    monkeypatch.setattr(backends, "service_pid_in_run", lambda registration, run_dir: read.append(registration))
    m = Manifest(RUN_ID, [], [codex_target(layout, outside, "opencode-server", "opencode"),
                              codex_target(layout, run_home, "opencode-server", "opencode")], [], [])
    manifest.stop_registered_services(layout, m)
    assert read == [run_home / "state" / "opencode" / "service.json"]


def fake_cell(tmp_path: Path, gone: str | None, scenario: str = "S12", agent: str = "codex"):
    from types import SimpleNamespace

    from agentcomms.engine import Launched
    from agentcomms.profiles import Binary
    from agentcomms.scenarios.common import Cell

    host = SimpleNamespace(take_notes=lambda: [])
    engine = SimpleNamespace(layout=Layout(tmp_path), user_home="/Users/me", sandbox="raw", host_of=lambda t: host,
                             receiver_gone=lambda target: gone, snapshot=lambda target, label: "",
                             check_owned=lambda target, live=True: None)
    target = Target("r1", agent, "tmux", "codex-app-server", tmp_path / "w", tmp_path / "h", "s",
                    f"agentcomms:r1-{agent}", None, None, 42)
    launched = Launched(target, Binary(agent, Path("/b"), "1"), {agent: "1"}, tmp_path / "pane.log", "pane-regex", [])
    adapter = SimpleNamespace(name="codex-remote-start", unwrap=lambda t: t)
    return Cell(engine, SimpleNamespace(run_id="r1"), launched, adapter, scenario, "extensive", 1)


def test_s12_agent_lost_by_restart_is_recorded_as_lost_not_a_receiver_crash(tmp_path, monkeypatch):
    from agentcomms import checkpoint
    from agentcomms.engine import AgentLostError
    from agentcomms.model import Delivery
    from agentcomms.scenarios import s12
    from agentcomms.scenarios.common import finish

    monkeypatch.setattr(checkpoint, "network_ok", lambda: True)
    monkeypatch.setattr(s12, "warm_up", lambda cell, target, timeout: True)
    monkeypatch.setattr(s12.time, "sleep", lambda s: None)
    cell = fake_cell(tmp_path, gone="pid 42 gone")
    cell.adapter.restart_backend = lambda target: "codex-app-server graceful stop+start"
    cell.engine.track_restarted_backend = lambda m, target: m
    cell.engine.track_bridge_daemons = lambda m, adapter, target: m

    def lost(m, target, binary, marker):
        raise AgentLostError("codex pid 42 gone and nothing respawned it")
    cell.engine.readopt_agent = lost
    record = finish(cell, s12.run(cell), time.time(), time.monotonic())
    assert record.delivery is Delivery.LOST
    assert "agent-lost-by-restart: codex pid 42 gone and nothing respawned it" in record.notes


def test_a_receiver_that_dies_outside_s12s_declared_loss_still_pauses(tmp_path, monkeypatch):
    from agentcomms import checkpoint
    from agentcomms.model import Delivery
    from agentcomms.scenarios.common import Outcome, finish

    monkeypatch.setattr(checkpoint, "network_ok", lambda: True)
    record = finish(fake_cell(tmp_path, gone="pid 42 gone"), Outcome(Delivery.DELIVERED, tokens=["tk"]), 0.0, 0.0)
    assert record.delivery is Delivery.ENV_ERROR
    assert "receiver-crashed (pid 42 gone; was delivered)" in record.notes


def test_only_the_runs_app_server_listen_socket_yields_a_link_target(tmp_path):
    layout = Layout(tmp_path / "repo")
    listen, channel = Path(f"/tmp/ac/{RUN_ID}.sock"), Path(f"/tmp/ac/{RUN_ID}-ch.sock")
    m = Manifest(RUN_ID, [], [], [listen, channel], [])
    assert manifest.derived_codex_sockets(layout, m) == {hashlib.sha256(str(listen).encode()).hexdigest()}


@pytest.fixture
def scale_layout(tmp_path, monkeypatch):
    import threading

    from agentcomms import cli, isolation

    layout = Layout(tmp_path)
    cleaned = []
    monkeypatch.setattr(cli, "default_layout", lambda: layout)
    monkeypatch.setattr(manifest, "cleanup", lambda layout, run_id, kill_server=True: cleaned.append(run_id) or [])
    monkeypatch.setattr(manifest, "stop_idle_server", lambda layout: False)
    monkeypatch.setattr(manifest, "remaining_pids", lambda layout, run_id: set())
    monkeypatch.setattr(isolation, "global_config_hashes", lambda: {})
    monkeypatch.setattr(isolation, "user_state_mtimes", lambda agent: {})
    monkeypatch.setattr(isolation, "bridge_snapshot", lambda home: {})
    def sampler(*a, **k):
        thread = threading.Thread(target=lambda: None)
        thread.start()
        return thread
    monkeypatch.setattr(cli, "load_sampler", sampler)
    layout.results.mkdir(parents=True)
    return layout, cleaned


def scale_records(layout: Layout) -> list[dict]:
    import json
    return [json.loads(line) for line in layout.raw_jsonl.read_text().splitlines()]


def test_scale_with_every_launch_failing_records_each_receiver_and_cleans_every_run(scale_layout, monkeypatch):
    from agentcomms import cli, scale

    layout, cleaned = scale_layout

    def broken(layout, receiver, m):
        raise RuntimeError(f"{receiver.label} did not start")
    monkeypatch.setattr(cli, "scale_launch", broken)
    assert cli.main(["scale"]) == cli.CELL_ERROR
    records = scale_records(layout)
    assert sorted(r["notes"].split("scale-receiver=")[1].split(";")[0] for r in records) == sorted(
        r.label for r in scale.receivers())
    assert {r["delivery"] for r in records} == {"error"}
    assert len(cleaned) == len(scale.MIX)
    assert len(list(layout.results.glob("scale-*.json"))) == 1


def test_one_failing_scale_receiver_keeps_the_others_records_and_the_summary(scale_layout, monkeypatch):
    from types import SimpleNamespace

    from agentcomms import cli, scale
    from agentcomms.model import Ack, Delivery, DraftFate
    from agentcomms.records import ResultRecord
    from agentcomms.scenarios import common

    layout, _ = scale_layout

    def launched(layout, receiver, m):
        target = SimpleNamespace(run_id=m.run_id, agent=receiver.agent)
        return object(), SimpleNamespace(name=receiver.mechanism), m, SimpleNamespace(target=target)
    broken_run = []

    def send(cell, target, body, timeout):
        if not broken_run:
            broken_run.append(target.run_id)
        if target.run_id == broken_run[0]:
            raise RuntimeError("pane vanished")
        return target

    def finish(cell, out, wall0, mono0):
        return ResultRecord(out.run_id, "shortlist", out.agent, {}, "m", "tmux", "none", "SCALE", cell.rep, "raw",
                            Delivery.DELIVERED, None, DraftFate.NA, Ack.ACKED, False, 0, 0.1)
    broken = []

    class WatchedBarrier(cli.threading.Barrier):
        def __init__(self, parties, timeout=None):
            super().__init__(parties, timeout=30)

        def wait(self, timeout=None):
            try:
                return super().wait(timeout)
            except cli.threading.BrokenBarrierError:
                broken.append(True)
                raise
    monkeypatch.setattr(cli.threading, "Barrier", WatchedBarrier)
    monkeypatch.setattr(cli, "scale_launch", launched)
    monkeypatch.setattr(common, "send_and_observe", send)
    monkeypatch.setattr(common, "finish", finish)
    assert cli.main(["scale"]) == cli.CELL_ERROR
    assert broken == []
    records = scale_records(layout)
    failed = [r for r in records if r["run_id"] == broken_run[0]]
    assert [r["delivery"] for r in failed] == ["error"]
    assert "pane vanished" in failed[0]["notes"]
    assert sum(r["delivery"] == "delivered" for r in records) == (len(scale.MIX) - 1) * scale.MESSAGES
    [summary] = layout.results.glob("scale-*.json")
    import json
    data = json.loads(summary.read_text())
    assert (data["delivered"], data["errors"]) == ([21, 21], 1)


def test_agents_and_terminal_hosts_get_a_tmpdir_inside_the_run(tmp_path):
    from agentcomms import isolation
    from agentcomms.hosts import zellij, zmx

    runs = tmp_path / "runs"
    home = runs / RUN_ID / "home" / "droid"
    iso = isolation.build_home("droid", home, runs / RUN_ID / "work" / "droid", runs, "0.251.0", "m", "low", "auto",
                               {"HOME": "/Users/u", "PATH": "/usr/bin", "TMPDIR": "/var/folders/xy/T/"}, 0.0)
    assert iso.env["TMPDIR"] == str(home / "tmp")
    assert (home / "tmp").is_dir()
    state = tmp_path / "ac" / f"{RUN_ID}-zj"
    assert zellij.zellij_env(state)["TMPDIR"] == str(state / "tmp")
    assert zmx.zmx_env(state)["TMPDIR"] == str(state / "tmp")


def test_a_zmx_session_that_never_lists_is_stopped_before_start_fails(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from agentcomms.hosts import zmx

    stopped = []
    monkeypatch.setattr(zmx, "SESSION_UP_S", 0.0)
    monkeypatch.setattr(zmx, "spawn_in_pty", lambda *a, **k: SimpleNamespace(close=lambda: None))
    host = zmx.ZmxHost(Path("/v/zmx"))
    monkeypatch.setattr(host, "sessions", lambda state: {})
    monkeypatch.setattr(host, "stop", stopped.append)
    state = tmp_path / f"{RUN_ID}-zmx"
    with pytest.raises(zmx.ZmxError, match="did not appear"):
        host.start("recv", ["/bin/true"], {}, tmp_path, None, state)
    assert stopped == [zmx.make_ref(state, "recv")]


def test_a_zellij_session_whose_pane_never_lists_is_stopped_before_start_fails(tmp_path, monkeypatch):
    from agentcomms.hosts import zellij

    stopped = []
    monkeypatch.setattr(zellij, "SESSION_UP_S", 0.0)
    monkeypatch.setattr(zellij.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, b"", b""))
    host = zellij.ZellijHost(Path("/v/zellij"))
    monkeypatch.setattr(host, "pane_listed", lambda ref: False)
    monkeypatch.setattr(host, "stop", stopped.append)
    state = tmp_path / f"{RUN_ID}-zj"
    with pytest.raises(zellij.ZellijError, match="did not appear"):
        host.start("recv", ["/bin/true"], {}, tmp_path, None, state)
    assert stopped == [zellij.make_ref(state, "recv")]


def test_a_failed_codex_daemon_start_check_stops_the_forked_daemon(tmp_path, monkeypatch):
    from agentcomms import procs
    from agentcomms.procs import ProcRow

    home = tmp_path / "runs" / RUN_ID / "home" / "codex"
    (home / "app-server-daemon").mkdir(parents=True)
    (home / "app-server-daemon" / "daemon.pid").write_text('{"pid": 4242}')
    spec = backends.BackendSpec("codex-daemon", ["/v/codex", "app-server", "daemon", "start"],
                                {"CODEX_HOME": str(home)}, str(tmp_path), None, str(tmp_path / "log"))
    verbs, killed = [], []

    def command(spec, verb, run_dir, user_home):
        verbs.append(verb)
        return subprocess.CompletedProcess([], 1 if verb == "start" else 0)
    monkeypatch.setattr(backends, "run_daemon_command", command)
    monkeypatch.setattr(procs, "alive", lambda pid: True)
    monkeypatch.setattr(procs, "ps_rows", lambda: [ProcRow(4242, 1, 4242, "/v/codex app-server daemon run")])
    monkeypatch.setattr(backends, "terminate", lambda pid, group, grace_s: killed.append((pid, group)))
    with pytest.raises(backends.BackendError, match="stopped daemon pid 4242"):
        backends.start_daemon(spec, tmp_path / "runs" / RUN_ID, tmp_path / "user")
    assert verbs == ["start", "stop"]
    assert killed == [(4242, False)]


def test_a_stale_daemon_pid_of_another_program_is_left_alone(tmp_path, monkeypatch):
    from agentcomms.procs import ProcRow

    spec = backends.BackendSpec("codex-daemon", ["/v/codex", "app-server", "daemon", "start"], {}, "", None, "log")
    assert backends.runs_codex([ProcRow(4242, 1, 4242, "/bin/zsh -l")], 4242, spec) is False
    assert backends.runs_codex([ProcRow(4242, 1, 4242, "/v/codex app-server daemon run")], 4242, spec) is True


def test_cleanup_kills_an_untracked_session_whose_pane_works_in_the_run(tmp_path, monkeypatch):
    layout = Layout(tmp_path / "repo")
    run_dir = layout.run_dir(RUN_ID)
    listing = f"{RUN_ID}-claude\t{run_dir}/work/claude\nuser-thing\t/Users/u\nother\t{run_dir}x/work\n"
    calls = []

    def fake_tmux(layout, *args, socket="agentcomms"):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, listing if args[0] == "list-panes" else "", "")
    monkeypatch.setattr(manifest, "_tmux", fake_tmux)
    monkeypatch.setattr(manifest, "SOCKET_DIR", tmp_path / "ac")
    monkeypatch.setattr(manifest, "CLAUDE_SOCK_DIR", tmp_path / "cc-socks")
    manifest.save(layout, Manifest(RUN_ID, [], [], [], []))
    report = manifest.cleanup(layout, RUN_ID, grace_s=0.0, kill_server=False)
    assert [c for c in calls if c[0] == "kill-session"] == [("kill-session", "-t", f"={RUN_ID}-claude")]
    assert f"killed untracked tmux session {RUN_ID}-claude (its pane works in the run)" in report


def test_a_timed_out_iterm_call_cancels_its_coroutine():
    import asyncio
    import concurrent.futures

    from agentcomms.hosts.iterm2 import ItermLoop

    loop = ItermLoop()
    loop.connection = object()
    cancelled = []

    async def slow(connection):
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
    try:
        with pytest.raises(concurrent.futures.TimeoutError):
            loop.call(slow, timeout=0.2)
        deadline = time.monotonic() + 2
        while not cancelled and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        loop.close()
    assert cancelled == [True]


def test_a_bridge_cli_timeout_kills_the_whole_process_group():
    import os

    from agentcomms.adapters.bridge import run_cli

    t0 = time.monotonic()
    result = run_cli(["/bin/sh", "-c", "sleep 30 & echo $!; wait"], {"PATH": "/usr/bin:/bin"}, timeout_s=0.5)
    assert time.monotonic() - t0 < 5
    assert result.code == 124
    child = int(result.stdout.split()[0])
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)


def opencode_overlay(tmp_path: Path, inv):
    from agentcomms import userconfig
    from agentcomms.model import LaunchMods

    run_dir = tmp_path / "runs" / RUN_ID
    home = run_dir / "home" / "opencode"
    env = {"XDG_DATA_HOME": str(home / "data"), "XDG_STATE_HOME": str(home / "state")}
    return userconfig.overlay(inv, env, LaunchMods(host="tmux"), home, run_dir / "work", run_dir, tmp_path / "user",
                              "m", "low"), run_dir


@pytest.mark.parametrize("disable", ["PATH=<run>/bin/user-config (no-op `rl`) first", "-c notify=[]"])
def test_a_declared_switch_the_agents_overlay_does_not_build_skips_the_cell(tmp_path, disable):
    from agentcomms import userconfig
    from agentcomms.userconfig import Integration, Inventory

    inv = Inventory("opencode", (Integration("extension", "x-ringleader", True, disable),))
    ov, run_dir = opencode_overlay(tmp_path, inv)
    assert userconfig.skip_reason(inv, "opencode-server-queue") is None
    with pytest.raises(userconfig.UserConfigSkip, match="x-ringleader"):
        userconfig.verify(inv, ov, run_dir)


def test_opencode_hooklinesinker_counts_as_switched_off_by_its_state_dir_inside_the_run(tmp_path):
    from agentcomms import userconfig
    from agentcomms.userconfig import Inventory

    inv = Inventory("opencode", (userconfig.classify("opencode", "plugin", "hooklinesinker-opencode.ts"),))
    ov, run_dir = opencode_overlay(tmp_path, inv)
    userconfig.verify(inv, ov, run_dir)
    outside = replace(ov, env=ov.env | {"XDG_STATE_HOME": str(tmp_path / "user" / ".local" / "state")})
    with pytest.raises(userconfig.UserConfigSkip, match=r"hooklinesinker-opencode\.ts"):
        userconfig.verify(inv, outside, run_dir)


def test_codex_switches_must_be_in_both_the_tui_and_backend_argv(tmp_path):
    from agentcomms import userconfig
    from agentcomms.model import LaunchMods
    from agentcomms.userconfig import Inventory

    inv = Inventory("codex", (userconfig.classify("codex", "notify", "client"),
                              userconfig.classify("codex", "mcp", "context7")))
    run_dir = tmp_path / "runs" / RUN_ID
    mods = LaunchMods(host="tmux", backend="codex-app-server", backend_argv=("/v/codex", "app-server", "--listen", "x"))
    ov = userconfig.overlay(inv, {}, mods, run_dir / "home", run_dir / "work", run_dir, tmp_path / "user", "m", "low")
    userconfig.verify(inv, ov, run_dir)
    assert ov.mods.backend_argv[:3] == ("/v/codex", "-c", "notify=[]")
    stripped = replace(ov, mods=replace(ov.mods, backend_argv=mods.backend_argv))
    with pytest.raises(userconfig.UserConfigSkip, match=r"client \(-c notify=\[\]\), context7"):
        userconfig.verify(inv, stripped, run_dir)


def test_an_unreviewed_hook_or_plugin_is_unclassified_and_skips_the_cell(tmp_path):
    from agentcomms import userconfig
    from agentcomms.userconfig import Inventory

    hook = userconfig.classify("codex", "hook", "post-to-slack")
    plugin = userconfig.classify("opencode", "plugin", "new-plugin.ts")
    assert (hook.outward, hook.disable, hook.why) == (True, None, userconfig.UNCLASSIFIED)
    reviewed = userconfig.classify("codex", "hook", "agent-sandbox-status")
    assert (reviewed.outward, reviewed.why) == (False, "")
    assert userconfig.skip_reason(Inventory("codex", (hook, reviewed)), "codex-remote-start") == (
        "skipped: unclassified integration post-to-slack")
    assert userconfig.skip_reason(Inventory("opencode", (plugin,)), "opencode-server-queue") == (
        "skipped: unclassified integration new-plugin.ts")


def test_a_user_config_skip_found_at_launch_is_recorded_as_na(tmp_path, monkeypatch):
    import json

    from agentcomms import cli, isolation, userconfig
    from agentcomms.engine import Engine

    home = tmp_path / "user"
    (home / ".config" / "opencode").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    layout = Layout(tmp_path / "repo")
    monkeypatch.setattr(cli, "default_layout", lambda: layout)
    monkeypatch.setattr(manifest, "cleanup", lambda layout, run_id, kill_server=True: [])
    monkeypatch.setattr(manifest, "remaining_pids", lambda layout, run_id: set())
    monkeypatch.setattr(isolation, "global_config_hashes", lambda: {})
    monkeypatch.setattr(isolation, "user_state_mtimes", lambda agent: {})
    monkeypatch.setattr(isolation, "bridge_snapshot", lambda home: {})
    monkeypatch.setattr(userconfig, "inventory", lambda agent, home, runs: userconfig.Inventory(agent))

    def launch(self, m, agent, mode="auto", adapter=None):
        raise userconfig.UserConfigSkip("skipped: switch not applied in the built argv/env for x")
    monkeypatch.setattr(Engine, "launch", launch)
    assert cli.main(["run", "--stage", "user-config", "--agent", "opencode", "--adapter", "tmux-paste"]) == 0
    [record] = [json.loads(line) for line in layout.raw_jsonl.read_text().splitlines()]
    assert (record["delivery"], record["notes"]) == ("n/a", "n/a: skipped: switch not applied in the built "
                                                             "argv/env for x")


def test_a_user_config_cell_lists_its_writes_into_the_users_stores(tmp_path, monkeypatch):
    import json

    from agentcomms import cli, isolation, userconfig
    from agentcomms.engine import Engine, Launched
    from agentcomms.model import Ack, Delivery, DraftFate
    from agentcomms.profiles import Binary
    from agentcomms.records import ResultRecord

    home = tmp_path / "user"
    (home / ".codex" / "sessions").mkdir(parents=True)
    (home / ".codex" / "config.toml").write_text("")
    monkeypatch.setenv("HOME", str(home))
    layout = Layout(tmp_path / "repo")
    monkeypatch.setattr(cli, "default_layout", lambda: layout)
    monkeypatch.setattr(manifest, "cleanup", lambda layout, run_id, kill_server=True: [])
    monkeypatch.setattr(manifest, "remaining_pids", lambda layout, run_id: set())
    monkeypatch.setattr(isolation, "global_config_hashes", lambda: {})
    monkeypatch.setattr(isolation, "user_state_mtimes", lambda agent: {})
    monkeypatch.setattr(isolation, "bridge_snapshot", lambda home: {})
    monkeypatch.setattr(userconfig, "inventory", lambda agent, home, runs: userconfig.Inventory(agent))

    def launch(self, m, agent, mode="auto", adapter=None):
        (home / ".codex" / "sessions" / "rollout-x.jsonl").write_text("{}\n")
        t = Target(m.run_id, agent, "tmux", "none", layout.work_dir(m.run_id, agent), home / ".codex", None,
                   f"agentcomms:{m.run_id}-{agent}", None, None, 1)
        return m, Launched(t, Binary("codex", Path("/c"), "1"), {}, layout.root / "p.log", "pane-regex", [])

    def run_cell(self, m, launched, adapter, scenario, stage, rep):
        return ResultRecord(m.run_id, stage, "codex", {}, adapter.name, "tmux", "none", "S1", rep, "raw",
                            Delivery.DELIVERED, True, DraftFate.NA, Ack.ACKED, False, 0, 0.1, notes="ready=x")
    monkeypatch.setattr(Engine, "launch", launch)
    monkeypatch.setattr(Engine, "run_cell", run_cell)
    monkeypatch.setattr(Engine, "resolved_session", lambda self, m, target: m)
    monkeypatch.setattr(Engine, "check_versions", lambda self, launched: True)
    assert cli.main(["run", "--stage", "user-config", "--agent", "codex", "--adapter", "tmux-paste"]) == 0
    [record] = [json.loads(line) for line in layout.raw_jsonl.read_text().splitlines()]
    assert f"user-store-writes=1 (runs/{record['run_id']}/user-store-writes.txt)" in record["notes"]
    listed = (layout.run_dir(record["run_id"]) / "user-store-writes.txt").read_text()
    assert listed == "~/.codex/sessions/rollout-x.jsonl\n"


def test_opencode_store_writes_include_node_modules(tmp_path):
    from agentcomms import isolation

    home = tmp_path / "user"
    (home / ".config" / "opencode" / "node_modules" / "x").mkdir(parents=True)
    before = isolation.user_store_mtimes("opencode", home)
    (home / ".config" / "opencode" / "node_modules" / "x" / "index.js").write_text("")
    after = isolation.user_store_mtimes("opencode", home)
    assert isolation.changed_paths(before, after) == [str(home / ".config/opencode/node_modules/x/index.js")]


def opencode_db(path: Path, order_column: str) -> Path:
    import sqlite3

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE session_message (id TEXT, session_id TEXT, type TEXT, {order_column} INTEGER, "
                 "time_created INTEGER, data TEXT)")
    conn.execute("INSERT INTO session_message VALUES ('m1', 'ses_1', 'user', 1, 1, '{}')")
    conn.commit()
    conn.close()
    return path


def test_opencode_reader_raises_on_schema_drift_instead_of_reporting_nothing(tmp_path):
    from agentcomms.transcripts import opencode

    drifted = opencode_db(tmp_path / "a" / "opencode.db", "position")
    with pytest.raises(opencode.SchemaDriftError, match="no such column: seq"):
        opencode.read_session(drifted, "ses_1")
    current = opencode_db(tmp_path / "b" / "opencode.db", "seq")
    messages, queued = opencode.read_session(current, "ses_1")
    assert ([m["id"] for m in messages], queued) == (["m1"], [])
    assert opencode.find_sessions(current, tmp_path) == []


def test_a_pi_ext_write_without_a_reply_leaves_the_verdict_to_the_transcript(tmp_path, monkeypatch):
    from agentcomms.adapters import pi_ext
    from agentcomms.engine import classify_delivery
    from agentcomms.model import Delivery

    monkeypatch.setattr(pi_ext.unix_send, "send", lambda path, body: "")
    t = Target(RUN_ID, "pi", "tmux", "none", tmp_path / "runs" / RUN_ID / "work" / "pi", tmp_path, None, "x", None,
               None, 1)
    receipt = pi_ext.PiExt().send(t, "hi")
    assert receipt.accepted is True and receipt.detail.endswith("verdict from the transcript")
    assert classify_delivery(receipt.accepted, []) is Delivery.LOST
    monkeypatch.setattr(pi_ext.unix_send, "send", lambda path, body: "error compacting")
    assert pi_ext.PiExt().send(t, "hi").accepted is False


def test_a_codex_turn_request_written_without_a_reply_is_not_a_rejection(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from agentcomms.adapters import codex_remote as adapter
    from agentcomms.senders import codex_remote

    class Silent:
        def busy_turn(self, thread):
            return None

        def call(self, make, *args):
            raise TimeoutError("app server reply deadline passed")
    with pytest.raises(codex_remote.WrittenTimeout):
        codex_remote.deliver(Silent(), "t", "hi", "start", 1.0)

    class Client:
        def __init__(self, path, timeout_s):
            pass

        def initialize(self):
            pass

        def busy_turn(self, thread):
            return None

        def close(self):
            pass
    monkeypatch.setattr(adapter, "owned_thread", lambda sock, target: "t")
    monkeypatch.setattr(adapter.codex_remote, "Client", Client)
    monkeypatch.setattr(adapter.codex_remote, "pending", lambda spool: False)
    monkeypatch.setattr(adapter.codex_remote, "deliver", lambda *a: (_ for _ in ()).throw(
        codex_remote.WrittenTimeout("request written, no reply: deadline")))
    t = SimpleNamespace(work_dir=tmp_path / "runs" / RUN_ID / "work" / "codex", backend_ref=f"/tmp/ac/{RUN_ID}.sock")
    receipt = adapter.CodexRemoteSteer().send(t, "hi")
    assert receipt.accepted is True
    assert receipt.detail == "request written, no reply: deadline; verdict from the transcript"


def test_the_notes_scenarios_write_are_the_markers_the_batch_and_scoring_read(tmp_path, monkeypatch):
    from agentcomms import checkpoint, cli, markers, scoring
    from agentcomms.model import Delivery
    from agentcomms.scenarios import s12
    from agentcomms.scenarios.common import Outcome, finish

    monkeypatch.setattr(checkpoint, "network_ok", lambda: True)
    crashed = finish(fake_cell(tmp_path, gone="pane-exited"), Outcome(Delivery.LOST, tokens=["t"]), time.time(),
                     time.monotonic())
    assert cli.pauses_batch(crashed.to_dict()) is True
    respawned = {"scenario": "S12", "delivery": "delivered", "intact": None, "harmful": False,
                 "notes": f"backend-restart=x; {s12.RESPAWNED_NOTE}"}
    assert scoring.is_good(respawned) is False
    assert cli.PAUSE_MARKERS == (markers.API_ERROR, markers.CRASH, markers.AUTH_REQUIRED)


def test_burst_verdict_separates_a_blocking_adapter_from_a_slow_harness():
    from agentcomms.model import Delivery
    from agentcomms.scenarios import s5

    assert s5.burst_verdict(0.6, 0.05) is None
    assert s5.burst_verdict(6.8, 6.3) == (Delivery.NA, "n/a: adapter cannot burst (window 6.80s)")
    assert s5.burst_verdict(1.34, 0.8) == (Delivery.ERROR, "precondition: burst-window (window 1.34s, adapter "
                                                           "sends 0.80s; the harness took the rest)")


def s5_cell(tmp_path: Path, send_s: float, check_s: float):
    from types import SimpleNamespace

    from agentcomms.model import SendReceipt

    cell = fake_cell(tmp_path, gone=None, scenario="S5")

    def send(target, text):
        started = (time.time(), time.monotonic())
        time.sleep(send_s)
        return SendReceipt(True, *started)
    entries = []

    def check(target, live=True):
        time.sleep(0 if live else check_s)
    cell.adapter.send = send
    cell.engine.check_owned = check
    cell.engine.track_spawned = lambda m, pids: m
    cell.engine.wait_for_acks = lambda target, tokens, timeout: (SimpleNamespace(
        entries=lambda: [(1.0, "user", f'ACK-REQUEST {t}: x') for t in tokens], path=tmp_path / "t"), True)
    cell.engine.snapshot = lambda target, label: ""
    cell.engine.write_body_diff = lambda *a: "diff"
    return cell, entries


def test_s5_records_a_blocking_adapter_as_na_and_a_slow_harness_as_error(tmp_path):
    from agentcomms.model import Delivery
    from agentcomms.scenarios import s5

    blocking, _ = s5_cell(tmp_path, send_s=0.25, check_s=0.0)
    out = s5.run(blocking)
    assert out.delivery is Delivery.NA
    assert out.notes[0].startswith("n/a: adapter cannot burst (window ")
    slow, _ = s5_cell(tmp_path, send_s=0.0, check_s=0.25)
    out = s5.run(slow)
    assert out.delivery is Delivery.ERROR
    assert out.notes[0].startswith("precondition: burst-window (window ")
    fast, _ = s5_cell(tmp_path, send_s=0.0, check_s=0.0)
    assert s5.run(fast).delivery is Delivery.DELIVERED


def test_s5_counts_adapter_work_before_the_send_stamp_as_the_adapters(tmp_path):
    from agentcomms.model import Delivery, SendReceipt
    from agentcomms.scenarios import s5

    cell, _ = s5_cell(tmp_path, send_s=0.0, check_s=0.0)

    def send(target, text):
        time.sleep(0.25)
        return SendReceipt(True, time.time(), time.monotonic())
    cell.adapter.send = send
    out = s5.run(cell)
    assert out.delivery is Delivery.NA
    assert out.notes[0].startswith("n/a: adapter cannot burst (window ")


def test_s5_counts_tracking_after_the_send_as_the_harnesss(tmp_path):
    from agentcomms.model import Delivery
    from agentcomms.scenarios import s5

    cell, _ = s5_cell(tmp_path, send_s=0.0, check_s=0.0)
    cell.engine.track_spawned = lambda m, pids: time.sleep(0.25) or m
    out = s5.run(cell)
    assert out.delivery is Delivery.ERROR
    assert "adapter sends 0.0" in out.notes[0]


def test_a_pid_is_adopted_only_from_the_harness_or_run_tree_or_with_its_cwd_in_the_run(tmp_path):
    from agentcomms import procs
    from agentcomms.procs import ProcRow

    run_dir = tmp_path / "runs" / RUN_ID
    rows = [ProcRow(10, 1, 10, "python harness"), ProcRow(11, 10, 11, "backend"), ProcRow(20, 1, 20, "daemon"),
            ProcRow(30, 1, 30, "user shell")]
    cwd = {20: str(run_dir / "work" / "codex"), 30: "/Users/u"}
    assert procs.with_provenance(rows, [11, 20, 30], {10}, cwd, run_dir) == [11, 20]


def test_engine_refuses_to_track_a_reused_pid_from_a_stale_pid_file(tmp_path, monkeypatch, capsys):
    from agentcomms import procs
    from agentcomms.engine import Engine
    from agentcomms.procs import ProcRow

    layout = Layout(tmp_path)
    engine = Engine(layout, environ={"HOME": str(tmp_path)})
    m = Manifest(RUN_ID, [], [], [], [])
    manifest.save(layout, m)
    monkeypatch.setattr(procs, "ps_rows", lambda: [ProcRow(30, 1, 30, "/bin/zsh -l")])
    monkeypatch.setattr(procs, "cwds", lambda pids: {30: "/Users/u"})
    monkeypatch.setattr(procs, "identities", lambda pids: {p: f"id-{p}" for p in pids})
    m = engine.track(m, "codex-daemon", [30])
    assert m.backends == []
    assert "not tracking codex-daemon pid 30" in capsys.readouterr().err


def test_only_pushed_entry_kinds_count_as_receipt():
    from agentcomms.engine import classify_delivery, receiver_hits
    from agentcomms.model import Delivery

    polled = [(1.0, "tool_result", "[event] ACK-REQUEST t1: x"), (2.0, "system", "ACK-REQUEST t1 shown"),
              (3.0, "queue", "ACK-REQUEST t1"), (4.0, "future_kind", "ACK-REQUEST t1")]
    assert receiver_hits(polled, "t1") == []
    assert classify_delivery(True, receiver_hits(polled, "t1")) is Delivery.LOST
    pushed = [*polled, (5.0, "peer", "ACK-REQUEST t1: x")]
    assert receiver_hits(pushed, "t1") == [(5.0, "peer", "ACK-REQUEST t1: x")]


def test_the_launch_host_comes_from_the_adapters_host_kind(tmp_path, monkeypatch):
    from agentcomms import profiles
    from agentcomms.engine import Engine
    from agentcomms.model import LaunchMods

    class ZellijAdapter:
        name, host_kind = "zellij-write", "zellij"
        agents = frozenset({"droid"})

        def launch_mods(self, agent, work_dir, home_dir):
            return LaunchMods(host="tmux")

        def run_sockets(self, work_dir):
            return []
    engine = Engine(Layout(tmp_path), environ={"HOME": str(tmp_path), "PATH": "/usr/bin"})
    started = {}
    monkeypatch.setattr(engine, "resolve", lambda agent: profiles.Binary("droid", Path("/d/droid"), "0.251.0"))
    monkeypatch.setattr(engine, "host_for", lambda kind: type("H", (), {"term": "xterm"})())
    monkeypatch.setattr(engine, "start", lambda m, launched, argv, sid, name, log, backend, ref, host: started.update(
        host=host, mods=launched.mods.host) or (m, launched))
    engine.launch(engine.new_run(), "droid", adapter=ZellijAdapter())
    assert started == {"host": "zellij", "mods": "zellij"}


def test_cleanup_stops_zmx_and_zellij_sessions_before_removing_their_state(tmp_path, monkeypatch):
    from agentcomms import hosts

    stopped = []

    class Host:
        def __init__(self, kind):
            self.kind = kind

        def stop(self, ref):
            stopped.append((self.kind, ref))
    monkeypatch.setattr(hosts, "make_host", Host)
    layout = Layout(tmp_path / "repo")
    t = codex_target(layout, layout.home_dir(RUN_ID, "codex"), "none")
    zmx_t = replace(t, host="zmx", host_ref=f"zmx:/tmp/ac/{RUN_ID}-zmx:recv")
    assert manifest.stop_multiplexer_sessions(Manifest(RUN_ID, [], [t, zmx_t], [], [])) == (
        ["stopped zmx session recv"], set())
    assert stopped == [("zmx", f"zmx:/tmp/ac/{RUN_ID}-zmx:recv")]


def test_sigkill_after_the_grace_period_spares_a_pid_reused_in_between(monkeypatch):
    from agentcomms import procs

    calls = iter([{10: "a", 11: "b"}, {10: "a", 11: "someone-else"}])
    signalled = []
    monkeypatch.setattr(procs, "identities", lambda pids: next(calls))
    monkeypatch.setattr(procs, "alive", lambda pid: True)
    monkeypatch.setattr(manifest, "_signal", lambda pids, sig: signalled.append((set(pids), sig)))
    assert manifest.terminate_same({10, 11}, grace_s=0.0) == 1
    assert signalled[-1] == ({10}, 9)


def test_a_partial_trailing_record_line_is_skipped_on_read():
    from agentcomms import checkpoint

    assert checkpoint.parse_records('{"a": 1}\n{"b": 2}\n{"c": ') == [{"a": 1}, {"b": 2}]
    assert checkpoint.parse_records('{"a": 1}\n{"b": 2}') == [{"a": 1}, {"b": 2}]


def test_concurrency_is_capped_at_three_outside_pilot():
    from agentcomms import cli

    assert [cli.concurrency(stage, 8) for stage in ("pilot", "screen", "extensive")] == [1, 3, 3]


def test_s9_refuses_the_embedded_codex_queue_route(capsys):
    from agentcomms import cli

    assert cli.main(["s9", "--a", "claude", "--b", "codex", "--fwd", "codex-queue-embedded", "--back",
                     "claude-uds-accept"]) == 2
    assert "codex-queue-embedded is not an S9 route (R30)" in capsys.readouterr().err


def test_gc_nudge_is_refused_under_nono(tmp_path, monkeypatch, capsys):
    from agentcomms import cli

    monkeypatch.setattr(cli, "default_layout", lambda: Layout(tmp_path))
    monkeypatch.setattr(cli.profiles, "nono_wrapper", lambda: ["nono", "run"])
    assert cli.main(["run", "--agent", "claude", "--adapter", "gc-nudge", "--sandbox", "nono"]) == 2
    assert "gc-nudge cannot run under --sandbox nono" in capsys.readouterr().err


def test_tmux_refuses_a_non_harness_socket_name():
    from agentcomms.hosts.tmux import TmuxError, socket_args

    with pytest.raises(TmuxError, match="cadet-city"):
        socket_args("cadet-city")


def test_owned_group_never_adopts_launchd_or_the_harness_group():
    from agentcomms import procs
    from agentcomms.procs import ProcRow

    rows = [ProcRow(50, 1, 1, "x"), ProcRow(60, 1, 77, "y")]
    assert procs.owned_group(rows, 50) == 50
    assert procs.owned_group(rows, 60, own_pgid=77) == 60


def test_the_pi_rl_switch_needs_the_no_op_shim_first_on_path(tmp_path):
    from agentcomms import userconfig
    from agentcomms.model import LaunchMods
    from agentcomms.userconfig import Inventory

    inv = Inventory("pi", (userconfig.classify("pi", "extension", "pi-ringleader-finish.ts"),))
    run_dir = tmp_path / "runs" / RUN_ID
    ov = userconfig.overlay(inv, {}, LaunchMods(host="tmux"), run_dir / "home", run_dir / "work", run_dir,
                            tmp_path / "user", "m", "low")
    userconfig.verify(inv, ov, run_dir)
    behind = replace(ov, mods=replace(ov.mods, path_prepend=("/opt/homebrew/bin", *ov.mods.path_prepend)))
    with pytest.raises(userconfig.UserConfigSkip, match=r"pi-ringleader-finish\.ts"):
        userconfig.verify(inv, behind, run_dir)


def test_engine_launch_verifies_the_overlay_before_starting_anything(tmp_path, monkeypatch):
    from agentcomms import profiles, userconfig
    from agentcomms.engine import Engine
    from agentcomms.userconfig import Integration, Inventory

    home = tmp_path / "user"
    engine = Engine(Layout(tmp_path / "repo"), environ={"HOME": str(home), "PATH": "/usr/bin"}, user_config=True)
    binary = profiles.Binary("pi", Path("/m/node_modules/pi/cli.js"), "1.4.0", "pi", Path("/n/node"), "24")
    monkeypatch.setattr(engine, "resolve", lambda agent: binary)
    monkeypatch.setattr(userconfig, "inventory", lambda agent, home, runs: Inventory(
        "pi", (Integration("notify", "client", True, "-c notify=[]"),)))
    monkeypatch.setattr(engine, "start", lambda *a, **k: (_ for _ in ()).throw(AssertionError("started")))
    with pytest.raises(userconfig.UserConfigSkip, match=r"client \(-c notify=\[\]\)"):
        engine.launch(engine.new_run(), "pi")


def test_a_detached_process_running_vendored_code_keeps_its_provenance(tmp_path):
    from agentcomms import procs
    from agentcomms.procs import ProcRow

    vendor = tmp_path / "vendor"
    rows = [ProcRow(40, 1, 40, f"/usr/bin/node {vendor.resolve()}/agent-intercom-pi/broker.js"),
            ProcRow(41, 1, 41, "/usr/bin/node /Users/u/other.js")]
    cwd = {40: "/", 41: "/"}
    assert procs.with_provenance(rows, [40, 41], set(), cwd, tmp_path / "runs" / RUN_ID, vendor) == [40]


def test_backend_spec_with_the_server_password_is_written_private(tmp_path):
    spec = backends.BackendSpec("opencode-server", ["/v/opencode", "serve"], {"OPENCODE_PASSWORD": "pw"}, "", None,
                                "log")
    backends.save_spec(tmp_path, spec)
    assert backends.spec_path(tmp_path).stat().st_mode & 0o777 == 0o600
    assert backends.load_spec(tmp_path) == spec


def test_a_down_message_counts_as_seen_only_in_a_pushed_entry():
    from types import SimpleNamespace

    from agentcomms.scenarios import s6

    queued = SimpleNamespace(entries=lambda: [(1.0, "queue", "ACK-REQUEST d1: down")])
    pushed = SimpleNamespace(entries=lambda: [(2.0, "user", "ACK-REQUEST d1: down")])
    assert s6.down_seen([queued], "d1") is False
    assert s6.down_seen([queued, pushed], "d1") is True


def test_safety_never_exceeds_its_fixed_denominator():
    from agentcomms import shortlist

    base = {"run_id": "r", "stage": "extensive", "agent": "pi", "mechanism": "m", "intact": True, "harmful": False,
            "draft_fate": "n/a", "notes": "", "versions": {"pi": "1.4.0"}}
    records = ([base | {"scenario": "S2", "delivery": "queued"}] * 4
               + [base | {"scenario": "S7", "delivery": "delivered", "draft_fate": "preserved"}] * 3
               + [base | {"scenario": "S3", "delivery": "delivered"}])
    score = shortlist.score(shortlist.with_equivalence(shortlist.counted_records(records))[("pi", "m")])
    assert score.safety_k == shortlist.SAFETY_DENOMINATOR


def test_codex_subagent_rollouts_are_not_observed_as_the_receivers_transcript(tmp_path):
    import json

    from agentcomms.engine import Engine

    home, work = tmp_path / "home", tmp_path / "work"
    day = home / "sessions" / "2026" / "10" / "29"
    day.mkdir(parents=True)
    for name, source in (("rollout-a.jsonl", "cli"), ("rollout-b.jsonl", "subagent")):
        (day / name).write_text(json.dumps({"type": "session_meta", "payload": {"cwd": str(work),
                                                                                 "thread_source": source}}) + "\n")
    t = Target(RUN_ID, "codex", "tmux", "none", work, home, None, "x", None, None, None)
    found = Engine(Layout(tmp_path), environ={"HOME": str(tmp_path)}).all_transcripts(t)
    assert [p.path.name for p in found] == ["rollout-a.jsonl"]
