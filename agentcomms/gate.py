import contextlib
import errno
import os
from pathlib import Path

from agentcomms import procs
from agentcomms.paths import SOCKET_DIR


def gate_path(run_id: str, root: Path = SOCKET_DIR) -> Path:
    return root / f"{run_id}.fifo"


def open_marker(run_id: str) -> str:
    return f"GATE-OPEN-{run_id}"


def gate_command(path: Path) -> str:
    return f"cat {path}"


def create(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
    os.mkfifo(path, 0o600)
    return path


def reader_running(rows: list[procs.ProcRow], path: Path) -> bool:
    command = gate_command(path)
    return any(r.args == command or r.args.endswith(f" {command}") for r in rows)


def release(path: Path, marker: str) -> bool:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
    except OSError as e:
        if e.errno in (errno.ENXIO, errno.ENOENT):
            return False
        raise
    try:
        os.write(fd, f"{marker}\n".encode())
    finally:
        os.close(fd)
    return True


def remove(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
