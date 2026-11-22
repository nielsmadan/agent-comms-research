import fcntl
import os
import pty
import struct
import subprocess
import termios
import threading
from pathlib import Path

from agentcomms.hosts.tmux import AttachedClient, copy_stream


def spawn_in_pty(argv: list[str], cwd: Path, env: dict[str, str], rows: int, cols: int, log: Path) -> AttachedClient:
    log.parent.mkdir(parents=True, exist_ok=True)
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    try:
        proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, cwd=cwd, env=env,
                                start_new_session=True)
    finally:
        os.close(slave)
    reader = threading.Thread(target=copy_stream, args=(master, log), daemon=True)
    reader.start()
    return AttachedClient(proc, master, log, reader)
