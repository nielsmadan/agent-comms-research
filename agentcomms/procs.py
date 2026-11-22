import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from agentcomms.senders.guard import identities as identities

TOOL_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class ProcRow:
    pid: int
    ppid: int
    pgid: int
    args: str


def parse_ps(output: str) -> list[ProcRow]:
    rows = []
    for line in output.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 3 or not parts[0].isdigit():
            continue
        rows.append(ProcRow(int(parts[0]), int(parts[1]), int(parts[2]), parts[3] if len(parts) > 3 else ""))
    return rows


def ps_rows() -> list[ProcRow]:
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,pgid=,args="], capture_output=True, text=True, check=True,
                         timeout=TOOL_TIMEOUT_S)
    return parse_ps(out.stdout)


def descendants(rows: list[ProcRow], roots: set[int]) -> set[int]:
    children: dict[int, list[int]] = {}
    for r in rows:
        children.setdefault(r.ppid, []).append(r.pid)
    found = set(roots) & {r.pid for r in rows}
    frontier = list(found)
    while frontier:
        pid = frontier.pop()
        for child in children.get(pid, []):
            if child not in found:
                found.add(child)
                frontier.append(child)
    return found


def is_agent_process(args: str, binary: str, title: str | None = None) -> bool:
    return args.split(" ", 1)[0] in (binary, title)


def find_agent_pid(rows: list[ProcRow], root: int, binary: str, title: str | None = None) -> int | None:
    tree = descendants(rows, {root})
    matches = [r.pid for r in rows if r.pid in tree and is_agent_process(r.args, binary, title)]
    return min(matches) if matches else None


def vendored(rows: list[ProcRow], vendor: Path) -> set[int]:
    prefix = f"{vendor.resolve()}/"
    return {r.pid for r in rows if r.args.startswith(prefix)}


def owned_group(rows: list[ProcRow], root: int, own_pgid: int | None = None) -> int:
    row = next((r for r in rows if r.pid == root), None)
    if row is None or row.pgid in (0, 1, own_pgid if own_pgid is not None else os.getpgrp()):
        return root
    members = {r.pid for r in rows if r.pgid == row.pgid}
    return row.pgid if members <= descendants(rows, {root}) else root


def group_members(rows: list[ProcRow], pgids: set[int]) -> set[int]:
    return {r.pid for r in rows if r.pgid in pgids}


def cwds(pids: set[int]) -> dict[int, str]:
    if not pids:
        return {}
    out = subprocess.run(
        ["lsof", "-a", "-d", "cwd", "-Fpn", "-p", ",".join(str(p) for p in sorted(pids))],
        capture_output=True, text=True, timeout=TOOL_TIMEOUT_S,
    )
    result: dict[int, str] = {}
    pid = None
    for line in out.stdout.splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            result[pid] = line[1:]
    return result


SCRIPT_RUNTIMES = frozenset({"node", "bun", "deno", "python", "python3", "sh", "bash"})


def runs_vendored_program(args: str, prefix: str) -> bool:
    words = args.split()
    if not words:
        return False
    if words[0].startswith(prefix):
        return True
    return Path(words[0]).name in SCRIPT_RUNTIMES and any(w.startswith(prefix) for w in words[1:])


def runs_vendored(rows: list[ProcRow], vendor: Path) -> set[int]:
    prefix = f"{vendor.resolve()}/"
    return {r.pid for r in rows if runs_vendored_program(r.args, prefix)}


def with_provenance(rows: list[ProcRow], pids: list[int], roots: set[int], cwd_map: dict[int, str],
                    run_dir: Path, vendor: Path | None = None) -> list[int]:
    tree = descendants(rows, roots) | (runs_vendored(rows, vendor) if vendor else set())
    root = run_dir.resolve()
    return [p for p in pids if p in tree or (cwd_map.get(p) and Path(cwd_map[p]).is_relative_to(root))]


def owned_pids(rows: list[ProcRow], candidates: set[int], cwd_map: dict[int, str], run_dir: Path) -> set[int]:
    root = run_dir.resolve()
    roots = {p for p in candidates if cwd_map.get(p) and Path(cwd_map[p]).is_relative_to(root)}
    return descendants(rows, roots)


def live_group(pgid: int) -> bool:
    out = subprocess.run(["ps", "-axo", "pgid=,stat="], capture_output=True, text=True, check=True,
                         timeout=TOOL_TIMEOUT_S)
    fields = (line.split() for line in out.stdout.splitlines())
    return any(f[0] == str(pgid) and not f[1].startswith("Z") for f in fields if len(f) == 2)


def live_process(pid: int) -> bool:
    stat = state(pid)
    return bool(stat) and not stat.startswith("Z")


def state(pid: int) -> str | None:
    out = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True, timeout=TOOL_TIMEOUT_S)
    return out.stdout.strip() or None


def running(pid: int, identity: str | None) -> bool:
    stat = state(pid)
    return bool(stat) and not stat.startswith("Z") and identities({pid}).get(pid) == identity


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
