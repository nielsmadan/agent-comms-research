from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

RUNS = Path(__file__).resolve().parents[2] / "runs"
SOCKET_DIR = Path("/tmp/ac")
RUN_SOCKET = re.compile(r"\A(\d{8}-\d{6}-[0-9A-Za-z]{4})(-[a-z]+)?\.sock\Z")
RUN_SOCKET_DIR = re.compile(r"\A(\d{8}-\d{6}-[0-9A-Za-z]{4})-[a-z]+\Z")
PID_SOCKET = re.compile(r"\A(?:pi-)?(\d+)\.sock\Z")
CLAUDE_SOCK_DIRS = (Path("/tmp/cc-socks"), Path("/private/tmp/cc-socks"))


class GuardError(Exception):
    pass


def identity(lstart: str, ucomm: str) -> str:
    return hashlib.sha256(f"{lstart}\0{ucomm}".encode()).hexdigest()[:16]


def parse_identities(output: str) -> dict[int, str]:
    found = {}
    for line in output.splitlines():
        parts = line.split(None, 6)
        if len(parts) == 7 and parts[0].isdigit():
            found[int(parts[0])] = identity(" ".join(parts[1:6]), parts[6].strip())
    return found


def identities(pids) -> dict[int, str]:
    wanted = set(pids)
    if not wanted:
        return {}
    # macOS ps takes ~0.6 s for any multi-pid -p list but ~0.1 s for the whole table
    select = ["-p", str(next(iter(wanted)))] if len(wanted) == 1 else ["-ax"]
    out = subprocess.run(["ps", *select, "-o", "pid=,lstart=,ucomm="], capture_output=True, text=True,
                         env={**os.environ, "LC_ALL": "C", "TZ": "UTC"}, timeout=30)
    return {pid: ident for pid, ident in parse_identities(out.stdout).items() if pid in wanted}


def entry_pid(entry: str) -> int | None:
    _, _, pid = entry.rpartition(":")
    return int(pid) if pid.isdigit() else None


def entry_kind(entry: str) -> str:
    return entry.rpartition(":")[0]


def owned_pid(manifest: dict, pid: int, current: dict[int, str]) -> bool:
    expected = (manifest.get("identities") or {}).get(str(pid))
    return expected is not None and current.get(pid) == expected


def run_dir_for(path: Path, runs: Path) -> Path:
    resolved, root = Path(path).resolve(), runs.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise GuardError(f"{path} is not inside the harness runs dir {runs}")
    return root / resolved.relative_to(root).parts[0]


def load_manifest(run_dir: Path) -> dict:
    path = run_dir / "manifest.json"
    if not path.is_file():
        raise GuardError(f"no harness manifest at {path}")
    return json.loads(path.read_text())


def same_path(a: str | Path, b: str | Path) -> bool:
    return Path(a).resolve() == Path(b).resolve()


def check_claude_target(manifest: dict, config_dir: Path, pid: int, current: dict[int, str]) -> dict:
    matches = [t for t in manifest["targets"] if t.get("agent") == "claude" and t.get("agent_pid") == pid
               and same_path(t["home_dir"], config_dir)]
    if not matches:
        raise GuardError(f"pid {pid} with config dir {config_dir} is not a target of run {manifest['run_id']}")
    if not owned_pid(manifest, pid, current):
        raise GuardError(f"pid {pid} is not the process run {manifest['run_id']} started (not running, or reused)")
    return matches[0]


def owned_claude_target(config_dir: Path, pid: int, runs: Path | None = None) -> dict:
    manifest = load_manifest(run_dir_for(config_dir, runs or RUNS))
    return check_claude_target(manifest, config_dir, pid, identities({pid}))


def owned_claude_socket(sock: str, pid: int) -> bool:
    path = Path(sock)
    return path.name == f"{pid}.sock" and path.parent in CLAUDE_SOCK_DIRS


def live_backends(manifest: dict, kind: str, current: dict[int, str]) -> list[int]:
    pids = [entry_pid(e) for e in manifest.get("backends") or [] if entry_kind(e) == kind]
    return [p for p in pids if p and owned_pid(manifest, p, current)]


def backend_pids(manifest: dict) -> set[int]:
    return {p for p in map(entry_pid, manifest.get("backends") or []) if p}


def check_codex_home(manifest: dict, codex_home: Path, current: dict[int, str]) -> None:
    if not any(t.get("agent") == "codex" and same_path(t["home_dir"], codex_home) for t in manifest["targets"]):
        raise GuardError(f"CODEX_HOME {codex_home} is not a codex target home of run {manifest['run_id']}")
    if not live_backends(manifest, "codex-daemon", current):
        raise GuardError(f"run {manifest['run_id']} has no running harness codex daemon")


def owned_codex_home(codex_home: Path, runs: Path | None = None) -> None:
    manifest = load_manifest(run_dir_for(codex_home, runs or RUNS))
    check_codex_home(manifest, codex_home, identities(backend_pids(manifest)))


def run_socket_run_id(sock: Path) -> str:
    m = RUN_SOCKET.match(sock.name)
    if not m or not same_path(sock.parent, SOCKET_DIR):
        raise GuardError(f"{sock} is not a harness socket in {SOCKET_DIR}")
    return m.group(1)


def owned_run_socket(sock: Path, runs: Path | None = None) -> dict:
    manifest = load_manifest((runs or RUNS) / run_socket_run_id(sock))
    if not any(Path(s) == sock for s in manifest.get("sockets") or []):
        raise GuardError(f"{sock} is not a socket of run {manifest['run_id']}")
    return manifest


def check_codex_socket(manifest: dict, sock: Path, current: dict[int, str]) -> None:
    if not any(t.get("agent") == "codex" and t.get("backend_ref") == str(sock) for t in manifest["targets"]):
        raise GuardError(f"{sock} is not the app server of a codex target of run {manifest['run_id']}")
    if not live_backends(manifest, "codex-app-server", current):
        raise GuardError(f"run {manifest['run_id']} has no running harness codex app server")


def owned_codex_socket(sock: Path, runs: Path | None = None) -> None:
    manifest = owned_run_socket(sock, runs)
    check_codex_socket(manifest, sock, identities(backend_pids(manifest)))


def socket_dir_run_id(sock: Path) -> str:
    text = str(sock)
    rel = Path(text.removeprefix("/private")) if text.startswith("/private/tmp/") else Path(text)
    if not rel.is_relative_to(SOCKET_DIR) or len(rel.relative_to(SOCKET_DIR).parts) < 2:
        raise GuardError(f"{sock} is not inside a harness run socket dir under {SOCKET_DIR}")
    m = RUN_SOCKET_DIR.match(rel.relative_to(SOCKET_DIR).parts[0])
    if not m:
        raise GuardError(f"{sock} is not inside a harness run socket dir under {SOCKET_DIR}")
    return m.group(1)


def check_agent_socket(manifest: dict, sock: Path, agent: str, current: dict[int, str]) -> int:
    if not any(Path(s) == sock for s in manifest.get("sockets") or []):
        raise GuardError(f"{sock} is not a socket of run {manifest['run_id']}")
    m = PID_SOCKET.match(sock.name)
    pid = int(m.group(1)) if m else None
    if pid is None or not any(t.get("agent") == agent and t.get("agent_pid") == pid for t in manifest["targets"]):
        raise GuardError(f"{sock} does not belong to a {agent} target of run {manifest['run_id']}")
    if not owned_pid(manifest, pid, current):
        raise GuardError(f"pid {pid} is not the process run {manifest['run_id']} started (not running, or reused)")
    return pid


def owned_agent_socket(sock: Path, agent: str, runs: Path | None = None) -> int:
    manifest = load_manifest((runs or RUNS) / socket_dir_run_id(sock))
    m = PID_SOCKET.match(sock.name)
    return check_agent_socket(manifest, sock, agent, identities({int(m.group(1))}) if m else {})
