import calendar
import contextlib
import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from agentcomms import isolation, manifest, procs, profiles
from agentcomms.hosts.tmux import env_wrapped

BG_ID = re.compile(r"claude attach ([A-Za-z0-9_-]+)")
COLD_START_ENV = {"CLAUDE_CODE_DAEMON_COLD_START": "transient"}
BG_SETTINGS = {"disableAgentView": False, "daemonColdStart": "transient"}
DISABLED = "background agents disabled"
PROBE_TIMEOUT_S = 90.0


def daemon_root(uid: int | None = None) -> Path:
    return Path("/tmp") / f"cc-daemon-{os.getuid() if uid is None else uid}"


def daemon_sock_dir(config_dir: Path, uid: int | None = None) -> Path:
    return daemon_root(uid) / hashlib.sha256(str(config_dir).encode()).hexdigest()[:8]


def shared_daemon_problem(config_dir: Path, user_home: Path, runs_root: Path) -> str | None:
    if not config_dir.resolve().is_relative_to(runs_root.resolve()):
        return f"CLAUDE_CONFIG_DIR {config_dir} is not under {runs_root}"
    if daemon_sock_dir(config_dir) == daemon_sock_dir(user_home / ".claude"):
        return "bg daemon socket dir would equal the user's"
    return None


def bg_argv(claude: str, model: str, extra: tuple[str, ...] = ()) -> list[str]:
    return [claude, "--bg", "--model", model, "--permission-mode", "bypassPermissions", *extra]


def attach_argv(claude: str, bg_id: str) -> list[str]:
    return [claude, "attach", bg_id]


def parse_bg_id(output: str) -> str | None:
    m = BG_ID.search(output)
    return m.group(1) if m else None


def roster(config_dir: Path) -> dict:
    path = config_dir / "daemon" / "roster.json"
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def daemon_pids(config_dir: Path) -> list[int]:
    data = roster(config_dir)
    workers = data.get("workers") or {}
    worker_pids = [w.get("pid") for w in workers.values() if isinstance(w, dict)]
    return [p for p in [data.get("supervisorPid"), *worker_pids] if isinstance(p, int)]


def dir_mtimes(path: Path) -> dict[str, float]:
    entries = [path, *sorted(path.iterdir())] if path.is_dir() else []
    return {str(p): p.stat().st_mtime for p in entries}


def listing(path: Path) -> set[str]:
    return {p.name for p in path.iterdir()} if path.is_dir() else set()


@dataclass(frozen=True)
class ProbeState:
    user_daemon: dict[str, float]
    sock_dirs: set[str]


def probe_verdict(output: str, before: ProbeState, after: ProbeState, expected: Path) -> tuple[str, str]:
    if before.user_daemon != after.user_daemon:
        changed = sorted(k for k in {*before.user_daemon, *after.user_daemon}
                         if before.user_daemon.get(k) != after.user_daemon.get(k))
        return "unusable", f"the user's ~/.claude/daemon changed: {', '.join(changed)}"
    new = after.sock_dirs - before.sock_dirs
    if new - {expected.name}:
        return "unusable", f"service socket dir(s) {', '.join(sorted(new))} differ from {expected}"
    if expected.name in new:
        return "started", f"service socket dir {expected} (per isolated config dir)"
    if DISABLED in output:
        return "untested", ("still disabled with disableAgentView=false in the isolated settings: the user's "
                            "disableAgentView leaks through CLAUDE_CONFIG_DIR")
    return "failed", output.strip()[-300:]


def owned_daemon_pids(config_dir: Path, started_after: float) -> list[int]:
    pids = [p for p in daemon_pids(config_dir) if procs.alive(p)]
    starts = start_times(pids)
    return [p for p in pids if starts.get(p, 0.0) >= started_after]


def start_times(pids: list[int]) -> dict[int, float]:
    if not pids:
        return {}
    out = subprocess.run(["ps", "-o", "pid=,lstart=", "-p", ",".join(map(str, pids))], capture_output=True, text=True,
                         env={**os.environ, "LC_ALL": "C", "TZ": "UTC"})
    starts = {}
    for line in out.stdout.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            starts[int(parts[0])] = parse_utc_lstart(parts[1])
    return starts


def parse_utc_lstart(text: str) -> float:
    return float(calendar.timegm(time.strptime(text.strip(), "%a %b %d %H:%M:%S %Y")))


def stop_pids(pids: list[int], grace_s: float = 5.0) -> None:
    manifest.terminate_same(set(pids), grace_s)


def probe(engine) -> list[str]:
    root = daemon_root()
    if root.exists():
        return [f"refused: {root} already exists; the probe needs a machine with no Claude background service"]
    user_home = Path(engine.user_home)
    before = ProbeState(dir_mtimes(user_home / ".claude" / "daemon"), listing(root))
    m = engine.new_run()
    binary = engine.resolve("claude")
    work_dir = engine.layout.work_dir(m.run_id, "claude")
    home = engine.layout.home_dir(m.run_id, "claude").resolve()
    model, effort = profiles.MODELS["claude"]
    iso = isolation.build_home("claude", home, work_dir, engine.layout.runs, binary.version, model, effort, "auto",
                               engine.environ, time.time())
    problem = shared_daemon_problem(home, user_home, engine.layout.runs)
    if problem:
        return [f"refused: {problem}"]
    settings = home / "settings.json"
    settings.write_text(json.dumps({**json.loads(settings.read_text()), **BG_SETTINGS}, indent=2))
    run_dir = engine.layout.run_dir(m.run_id)
    log_path = run_dir / "bg-probe.log"
    argv = profiles.launch_argv(bg_argv(str(binary.path), model))
    started = time.time() - 1.0
    with open(log_path, "wb") as log:
        proc = subprocess.Popen(env_wrapped(argv, iso.env | COLD_START_ENV), cwd=work_dir.resolve(),
                                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    report: list[str] = []
    output = ""
    try:
        m = engine.add_pgid(m, proc.pid)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(PROBE_TIMEOUT_S)
        time.sleep(2.0)
        output = log_path.read_text(errors="replace")
        after = ProbeState(dir_mtimes(user_home / ".claude" / "daemon"), listing(root))
        expected = daemon_sock_dir(home)
        verdict, detail = probe_verdict(output, before, after, expected)
        report = [f"run_id: {m.run_id}", f"verdict: {verdict}: {detail}", f"bg id: {parse_bg_id(output)}",
                  f"exit: {proc.returncode}"]
    finally:
        owned = owned_daemon_pids(home, started)
        if owned:
            stop_pids(owned)
            report.append(f"stopped harness-spawned service pids {owned}")
        report += manifest.cleanup(engine.layout, m.run_id)
        (run_dir / "bg-probe.txt").write_text("\n".join([*report, "--- output ---", output]))
    return report
