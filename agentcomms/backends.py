import contextlib
import hashlib
import json
import os
import signal
import socket
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from agentcomms import isolation, procs, sandbox
from agentcomms.hosts.tmux import env_wrapped, private_env_argv, write_private
from agentcomms.model import Backend
from agentcomms.paths import SOCKET_DIR
from agentcomms.senders import guard
from agentcomms.senders.guard import entry_kind as entry_kind
from agentcomms.senders.guard import entry_pid as entry_pid

CODEX_DAEMON_SOCK_DIR = Path(f"/private/tmp/codex-daemon-{os.getuid()}")
CODEX_KINDS = frozenset({"codex-daemon", "codex-app-server"})
OPENCODE_KINDS = frozenset({"opencode-server", "opencode-service"})
OPENCODE_DIRS = ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "OPENCODE_TEST_HOME", "TMPDIR")
OPENCODE_DEFAULT_SERVICE_PORT = 0xC0DE
LOOPBACK = "127.0.0.1"
USER_HOME = Path.home()
SPEC_NAME = "backend.json"
PID_NAME = "backend.pid"


class BackendError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackendSpec:
    kind: Backend
    argv: list[str]
    env: dict[str, str]
    cwd: str
    socket: str | None
    log: str
    sandbox: dict[str, str] | None = None
    user_config: bool = False


def spec_path(run_dir: Path) -> Path:
    return run_dir / SPEC_NAME


def pid_path(run_dir: Path) -> Path:
    return run_dir / PID_NAME


def current_pid(run_dir: Path) -> int | None:
    path = pid_path(run_dir)
    return int(path.read_text().strip()) if path.exists() else None


def save_spec(run_dir: Path, spec: BackendSpec) -> None:
    write_private(spec_path(run_dir), json.dumps(asdict(spec), indent=2) + "\n")


def load_spec(run_dir: Path) -> BackendSpec | None:
    path = spec_path(run_dir)
    return BackendSpec(**json.loads(path.read_text())) if path.exists() else None


def codex_daemon_socket(codex_home: Path) -> Path:
    control = codex_home.resolve() / "app-server-control" / "app-server-control.sock"
    return CODEX_DAEMON_SOCK_DIR / hashlib.sha256(str(control).encode()).hexdigest()


def codex_daemon_pid_file(codex_home: Path) -> Path:
    return codex_home / "app-server-daemon" / "daemon.pid"


def parse_daemon_pid(text: str) -> int | None:
    try:
        return int(json.loads(text)["pid"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def daemon_side_pids(codex_home: Path) -> list[int]:
    updater = codex_home / "app-server-daemon" / "daemon-updater.pid"
    pid = parse_daemon_pid(updater.read_text()) if updater.exists() else None
    return [pid] if pid and procs.alive(pid) else []


def isolated_daemon_problem(codex_home: Path, user_home: Path, runs_root: Path) -> str | None:
    home = codex_home.resolve()
    if not home.is_relative_to(runs_root.resolve()):
        return f"CODEX_HOME {home} is not under {runs_root}"
    ours, users = codex_daemon_socket(home), codex_daemon_socket(user_home / ".codex")
    if ours == users:
        return f"isolated daemon socket {ours} equals the user's"
    if not codex_daemon_pid_file(home).resolve().is_relative_to(home):
        return "daemon pid file resolves outside the isolated CODEX_HOME"
    return None


def opencode_service_config(env: dict[str, str]) -> Path:
    return Path(env["XDG_CONFIG_HOME"]) / "opencode" / "service.json"


def opencode_service_registration(env: dict[str, str]) -> Path:
    return Path(env["XDG_STATE_HOME"]) / "opencode" / "service.json"


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def flag_value(argv: list[str], flag: str) -> str | None:
    return argv[argv.index(flag) + 1] if flag in argv[:-1] else None


def opencode_args(argv: list[str]) -> list[str]:
    i = next((i for i, a in enumerate(argv) if Path(a).name == "opencode"), None)
    return argv[i + 1:] if i is not None else []


def opencode_url(spec_argv: list[str], env: dict[str, str]) -> str | None:
    if opencode_args(spec_argv)[:1] == ["service"]:
        port = read_json(opencode_service_config(env)).get("port")
    else:
        port = flag_value(spec_argv, "--port")
    return f"http://{LOOPBACK}:{port}" if port else None


USER_CONFIG_DIRS = ("XDG_CONFIG_HOME", "OPENCODE_TEST_HOME")


def opencode_spec_problem(spec: BackendSpec, run_dir: Path) -> str | None:
    home = (run_dir / "home").resolve()
    if spec.user_config and spec.kind != "opencode-server":
        return f"{spec.kind} never runs with the user's config (it would attach to the user's service)"
    if spec.user_config and any(k in spec.env for k in USER_CONFIG_DIRS):
        return f"user-config opencode-server must use the user's config dir, not {USER_CONFIG_DIRS}"
    for key in (k for k in OPENCODE_DIRS if not (spec.user_config and k in USER_CONFIG_DIRS)):
        value = spec.env.get(key)
        if not value or not Path(value).resolve().is_relative_to(home):
            return f"{spec.kind} backend env {key}={value} is not under {run_dir / 'home'}"
    args = opencode_args(spec.argv)
    if spec.kind == "opencode-server":
        if args[:1] != ["serve"] or flag_value(args, "--hostname") != LOOPBACK:
            return f"opencode-server must be `serve --hostname {LOOPBACK}`, got {args}"
        if flag_value(args, "--port") == str(OPENCODE_DEFAULT_SERVICE_PORT):
            return f"opencode-server must not take the user's service port {OPENCODE_DEFAULT_SERVICE_PORT}"
        return None
    if args != ["service", "start"]:
        return f"opencode-service must be `service start`, got {args}"
    config = read_json(opencode_service_config(spec.env))
    if config.get("hostname") != LOOPBACK or config.get("port") in (None, OPENCODE_DEFAULT_SERVICE_PORT):
        return f"isolated service config {opencode_service_config(spec.env)} needs {LOOPBACK} and a non-default port"
    for path in (opencode_service_config(spec.env), opencode_service_registration(spec.env)):
        if not path.resolve().is_relative_to(home):
            return f"service state path {path} is not under {run_dir / 'home'}"
    return None


def spec_problem(spec: BackendSpec, run_dir: Path, user_home: Path) -> str | None:
    if spec.kind in OPENCODE_KINDS:
        return opencode_spec_problem(spec, run_dir)
    if spec.kind not in CODEX_KINDS:
        return f"no isolation check for backend kind {spec.kind}"
    home = spec.env.get("CODEX_HOME")
    if not home:
        return f"{spec.kind} backend env has no CODEX_HOME"
    if spec.user_config:
        return user_config_codex_problem(spec, run_dir, Path(home), user_home)
    if not Path(home).resolve().is_relative_to((run_dir / "home").resolve()):
        return f"CODEX_HOME {home} is not under {run_dir / 'home'}"
    return isolated_daemon_problem(Path(home), user_home, run_dir.parent)


def user_config_codex_problem(spec: BackendSpec, run_dir: Path, home: Path, user_home: Path) -> str | None:
    if spec.kind != "codex-app-server":
        return f"{spec.kind} never runs with the user's CODEX_HOME (it would be the user's own daemon)"
    if home.resolve() != (user_home / ".codex").resolve():
        return f"user-config CODEX_HOME must be the user's ~/.codex, got {home}"
    listen = flag_value(spec.argv, "--listen") or ""
    if listen != f"unix://{SOCKET_DIR / run_dir.name}.sock":
        return f"user-config codex app-server must listen on the run socket, got {listen!r}"
    return None


def require_isolated(spec: BackendSpec, run_dir: Path, user_home: Path) -> None:
    problem = spec_problem(spec, run_dir, user_home)
    if problem:
        raise isolation.IsolationError(problem)


def wait_socket(path: Path | str, timeout_s: float) -> bool:
    url = str(path)
    tcp = url.startswith("http://")
    host, _, port = url.removeprefix("http://").partition(":")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        s = socket.socket(socket.AF_INET if tcp else socket.AF_UNIX)
        try:
            s.connect((host, int(port)) if tcp else url)
            return True
        except OSError:
            time.sleep(0.2)
        finally:
            s.close()
    return False


def secret_env_file(spec: BackendSpec) -> Path:
    return Path(spec.log).parent / "env-backend.sh"


def spec_command(spec: BackendSpec, argv: list[str]) -> tuple[list[str], dict[str, str]]:
    if not spec.sandbox:
        return argv, spec.env
    box = spec.sandbox
    wrap = sandbox.wrap_launch if argv and sandbox.is_sops_exec(argv[0]) else sandbox.wrap_command
    wrapped = wrap(box["agent"], argv, spec.env, box["nono"], Path(box["user_home"]))
    return wrapped.argv, wrapped.env


def start_server(spec: BackendSpec) -> int:
    argv, env = spec_command(spec, spec.argv)
    log = open(spec.log, "ab")  # noqa: SIM115 - handed to the child, closed below
    try:
        proc = subprocess.Popen(private_env_argv(argv, env, secret_env_file(spec)), cwd=spec.cwd,
                                stdin=subprocess.DEVNULL,
                                stdout=log, stderr=log, start_new_session=True)
    finally:
        log.close()
    if spec.socket and not wait_socket(spec.socket, 30.0):
        stop_group(proc.pid)
        raise BackendError(f"{spec.kind} did not open {spec.socket} within 30s (log {spec.log})")
    return proc.pid


def run_daemon_command(spec: BackendSpec, verb: str, run_dir: Path, user_home: Path) -> subprocess.CompletedProcess:
    require_isolated(spec, run_dir, user_home)
    argv, env = spec_command(spec, [*spec.argv[:-1], verb]) if verb == "start" else ([*spec.argv[:-1], verb],
                                                                                        spec.env)
    with open(spec.log, "ab") as log:
        return subprocess.run(env_wrapped(argv, env), cwd=spec.cwd, stdin=subprocess.DEVNULL, stdout=log,
                              stderr=log, timeout=120)


def daemon_file_pid(spec: BackendSpec) -> int | None:
    pid_file = codex_daemon_pid_file(Path(spec.env["CODEX_HOME"]))
    return parse_daemon_pid(pid_file.read_text()) if pid_file.exists() else None


def runs_codex(rows: list[procs.ProcRow], pid: int, spec: BackendSpec) -> bool:
    binary = next((a for a in spec.argv if Path(a).name == "codex"), None)
    return bool(binary) and any(r.pid == pid and r.args.startswith(f"{binary} ") for r in rows)


def abandon_daemon_start(spec: BackendSpec, run_dir: Path, user_home: Path, cause: str) -> BackendError:
    with contextlib.suppress(subprocess.SubprocessError, OSError):
        run_daemon_command(spec, "stop", run_dir, user_home)
    pid = daemon_file_pid(spec)
    ours = pid is not None and procs.alive(pid) and runs_codex(procs.ps_rows(), pid, spec)
    if ours:
        terminate(pid, False, 5.0)
    stopped = f"; stopped daemon pid {pid}" if ours else ""
    return BackendError(f"{cause}{stopped} (log {spec.log})")


def start_daemon(spec: BackendSpec, run_dir: Path, user_home: Path) -> int:
    try:
        out = run_daemon_command(spec, "start", run_dir, user_home)
    except subprocess.TimeoutExpired:
        raise abandon_daemon_start(spec, run_dir, user_home, "codex daemon start timed out") from None
    pid = daemon_file_pid(spec)
    if out.returncode != 0 or pid is None or not procs.alive(pid):
        raise abandon_daemon_start(spec, run_dir, user_home, f"codex daemon start exited {out.returncode}, pid {pid}")
    if spec.socket and not wait_socket(spec.socket, 30.0):
        raise abandon_daemon_start(spec, run_dir, user_home, f"codex daemon did not open {spec.socket} within 30s")
    return pid


SERVICE_START_TIMEOUT_S = 150.0


def service_pid_in_run(registration: Path, run_dir: Path) -> int | None:
    pid = read_json(registration).get("pid")
    if not isinstance(pid, int) or not procs.alive(pid):
        return None
    cwd = procs.cwds({pid}).get(pid, "")
    return pid if cwd and Path(cwd).resolve().is_relative_to((run_dir / "home").resolve()) else None


def registered_service_pid(spec: BackendSpec, run_dir: Path) -> int | None:
    return service_pid_in_run(opencode_service_registration(spec.env), run_dir)


def abandon_service_start(spec: BackendSpec, run_dir: Path, proc: subprocess.Popen | None, cause: str) -> BackendError:
    if proc is not None and proc.poll() is None:
        stop_group(proc.pid, grace_s=2.0)
    pid = registered_service_pid(spec, run_dir)
    if pid:
        stop_group(pid)
    stopped = f"; stopped the registered service pid {pid}" if pid else ""
    return BackendError(f"opencode service start failed: {cause}{stopped} (log {spec.log})")


def start_opencode_service(spec: BackendSpec, run_dir: Path, user_home: Path,
                           timeout_s: float = SERVICE_START_TIMEOUT_S) -> int:
    require_isolated(spec, run_dir, user_home)
    proc = None
    try:
        with open(spec.log, "ab") as log:
            argv, env = spec_command(spec, spec.argv)
            proc = subprocess.Popen(env_wrapped(argv, env), cwd=spec.cwd, stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=log, start_new_session=True)
            code = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        raise abandon_service_start(spec, run_dir, proc, f"`service start` still running after {timeout_s:.0f}s") \
            from None
    except OSError as e:
        raise abandon_service_start(spec, run_dir, proc, f"{type(e).__name__}: {e}") from e
    registration = read_json(opencode_service_registration(spec.env))
    pid = registration.get("pid")
    if code != 0 or not isinstance(pid, int) or not procs.alive(pid):
        raise abandon_service_start(spec, run_dir, None, f"exit {code}, registered pid {pid}")
    if registration.get("url", "").rstrip("/") != spec.socket:
        url = registration.get("url")
        raise abandon_service_start(spec, run_dir, None, f"registered {url}, expected {spec.socket}")
    if spec.socket and not wait_socket(spec.socket, 30.0):
        raise abandon_service_start(spec, run_dir, None, f"{spec.socket} not reachable within 30s")
    return pid


def start(spec: BackendSpec, run_dir: Path, user_home: Path = USER_HOME) -> int:
    require_isolated(spec, run_dir, user_home)
    if spec.kind == "codex-daemon":
        return start_daemon(spec, run_dir, user_home)
    if spec.kind == "opencode-service":
        return start_opencode_service(spec, run_dir, user_home)
    return start_server(spec)


def reap(pid: int) -> None:
    with contextlib.suppress(ChildProcessError, OSError):
        os.waitpid(pid, os.WNOHANG)


def wait_gone(pid: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while True:
        reap(pid)
        if not procs.alive(pid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def wait_exited(pid: int, group: bool, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while procs.live_group(pid) if group else procs.live_process(pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
    return True


def kill_allowed(group: bool, before: str | None, now: str | None) -> bool:
    if group and now is None:
        # a leaderless group still alive is the original one: a live group's pgid is never reused
        return True
    return before is not None and now == before


def terminate(pid: int, group: bool, grace_s: float) -> None:
    kill = os.killpg if group else os.kill
    before = procs.identities({pid}).get(pid)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        kill(pid, signal.SIGTERM)
    if wait_exited(pid, group, grace_s):
        return
    if kill_allowed(group, before, procs.identities({pid}).get(pid)):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            kill(pid, signal.SIGKILL)


def stop_group(pid: int, grace_s: float = 5.0, kill_wait_s: float = 3.0) -> None:
    terminate(pid, True, grace_s)
    wait_gone(pid, kill_wait_s)


def owned_backend(run_dir: Path, pid: int) -> bool:
    path = run_dir / "manifest.json"
    manifest = json.loads(path.read_text()) if path.exists() else {}
    return pid in guard.backend_pids(manifest) and guard.owned_pid(manifest, pid, procs.identities({pid}))


def stop(spec: BackendSpec, pid: int, run_dir: Path, user_home: Path = USER_HOME) -> None:
    if spec.kind == "codex-daemon":
        run_daemon_command(spec, "stop", run_dir, user_home)
    if procs.alive(pid) and owned_backend(run_dir, pid):
        stop_group(pid)


def launch(run_dir: Path, spec: BackendSpec, user_home: Path = USER_HOME) -> int:
    require_isolated(spec, run_dir, user_home)
    save_spec(run_dir, spec)
    pid = start(spec, run_dir, user_home)
    pid_path(run_dir).write_text(f"{pid}\n")
    return pid


def restart_detail(kind: str, old: int, new: int, t0: float, t1: float, t2: float) -> str:
    return (f"{kind} graceful stop+start, pid {old} -> {new}; stop {t1 - t0:.1f}s + start {t2 - t1:.1f}s = "
            f"down {t2 - t0:.1f}s")


def restart(run_dir: Path, user_home: Path = USER_HOME, clock=time.time) -> tuple[int, str]:
    spec, pid = load_spec(run_dir), current_pid(run_dir)
    if spec is None or pid is None:
        raise BackendError(f"no backend spec or pid in {run_dir}")
    require_isolated(spec, run_dir, user_home)
    if not (procs.alive(pid) and owned_backend(run_dir, pid)):
        raise BackendError(f"{spec.kind} pid {pid} is not running as the run's backend; nothing to restart")
    old_identity = procs.identities({pid}).get(pid)
    t0 = clock()
    stop(spec, pid, run_dir, user_home)
    t1 = clock()
    if procs.alive(pid) and procs.identities({pid}).get(pid) == old_identity:
        raise BackendError(f"{spec.kind} pid {pid} is still running after the stop")
    new_pid = start(spec, run_dir, user_home)
    t2 = clock()
    if procs.identities({new_pid}).get(new_pid) == old_identity:
        raise BackendError(f"{spec.kind} start returned the old backend (pid {new_pid}); no restart happened")
    pid_path(run_dir).write_text(f"{new_pid}\n")
    return new_pid, restart_detail(spec.kind, pid, new_pid, t0, t1, t2)


def backend_entry(kind: str, pid: int) -> str:
    return f"{kind}:{pid}"
