from __future__ import annotations

import argparse
import errno
import importlib.util
import os
import socket
import sys
from pathlib import Path

CONNECT_TIMEOUT_S = 1.0
REPLY_TIMEOUT_S = 0.8


def send(path: str, body: bytes, timeout_s: float = CONNECT_TIMEOUT_S, reply_s: float = REPLY_TIMEOUT_S) -> str:
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(timeout_s)
    try:
        s.connect(path)
        s.sendall(body)
        try:
            s.shutdown(socket.SHUT_WR)
        except OSError as e:
            if e.errno != errno.ENOTCONN:
                raise
        s.settimeout(reply_s)
        try:
            return s.recv(4096).decode(errors="replace").strip()
        except TimeoutError:
            return ""
    finally:
        s.close()


def load_sibling(name: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                     f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="write stdin to a harness run socket (agentcomms channel server or relay)")
    p.add_argument("--socket", required=True, help="/tmp/ac/<run_id>-<kind>.sock, listed in that run's manifest")
    args = p.parse_args(argv)
    guard = load_sibling("guard")
    try:
        guard.owned_run_socket(Path(args.socket))
    except (guard.GuardError, OSError, ValueError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    print(send(args.socket, sys.stdin.buffer.read()) or "sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
