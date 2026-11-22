import json
import os
import sys
import termios
import time
import tty


def log_line(out, **fields) -> None:
    out.write(json.dumps(fields).encode() + b"\n")


def main(path: str) -> None:
    fd = sys.stdin.fileno()
    termios.tcgetattr(fd)
    tty.setraw(fd)
    sys.stdout.write("\x1b[?2004h")
    sys.stdout.flush()
    cols, rows = os.get_terminal_size(fd)
    with open(path, "ab", buffering=0) as out:
        log_line(out, ready=True, rows=rows, cols=cols, term=os.environ.get("TERM", ""))
        while True:
            data = os.read(fd, 65536)
            if not data:
                return
            log_line(out, t=time.time(), hex=data.hex())


if __name__ == "__main__":
    main(sys.argv[1])
