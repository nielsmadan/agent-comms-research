import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from agentcomms import manifest, procs
from agentcomms.manifest import OwnershipError, assert_owned, is_owned, owned_target, socket_removable
from agentcomms.model import Manifest, Target
from agentcomms.paths import Layout
from agentcomms.procs import ProcRow, owned_pids

RUNS = Path("/repo/runs")


def owned(run_id: str = "20261024-101500-a1b2") -> Target:
    return Target(run_id=run_id, agent="claude", host="tmux", backend="none",
                  work_dir=RUNS / run_id / "work" / "claude", home_dir=RUNS / run_id / "home" / "claude",
                  session_id="sid-1", host_ref=f"agentcomms:{run_id}-claude", backend_ref=None,
                  transcript=None, agent_pid=200)


def manifest_with(*targets: Target) -> Manifest:
    return Manifest(run_id="20261024-101500-a1b2", pgids=[100], targets=list(targets), sockets=[],
                    backends=[])


def test_owned_target_passes_guard():
    m = manifest_with(owned())
    assert is_owned(m, owned(), RUNS)
    assert owned_target(m, RUNS, agent="claude") == owned()


def test_guard_rejects_target_missing_from_manifest():
    m = manifest_with(owned())
    stranger = replace(owned(), host_ref="agentcomms:users-own-session")
    with pytest.raises(OwnershipError):
        assert_owned(m, stranger, RUNS)


def test_guard_rejects_work_dir_outside_run():
    m = manifest_with(replace(owned(), work_dir=Path("/Users/me/project")))
    with pytest.raises(OwnershipError):
        assert_owned(m, replace(owned(), work_dir=Path("/Users/me/project")), RUNS)


def test_guard_rejects_other_session_id():
    m = manifest_with(owned())
    with pytest.raises(OwnershipError):
        assert_owned(m, replace(owned(), session_id="sid-2"), RUNS)


def test_guard_rejects_pid_outside_process_groups():
    rows = [ProcRow(100, 1, 100, "sops-exec"), ProcRow(150, 100, 100, "sops"), ProcRow(200, 1, 200, "claude")]
    with pytest.raises(OwnershipError):
        assert_owned(manifest_with(owned()), owned(), RUNS, rows)


def test_guard_accepts_pid_descending_from_pane_group():
    rows = [ProcRow(100, 1, 100, "sops-exec"), ProcRow(150, 100, 100, "sops"), ProcRow(200, 150, 100, "claude")]
    assert_owned(manifest_with(owned()), owned(), RUNS, rows)


def test_guard_rejects_target_without_agent_pid_when_checking_tree():
    t = replace(owned(), agent_pid=None)
    with pytest.raises(OwnershipError):
        assert_owned(manifest_with(t), t, RUNS, [ProcRow(100, 1, 100, "sops-exec")])


def test_only_harness_owned_socket_dirs_are_removable(tmp_path):
    layout = Layout(tmp_path)
    (tmp_path / "runs").mkdir()
    assert socket_removable(tmp_path / "runs" / "r1" / "a.sock", layout)
    assert socket_removable(Path("/tmp/ac/x.sock"), layout)
    assert not socket_removable(Path("/tmp/cc-socks/123.sock"), layout)


def test_owned_pids_are_cwd_roots_and_their_descendants(tmp_path):
    rows = [ProcRow(10, 1, 10, "sops-exec"), ProcRow(11, 10, 10, "claude"), ProcRow(12, 11, 10, "mcp"),
            ProcRow(20, 1, 20, "user-claude")]
    run_dir = tmp_path / "r1"
    cwd_map = {11: str(run_dir / "work"), 20: "/elsewhere"}
    assert owned_pids(rows, {10, 11, 20}, cwd_map, run_dir) == {11, 12}


def run_manifest(layout: Layout, run_id: str, pgids: list[int], agent_pid: int | None = None) -> Manifest:
    t = Target(run_id=run_id, agent="claude", host="tmux", backend="none", work_dir=layout.work_dir(run_id, "claude"),
               home_dir=layout.home_dir(run_id, "claude"), session_id=None, host_ref=f"agentcomms:{run_id}-claude",
               backend_ref=None, transcript=None, agent_pid=agent_pid)
    return Manifest(run_id=run_id, pgids=pgids, targets=[t], sockets=[], backends=[])


def test_run_pids_follow_groups_and_agent_pid_but_only_inside_the_run_dir(tmp_path, monkeypatch):
    layout = Layout(tmp_path)
    run_id = "20261024-000000-abcd"
    rows = [ProcRow(100, 1, 100, "sops-exec"), ProcRow(101, 100, 100, "claude"), ProcRow(102, 101, 102, "mcp"),
            ProcRow(300, 1, 300, "detached-child"), ProcRow(301, 300, 300, "grandchild"),
            ProcRow(900, 1, 900, "users-own-claude")]
    inside = str(layout.run_dir(run_id) / "work" / "claude")
    cwd_map = {100: inside, 101: inside, 102: inside, 300: inside, 301: inside, 900: "/Users/me/project"}
    monkeypatch.setattr(procs, "cwds", lambda pids: {p: cwd_map[p] for p in pids if p in cwd_map})
    assert manifest.run_pids(layout, run_manifest(layout, run_id, [100], agent_pid=101), rows) == {100, 101, 102}
    assert manifest.run_pids(layout, run_manifest(layout, run_id, [100, 300, 900]), rows) == {100, 101, 102, 300, 301}


def spawn_in_run(layout: Layout, run_id: str, command: str) -> int:
    cwd = layout.work_dir(run_id, "claude")
    cwd.mkdir(parents=True, exist_ok=True)
    out = subprocess.run(["/bin/sh", "-c", f"{command} >/dev/null 2>&1 & echo $!"], cwd=cwd, capture_output=True,
                         text=True, check=True, start_new_session=True)
    time.sleep(0.3)
    return int(out.stdout.strip())


def kill_quietly(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)


def test_sweep_terminates_run_processes(tmp_path):
    layout = Layout(tmp_path)
    run_id = "20261024-000000-abcd"
    pid = spawn_in_run(layout, run_id, "sleep 30")
    try:
        m = run_manifest(layout, run_id, [os.getpgid(pid)])
        assert manifest.run_pids(layout, m, procs.ps_rows()) == {pid}
        assert manifest.sweep(layout, m, grace_s=5.0) == 0
        assert procs.alive(pid) is False
    finally:
        kill_quietly(pid)


def test_sweep_escalates_to_sigkill(tmp_path):
    layout = Layout(tmp_path)
    run_id = "20261024-000000-abcd"
    pid = spawn_in_run(layout, run_id, f"{sys.executable} -c 'import signal, time; "
                                       "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'")
    try:
        time.sleep(0.5)
        assert manifest.sweep(layout, run_manifest(layout, run_id, [os.getpgid(pid)]), grace_s=0.5) == 1
        time.sleep(0.3)
        assert procs.alive(pid) is False
    finally:
        kill_quietly(pid)


def test_cleanup_kills_processes_removes_sockets_and_reports_zero_left(tmp_path, monkeypatch):
    layout = Layout(tmp_path)
    run_id = "20261024-000000-abcd"
    calls = []

    def fake_tmux(layout, *args, socket="agentcomms"):
        calls.append(args if socket == "agentcomms" else (socket, *args))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(manifest, "_tmux", fake_tmux)
    sockets = tmp_path / "ac"
    sockets.mkdir()
    (sockets / f"agentcomms-{run_id}-claude").write_text("")
    (sockets / "agentcomms-20261024-000000-ffff-claude").write_text("")
    (sockets / f"{run_id}-ic").mkdir()
    monkeypatch.setattr(manifest, "SOCKET_DIR", sockets)
    monkeypatch.setattr(manifest, "CLAUDE_SOCK_DIR", tmp_path / "cc-socks")
    pid = spawn_in_run(layout, run_id, "sleep 30")
    sock = layout.run_dir(run_id) / "a.sock"
    sock.write_text("")
    m = replace(run_manifest(layout, run_id, [os.getpgid(pid)]), sockets=[sock])
    manifest.save(layout, m)
    try:
        report = manifest.cleanup(layout, run_id, grace_s=5.0)
    finally:
        kill_quietly(pid)
    assert report == ["killed tmux session 20261024-000000-abcd-claude",
                      f"killed the run's tmux server agentcomms-{run_id}-claude",
                      "terminated 1 processes (0 needed SIGKILL)", f"removed socket {sock}",
                      f"removed socket dir {sockets / f'{run_id}-ic'}", "remaining harness processes: 0"]
    assert sock.exists() is False
    assert ("kill-session", "-t", f"={run_id}-claude") in calls
    assert ("kill-server",) in calls
    assert [c for c in calls if c[-1] == "kill-server"] == [(f"agentcomms-{run_id}-claude", "kill-server"),
                                                           ("kill-server",)]
    assert sorted(p.name for p in sockets.iterdir()) == ["agentcomms-20261024-000000-ffff-claude"]
    assert manifest.cleanup(layout, run_id)[0] == "killed tmux session 20261024-000000-abcd-claude"


def test_session_owned_by_manifest_target_or_run_transcript():
    m = manifest_with(owned())
    manifest.assert_session_owned(m, "sid-1", set())
    manifest.assert_session_owned(m, "sid-new", {"sid-new"})
    with pytest.raises(OwnershipError, match="session sid-x"):
        manifest.assert_session_owned(m, "sid-x", {"sid-new", None})


def test_backend_pids_count_only_with_their_recorded_identity(tmp_path, monkeypatch):
    layout = Layout(tmp_path)
    run_id = "20261025-000000-abcd"
    rows = [ProcRow(500, 1, 500, "codex app-server"), ProcRow(501, 500, 500, "codex helper"),
            ProcRow(600, 1, 600, "users-editor"), ProcRow(601, 600, 600, "users-shell")]
    monkeypatch.setattr(procs, "cwds", lambda pids: {})
    monkeypatch.setattr(procs, "identities", lambda pids: {500: "codex-start", 600: "editor-start"})
    base = run_manifest(layout, run_id, [])
    ours = replace(base, backends=["codex-app-server:500"], identities={500: "codex-start"})
    assert manifest.run_pids(layout, ours, rows) == {500, 501}
    reused = replace(base, backends=["codex-daemon:600"], identities={600: "old-daemon-start"})
    assert manifest.run_pids(layout, reused, rows) == set()


def test_legacy_manifest_backend_entries_are_never_owned(tmp_path, monkeypatch):
    layout = Layout(tmp_path)
    run_id = "20261025-000000-abcd"
    path = layout.manifest_path(run_id)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"run_id": run_id, "pgids": [], "targets": [], "sockets": [],
                                "backends": ["codex-daemon:600"]}))
    rows = [ProcRow(600, 1, 600, "users-editor"), ProcRow(601, 600, 600, "users-shell")]
    monkeypatch.setattr(procs, "cwds", lambda pids: {})
    monkeypatch.setattr(procs, "identities", lambda pids: {600: "editor-start"})
    monkeypatch.setattr(procs, "ps_rows", lambda: rows)
    killed = []
    monkeypatch.setattr(manifest, "_signal", lambda pids, sig: killed.append(pids))
    m = manifest.load(layout, run_id)
    assert manifest.run_pids(layout, m, rows) == set()
    assert manifest.live_runs(layout) == []
    assert manifest.sweep(layout, m, 0.0) == 0
    assert killed == []


def test_tracking_replaces_restarted_backends_and_prunes_dead_entries():
    m = replace(manifest_with(owned()), backends=["codex-daemon:10", "codex-daemon:11", "deferred-sender:12"],
                identities={10: "a", 11: "b", 12: "c", 200: "agent"})
    current = {10: "a", 11: "b", 30: "n"}
    restarted = manifest.with_tracked(m, "codex-daemon", {30: "n", 11: "b"}, current, replace_kind=True)
    assert restarted.backends == ["codex-daemon:30", "codex-daemon:11"]
    assert restarted.identities == {11: "b", 30: "n", 200: "agent"}
    spawned = manifest.with_tracked(restarted, "deferred-sender", {40: "w"}, {**current, 40: "w"})
    assert spawned.backends == ["codex-daemon:30", "codex-daemon:11", "deferred-sender:40"]


def test_identities_survive_a_save_and_load(tmp_path):
    layout = Layout(tmp_path)
    m = replace(manifest_with(owned()), backends=["codex-app-server:5"], identities={5: "x", 200: "y"})
    manifest.save(layout, m)
    assert manifest.load(layout, m.run_id).identities == {5: "x", 200: "y"}


def make_unix_socket(directory, name, monkeypatch):
    import socket

    with monkeypatch.context() as ctx:
        ctx.chdir(directory)
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(name)
        sock.close()
    return directory / name


def claude_manifest(run_id, pids_and_idents, agent="claude"):
    from pathlib import Path

    from agentcomms.model import Manifest, Target

    targets = [Target(run_id, agent, "tmux", "none", Path("/w"), Path("/h"), None, f"agentcomms:{run_id}-{pid}", None,
                      None, pid) for pid in pids_and_idents]
    return Manifest(run_id, [], targets, [], [], identities=dict(pids_and_idents))


def test_only_dead_harness_claude_sockets_are_removed(tmp_path, monkeypatch):
    import os
    import subprocess

    from agentcomms import manifest, procs

    gone = subprocess.Popen(["/usr/bin/true"])
    gone.wait()
    me = os.getpid()
    real = procs.identities({me})[me]
    socks = {name: make_unix_socket(tmp_path, f"{pid}.sock", monkeypatch) for name, pid in
             {"harness-dead": gone.pid, "harness-live": me, "harness-reused": 1, "user-dead": 999991,
              "codex-dead": 999992}.items()}
    (tmp_path / "999993.sock").write_text("")
    manifests = [claude_manifest("20261028-000000-aaaa", {gone.pid: "dead-id", me: real, 1: "not-launchd"}),
                 claude_manifest("20261028-000001-bbbb", {999992: "x"}, agent="codex")]
    report = manifest.remove_stale_claude_sockets(manifests, tmp_path)
    assert {n: s.exists() for n, s in socks.items()} == {
        "harness-dead": False, "harness-live": True, "harness-reused": True, "user-dead": True, "codex-dead": True}
    assert (tmp_path / "999993.sock").exists()
    assert sorted(report) == sorted([
        f"removed stale Claude socket {socks['harness-dead']}",
        f"left Claude socket {socks['harness-reused']} (its pid now belongs to another process)"])


def test_a_pid_recorded_by_any_manifest_with_a_matching_identity_keeps_its_socket(tmp_path, monkeypatch):
    import os

    from agentcomms import manifest, procs

    me = os.getpid()
    sock = make_unix_socket(tmp_path, f"{me}.sock", monkeypatch)
    manifests = [claude_manifest("20261028-000000-aaaa", {me: "an-earlier-process"}),
                 claude_manifest("20261028-000001-bbbb", {me: procs.identities({me})[me]})]
    assert manifest.remove_stale_claude_sockets(manifests, tmp_path) == []
    assert sock.exists()


def test_run_manifests_reads_every_run_and_skips_broken_ones(tmp_path):
    from agentcomms import manifest
    from agentcomms.paths import Layout

    layout = Layout(tmp_path)
    manifest.save(layout, claude_manifest("20261028-000000-aaaa", {7: "id"}))
    (layout.runs / "20261028-000001-bbbb").mkdir()
    (layout.runs / "20261028-000001-bbbb" / "manifest.json").write_text("{")
    assert [m.run_id for m in manifest.run_manifests(layout)] == ["20261028-000000-aaaa"]


def test_guard_rejects_a_different_agent_pid():
    with pytest.raises(OwnershipError):
        assert_owned(manifest_with(owned()), replace(owned(), agent_pid=999), RUNS)


def test_guard_rejects_a_target_of_another_run():
    with pytest.raises(OwnershipError):
        assert_owned(manifest_with(owned()), replace(owned(), run_id="20261024-101500-ffff"), RUNS)
