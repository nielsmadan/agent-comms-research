import contextlib
import hashlib
import json
import os
import shutil
import signal
import sqlite3
import stat
import subprocess
import time
from dataclasses import asdict, replace
from pathlib import Path

from agentcomms import backends, isolation, procs
from agentcomms.hosts.errors import HostError
from agentcomms.hosts.tmux import harness_socket, socket_args, split_ref
from agentcomms.model import Manifest, Target
from agentcomms.paths import SOCKET_DIR, TMUX_SOCKET, Layout


class OwnershipError(Exception):
    pass


class LiveRunError(Exception):
    pass


def target_to_dict(t: Target) -> dict:
    d = asdict(t)
    for key in ("work_dir", "home_dir", "transcript"):
        d[key] = str(d[key]) if d[key] is not None else None
    return d


def target_from_dict(d: dict) -> Target:
    return Target(
        run_id=d["run_id"], agent=d["agent"], host=d["host"], backend=d["backend"],
        work_dir=Path(d["work_dir"]), home_dir=Path(d["home_dir"]), session_id=d.get("session_id"),
        host_ref=d["host_ref"], backend_ref=d.get("backend_ref"),
        transcript=Path(d["transcript"]) if d.get("transcript") else None, agent_pid=d.get("agent_pid"),
    )


def manifest_to_dict(m: Manifest) -> dict:
    return {
        "run_id": m.run_id, "pgids": list(m.pgids), "targets": [target_to_dict(t) for t in m.targets],
        "sockets": [str(s) for s in m.sockets],
        "backends": list(m.backends), "identities": {str(pid): ident for pid, ident in m.identities.items()},
    }


def manifest_from_dict(d: dict) -> Manifest:
    return Manifest(
        run_id=d["run_id"], pgids=list(d["pgids"]), targets=[target_from_dict(t) for t in d["targets"]],
        sockets=[Path(s) for s in d["sockets"]], backends=list(d["backends"]),
        identities={int(pid): ident for pid, ident in (d.get("identities") or {}).items()},
    )


def save(layout: Layout, m: Manifest) -> Path:
    path = layout.manifest_path(m.run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest_to_dict(m), indent=2) + "\n")
    os.replace(tmp, path)
    return path


def load(layout: Layout, run_id: str) -> Manifest | None:
    path = layout.manifest_path(run_id)
    return manifest_from_dict(json.loads(path.read_text())) if path.exists() else None


def with_target(m: Manifest, target: Target) -> Manifest:
    others = [t for t in m.targets if t.host_ref != target.host_ref]
    return replace(m, targets=[*others, target])


def _under(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def is_owned(m: Manifest, target: Target, runs_root: Path) -> bool:
    if target.run_id != m.run_id or not _under(target.work_dir, runs_root / m.run_id):
        return False
    for t in m.targets:
        same = (t.agent, t.host, t.host_ref, t.work_dir.resolve()) == (
            target.agent, target.host, target.host_ref, target.work_dir.resolve())
        if not same:
            continue
        if t.session_id and target.session_id and t.session_id != target.session_id:
            return False
        return not (t.agent_pid and target.agent_pid and t.agent_pid != target.agent_pid)
    return False


def pid_in_groups(rows: list[procs.ProcRow], pid: int, pgids: list[int]) -> bool:
    return pid in procs.descendants(rows, procs.group_members(rows, set(pgids)))


def assert_owned(m: Manifest, target: Target, runs_root: Path, rows: list[procs.ProcRow] | None = None) -> None:
    if not is_owned(m, target, runs_root):
        raise OwnershipError(f"target {target.host_ref} is not owned by run {m.run_id}")
    if rows is not None:
        if not target.agent_pid:
            raise OwnershipError(f"target {target.host_ref} has no recorded agent pid; cannot verify its process tree")
        if not pid_in_groups(rows, target.agent_pid, m.pgids):
            raise OwnershipError(f"pid {target.agent_pid} is not in run {m.run_id}'s process groups")


def assert_session_owned(m: Manifest, session_id: str, run_transcript_ids: set[str | None]) -> None:
    if session_id in {t.session_id for t in m.targets} or session_id in run_transcript_ids:
        return
    raise OwnershipError(f"session {session_id} is neither a manifest target nor a transcript of run {m.run_id}")


def owned_target(m: Manifest, runs_root: Path, agent: str | None = None, host_ref: str | None = None) -> Target:
    matches = [t for t in m.targets if (agent is None or t.agent == agent)
               and (host_ref is None or t.host_ref == host_ref)]
    if len(matches) != 1:
        raise OwnershipError(f"expected exactly one manifest target, found {len(matches)}")
    assert_owned(m, matches[0], runs_root)
    return matches[0]


def tracked_pids(m: Manifest) -> set[int]:
    return {p for p in map(backends.entry_pid, m.backends) if p}


def owned_tracked(m: Manifest, current: dict[int, str]) -> set[int]:
    return {p for p in tracked_pids(m) if p in m.identities and current.get(p) == m.identities[p]}


def with_identities(m: Manifest, idents: dict[int, str]) -> Manifest:
    return replace(m, identities={**m.identities, **idents})


def with_tracked(m: Manifest, kind: str, idents: dict[int, str], current: dict[int, str],
                 replace_kind: bool = False) -> Manifest:
    live = owned_tracked(m, current)
    kept = [e for e in m.backends if backends.entry_pid(e) in live
            and not (replace_kind and backends.entry_kind(e) == kind)]
    added = [backends.backend_entry(kind, p) for p in idents]
    entries = list(dict.fromkeys([*kept, *added]))
    keep_ids = {backends.entry_pid(e) for e in entries} | {t.agent_pid for t in m.targets if t.agent_pid}
    merged = {p: i for p, i in {**m.identities, **idents}.items() if p in keep_ids}
    return replace(m, backends=entries, identities=merged)


def run_pids(layout: Layout, m: Manifest, rows: list[procs.ProcRow]) -> set[int]:
    candidates = procs.descendants(rows, procs.group_members(rows, set(m.pgids)) | set(m.pgids))
    candidates |= procs.vendored(rows, layout.root / "vendor")
    targets = {t.agent_pid for t in m.targets if t.agent_pid}
    candidates |= procs.descendants(rows, targets)
    cwd_map = procs.cwds(candidates)
    tracked = owned_tracked(m, procs.identities(tracked_pids(m)))
    return procs.owned_pids(rows, candidates, cwd_map, layout.run_dir(m.run_id)) | procs.descendants(rows, tracked)


def live_runs(layout: Layout, exclude: frozenset[str] = frozenset()) -> list[str]:
    if not layout.runs.exists():
        return []
    rows = procs.ps_rows()
    live = []
    for path in sorted(layout.runs.glob("*/manifest.json")):
        m = manifest_from_dict(json.loads(path.read_text()))
        if m.run_id not in exclude and run_pids(layout, m, rows):
            live.append(m.run_id)
    return live


def refuse_if_live(layout: Layout, exclude: frozenset[str] = frozenset()) -> None:
    live = live_runs(layout, exclude)
    if live:
        raise LiveRunError(f"runs with live processes: {', '.join(live)}; run `agentcomms cleanup <run_id>` first")


def _tmux(layout: Layout, *args: str, socket: str = TMUX_SOCKET) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *socket_args(socket), "-f", str(layout.tmux_conf), *args],
                          capture_output=True, text=True, timeout=30)


def run_socket_prefix(run_id: str) -> str:
    return f"{TMUX_SOCKET}-{run_id}-"


def run_tmux_sockets(run_id: str, socket_dir: Path | None = None) -> list[str]:
    prefix = run_socket_prefix(run_id)
    return sorted(p.name for p in (socket_dir or SOCKET_DIR).glob(f"{prefix}*")
                  if not p.is_dir() and harness_socket(p.name))


def target_sessions(m: Manifest) -> list[tuple[str, str]]:
    refs = [t.host_ref for t in m.targets if t.host == "tmux"]
    return [split_ref(r) for r in refs if valid_ref(r)]


def valid_ref(host_ref: str) -> bool:
    try:
        split_ref(host_ref)
    except HostError:
        return False
    return True


def run_panes(listing: str, run_dir: Path) -> set[str]:
    root = run_dir.resolve()
    rows = (line.split("\t", 1) for line in listing.splitlines())
    return {name for name, path in (r for r in rows if len(r) == 2) if path and Path(path).is_relative_to(root)}


def untracked_run_sessions(layout: Layout, m: Manifest) -> list[str]:
    out = _tmux(layout, "list-panes", "-a", "-F", "#{session_name}\t#{pane_current_path}")
    if out.returncode != 0:
        return []
    tracked = {name for socket, name in target_sessions(m) if socket == TMUX_SOCKET}
    return sorted(run_panes(out.stdout, layout.run_dir(m.run_id)) - tracked)


def multiplexer_state_dir(host_ref: str) -> Path:
    return Path(host_ref.partition(":")[2].rpartition(":")[0])


def stop_multiplexer_sessions(m: Manifest) -> tuple[list[str], set[Path]]:
    from agentcomms.hosts import make_host
    report, survived = [], set()
    for t in (t for t in m.targets if t.host in ("zmx", "zellij")):
        name = t.host_ref.rsplit(":", 1)[-1]
        try:
            make_host(t.host).stop(t.host_ref)
        except Exception as e:  # any failure leaves the server possibly running; keep its state dir findable
            report.append(f"note: stopping {t.host} session {name} failed: {type(e).__name__}: {e}")
            survived.add(multiplexer_state_dir(t.host_ref))
            continue
        report.append(f"stopped {t.host} session {name}")
    return report, survived


def bridge_daemons(m: Manifest, current: dict[int, str]) -> set[int]:
    return {p for p in owned_tracked(m, current)
            if any(backends.entry_pid(e) == p and backends.entry_kind(e) == "bridge-daemon" for e in m.backends)}


def stop_bridge_daemons(m: Manifest, grace_s: float) -> list[str]:
    pids = {p for p in bridge_daemons(m, procs.identities(tracked_pids(m))) if procs.alive(p)}
    if not pids:
        return []
    terminate_same(pids, grace_s)
    return [f"stopped bridge daemon pid {p}" for p in sorted(pids)]


def same_survivors(pids: set[int], before: dict[int, str], now: dict[int, str]) -> set[int]:
    return {p for p in pids if p in before and now.get(p) == before[p]}


def terminate_same(pids: set[int], grace_s: float) -> int:
    before = procs.identities(pids)
    _signal(pids, signal.SIGTERM)
    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline and any(procs.alive(p) for p in pids):
        time.sleep(0.2)
    alive = {p for p in pids if procs.alive(p)}
    survivors = same_survivors(alive, before, procs.identities(alive)) if alive else set()
    _signal(survivors, signal.SIGKILL)
    return len(survivors)


def _signal(pids: set[int], sig: int) -> None:
    for pid in pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, sig)


def run_owned_home(layout: Layout, m: Manifest, home: Path) -> bool:
    return _under(home, layout.run_dir(m.run_id))


def harness_daemon_homes(layout: Layout, m: Manifest) -> set[Path]:
    return {t.home_dir for t in m.targets
            if t.agent == "codex" and t.backend == "codex-daemon" and run_owned_home(layout, m, t.home_dir)}


def derived_codex_sockets(layout: Layout, m: Manifest) -> set[str]:
    listen = SOCKET_DIR / f"{m.run_id}.sock"
    links = {hashlib.sha256(str(s).encode()).hexdigest() for s in m.sockets if s == listen}
    homes = {backends.codex_daemon_socket(h).name for h in harness_daemon_homes(layout, m)}
    return links | homes


def socket_removable(sock: Path, layout: Layout, derived: frozenset[str] = frozenset()) -> bool:
    if sock.parent == backends.CODEX_DAEMON_SOCK_DIR:
        return sock.name in derived
    parent = sock.parent.resolve()
    return any(parent.is_relative_to(root.resolve()) for root in (SOCKET_DIR, layout.runs))


CLAUDE_SOCK_DIR = Path("/tmp/cc-socks")


def harness_claude_identities(manifests: list[Manifest]) -> dict[int, set[str]]:
    recorded: dict[int, set[str]] = {}
    for m in manifests:
        for t in m.targets:
            if t.agent == "claude" and t.agent_pid and t.agent_pid in m.identities:
                recorded.setdefault(t.agent_pid, set()).add(m.identities[t.agent_pid])
    return recorded


def is_socket(path: Path) -> bool:
    try:
        return stat.S_ISSOCK(path.lstat().st_mode)
    except OSError:
        return False


def claude_socket_verdicts(manifests: list[Manifest], current: dict[int, str],
                           sock_dir: Path | None = None) -> dict[Path, str]:
    sock_dir = sock_dir or CLAUDE_SOCK_DIR
    verdicts = {}
    for pid, idents in sorted(harness_claude_identities(manifests).items()):
        sock = sock_dir / f"{pid}.sock"
        if not is_socket(sock):
            continue
        if pid not in current:
            verdicts[sock] = "stale"
        elif current[pid] in idents:
            verdicts[sock] = "live"
        else:
            verdicts[sock] = "reused"
    return verdicts


def run_manifests(layout: Layout) -> list[Manifest]:
    found = []
    for path in sorted(layout.runs.glob("*/manifest.json")):
        with contextlib.suppress(OSError, ValueError, KeyError):
            found.append(manifest_from_dict(json.loads(path.read_text())))
    return found


def remove_stale_claude_sockets(manifests: list[Manifest], sock_dir: Path | None = None) -> list[str]:
    pids = set(harness_claude_identities(manifests))
    verdicts = claude_socket_verdicts(manifests, procs.identities(pids), sock_dir)
    report = []
    for sock, verdict in verdicts.items():
        if verdict == "stale":
            sock.unlink()
            report.append(f"removed stale Claude socket {sock}")
        elif verdict == "reused":
            report.append(f"left Claude socket {sock} (its pid now belongs to another process)")
    return report


def release_iterm_sessions(refs: list[str]) -> list[str]:
    from agentcomms.hosts import iterm2
    try:
        closed, stolen = iterm2.release_sessions_sync([iterm2.session_id(r) for r in refs])
    except Exception as e:  # the API may be unreachable; the processes are swept regardless
        return [f"note: closing iTerm2 sessions failed: {type(e).__name__}: {e}"]
    return [f"closed iTerm2 session {sid}" for sid in closed] + (["note: focus_stolen=yes while closing iTerm2 tabs"]
                                                                if stolen else [])


def close_iterm_holder() -> list[str]:
    from agentcomms.hosts import iterm2
    try:
        return iterm2.close_holder_sync()
    except Exception as e:  # the API may be unreachable
        return [f"note: closing the iTerm2 holder failed: {type(e).__name__}: {e}"]


def stop_registered_services(layout: Layout, m: Manifest) -> list[str]:
    report = []
    for t in m.targets:
        if t.agent != "opencode" or not run_owned_home(layout, m, t.home_dir):
            continue
        pid = backends.service_pid_in_run(t.home_dir / "state" / "opencode" / "service.json", layout.run_dir(m.run_id))
        if pid:
            backends.stop_group(pid)
            report.append(f"stopped isolated opencode service pid {pid} (registered in the run, cwd inside it)")
    return report


def run_socket_dirs(run_id: str, socket_dir: Path | None = None) -> list[Path]:
    return sorted(p for p in (socket_dir or SOCKET_DIR).glob(f"{run_id}-*") if p.is_dir() and not p.is_symlink())


def run_links(run_id: str, run_dir: Path, socket_dir: Path | None = None) -> list[Path]:
    root = run_dir.resolve()
    return sorted(p for p in (socket_dir or SOCKET_DIR).glob(f"{run_id}-*")
                  if p.is_symlink() and p.resolve().is_relative_to(root))


def remove_run_socket_dirs(run_id: str, socket_dir: Path | None = None, run_dir: Path | None = None,
                           keep: frozenset[Path] = frozenset()) -> list[str]:
    removed = []
    kept = {p.resolve() for p in keep}
    for path in run_socket_dirs(run_id, socket_dir):
        if path.resolve() in kept:
            removed.append(f"left socket dir {path} (its multiplexer session did not stop)")
            continue
        shutil.rmtree(path, ignore_errors=True)
        removed.append(f"removed socket dir {path}")
    for path in run_links(run_id, run_dir, socket_dir) if run_dir else []:
        path.unlink()
        removed.append(f"removed link {path}")
    return removed


def sweep(layout: Layout, m: Manifest, grace_s: float) -> int:
    pids = {p for p in run_pids(layout, m, procs.ps_rows()) if procs.alive(p)}
    return terminate_same(pids, grace_s) if pids else 0


def remaining_pids(layout: Layout, run_id: str) -> set[int]:
    m = load(layout, run_id)
    return run_pids(layout, m, procs.ps_rows()) if m else set()


def stop_idle_server(layout: Layout) -> bool:
    sessions = _tmux(layout, "list-sessions", "-F", "#{session_name}")
    if sessions.returncode == 0 and not sessions.stdout.strip():
        _tmux(layout, "kill-server")
        return True
    return False


def cleanup(layout: Layout, run_id: str, grace_s: float = 5.0, kill_server: bool = True) -> list[str]:
    m = load(layout, run_id)
    if m is None:
        return [f"no manifest for {run_id}"]
    report = stop_bridge_daemons(m, grace_s)
    for socket, name in target_sessions(m):
        if _tmux(layout, "kill-session", "-t", f"={name}", socket=socket).returncode == 0:
            report.append(f"killed tmux session {name}" + ("" if socket == TMUX_SOCKET else f" on {socket}"))
    for name in untracked_run_sessions(layout, m):
        if _tmux(layout, "kill-session", "-t", f"={name}").returncode == 0:
            report.append(f"killed untracked tmux session {name} (its pane works in the run)")
    stopped, unstopped = stop_multiplexer_sessions(m)
    report += stopped
    for socket in run_tmux_sockets(m.run_id):
        if _tmux(layout, "kill-server", socket=socket).returncode == 0:
            report.append(f"killed the run's tmux server {socket}")
        with contextlib.suppress(FileNotFoundError):
            (SOCKET_DIR / socket).unlink()
    iterm_refs = [t.host_ref for t in m.targets if t.host == "iterm2"]
    if iterm_refs:
        report += release_iterm_sessions(iterm_refs)
    total, sigkilled = 0, 0
    for _ in range(3):
        before = len(run_pids(layout, m, procs.ps_rows()))
        if not before:
            break
        total += before
        sigkilled += sweep(layout, m, grace_s)
    if total:
        report.append(f"terminated {total} processes ({sigkilled} needed SIGKILL)")
    derived = frozenset(derived_codex_sockets(layout, m))
    codex_targets = [backends.CODEX_DAEMON_SOCK_DIR / name for name in sorted(derived)]
    for sock in [*m.sockets, *codex_targets]:
        if not (sock.exists() or sock.is_symlink()):
            continue
        if socket_removable(sock, layout, derived):
            sock.unlink()
            report.append(f"removed socket {sock}")
        else:
            report.append(f"left socket {sock} (outside harness-owned dirs)")
    report += remove_stale_claude_sockets([m])
    report += stop_registered_services(layout, m)
    report += remove_run_socket_dirs(m.run_id, run_dir=layout.run_dir(m.run_id), keep=frozenset(unstopped))
    if kill_server:
        stop_idle_server(layout)
    remaining = run_pids(layout, m, procs.ps_rows())
    if not remaining:
        report += purge_run_credentials(layout, m)
        report += purge_env_snapshots(layout, m)
    report.append(f"remaining harness processes: {len(remaining)}")
    return report


def env_snapshots(layout: Layout, m: Manifest) -> list[Path]:
    homes = {t.home_dir for t in m.targets if t.agent == "codex" and _under(t.home_dir, layout.run_dir(m.run_id))}
    return sorted(p for h in homes for p in (h / "shell_snapshots").glob("*.sh") if p.is_file())


def purge_env_snapshots(layout: Layout, m: Manifest) -> list[str]:
    files = env_snapshots(layout, m)
    for path in files:
        path.unlink()
    return [f"removed {len(files)} Codex shell snapshots (exported env)"] if files else []


def purge_run_credentials(layout: Layout, m: Manifest) -> list[str]:
    report = []
    for t in m.targets:
        for db in isolation.credential_dbs(t.agent, t.home_dir):
            if not _under(db, layout.run_dir(m.run_id)):
                continue
            where = db.resolve().relative_to(layout.root.resolve())
            try:
                removed = isolation.purge_credentials(db)
            except (sqlite3.Error, OSError) as e:
                report.append(f"note: credential purge failed for {where}: {type(e).__name__}: {e}")
                continue
            if removed:
                report.append(f"removed {removed} credential rows from {where}")
    return report
