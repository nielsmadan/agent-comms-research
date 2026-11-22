import contextlib
import os
import shlex
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agentcomms import backends, procs
from agentcomms.adapters.native import NativeAdapter, now, receipt
from agentcomms.model import SendReceipt

LIFECYCLE_NA = ("not measured: the bridge owns the session lifecycle (it starts the agent itself), so a harness "
                "resume would bypass it, and the bridge's own restart path is not driven by the harness")

CLI_TIMEOUT_S = 30.0
BASE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


def run_dir(work_dir: Path) -> Path:
    return work_dir.parent.parent


def tools_dir(work_dir: Path) -> Path:
    return run_dir(work_dir) / "bin" / f"tools-{work_dir.name}"


def executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def reaches(folder: str, names: tuple[str, ...], is_exec: Callable[[Path], bool] = executable) -> bool:
    return any(is_exec(Path(folder) / n) for n in names) or Path(folder).name == "shims"


def contained_path(path: str, first: tuple[str, ...], blocked: tuple[str, ...],
                   is_exec: Callable[[Path], bool] = executable) -> str:
    kept = [d for d in path.split(":") if d and d not in first and not reaches(d, blocked, is_exec)]
    return ":".join([*first, *kept])


def pinned_inner(argv: list[str], pins: dict[str, str]) -> list[str]:
    if not argv or Path(argv[0]).name != "sops-exec":
        raise ValueError(f"expected a sops-exec launch, got {argv[:1]}")
    return [argv[0], "/usr/bin/env", *(f"{k}={v}" for k, v in sorted(pins.items())), *argv[1:]]


def forwarding_exec(wrapped: list[str], forward: tuple[str, ...]) -> str:
    if wrapped[:2] != ["/usr/bin/env", "-i"]:
        raise ValueError("expected an env -i launch")
    words = ["/usr/bin/env -i", *(f'"{name}=${{{name}-}}"' for name in forward), shlex.join(wrapped[2:])]
    return f"#!/bin/sh\nexec {' '.join(words)}\n"


def tool_wrapper(env: dict[str, str], argv: list[str], forward: tuple[str, ...] = ()) -> str:
    words = ["/usr/bin/env -i", *(f'"{name}=${{{name}-}}"' for name in forward),
             shlex.join([*(f"{k}={v}" for k, v in sorted(env.items())), *argv]), '"$@"']
    return f"#!/bin/sh\nexec {' '.join(words)}\n"


def require_owned_daemon(run_dir_: Path, pid: int | None, label: str) -> int:
    if pid is None or not procs.alive(pid) or not backends.owned_backend(run_dir_, pid):
        raise backends.BackendError(f"{label} pid {pid} is not a live tracked bridge daemon of the run")
    return pid


def stop_pid(pid: int, group: bool, grace_s: float = 5.0) -> None:
    backends.terminate(pid, group, grace_s)
    if not backends.wait_gone(pid, grace_s):
        raise backends.BackendError(f"bridge daemon pid {pid} still running after SIGKILL")


def wait_for(check, timeout_s: float, interval_s: float = 0.5):
    deadline = time.monotonic() + timeout_s
    while True:
        value = check()
        if value or time.monotonic() >= deadline:
            return value
        time.sleep(interval_s)


@dataclass(frozen=True)
class CliResult:
    code: int
    stdout: str
    stderr: str


def run_cli(argv: list[str], env: dict[str, str], stdin: str | None = None, cwd: Path | None = None,
            timeout_s: float = CLI_TIMEOUT_S) -> CliResult:
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE if stdin is not None else None, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=env, cwd=cwd, start_new_session=True)
    except OSError as e:
        return CliResult(127, "", f"{type(e).__name__}: {e}")
    try:
        out, err = proc.communicate(stdin, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
        out, _ = proc.communicate()
        return CliResult(124, out or "", f"timeout after {timeout_s:.0f}s")
    return CliResult(proc.returncode, out, err)


def cli_receipt(started: tuple[float, float], label: str, result: CliResult) -> SendReceipt:
    tail = (result.stdout.strip() or result.stderr.strip()).splitlines()[-1:] or [""]
    return receipt(started, result.code == 0, f"{label}: exit {result.code} {tail[0][:160]}".strip())


@dataclass(frozen=True)
class AgentRoute:
    discovery: Literal["name", "address"]
    address: str
    identity: tuple[str, ...]
    command: list[str] | None = None
    tool: str | None = None


class BridgeAdapter(NativeAdapter):
    kind: Literal["native", "terminal", "bridge"] = "bridge"

    def cli_send(self, argv: list[str], env: dict[str, str], text: str, label: str,
                 cwd: Path | None = None) -> SendReceipt:
        started = now()
        return cli_receipt(started, label, run_cli(argv, env, text, cwd))
