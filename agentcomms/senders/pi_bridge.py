from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import sys
import time
from pathlib import Path

COMMANDS = ("prompt", "steer", "follow_up")
TIMEOUT_S = 1.5


def load_sibling(name: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                     f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = load_sibling("guard")


def request_line(command: str, text: str, req_id: str) -> bytes:
    if command not in COMMANDS:
        raise ValueError(f"unknown pi-session-bridge command {command!r}")
    return (json.dumps({"id": req_id, "type": command, "message": text}) + "\n").encode()


def response_for(lines: list[str], req_id: str) -> dict | None:
    for line in lines:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(msg, dict) and msg.get("type") == "response" and msg.get("id") == req_id:
            return msg
    return None


def send(path: str, command: str, text: str, req_id: str, timeout_s: float = TIMEOUT_S) -> dict:
    deadline = time.monotonic() + timeout_s
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(timeout_s)
    try:
        s.connect(path)
        s.sendall(request_line(command, text, req_id))
        buf = b""
        while time.monotonic() < deadline:
            s.settimeout(max(0.05, deadline - time.monotonic()))
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            reply = response_for(buf.decode(errors="replace").splitlines(), req_id)
            if reply is not None:
                return reply
    finally:
        s.close()
    raise TimeoutError(f"no pi-session-bridge response for request {req_id} within {timeout_s}s")


def summary(reply: dict) -> str:
    data = reply.get("data") if isinstance(reply.get("data"), dict) else {}
    if reply.get("success"):
        return f"ok deliveredAs={data.get('deliveredAs')} idleBeforeSend={data.get('idleBeforeSend')}"
    return f"error {reply.get('error')}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="send stdin to a harness-owned Pi session through pi-session-bridge")
    p.add_argument("--socket", required=True, help="/tmp/ac/<run_id>-pb/pi-<pid>.sock, listed in that run's manifest")
    p.add_argument("--command", choices=COMMANDS, default="prompt")
    args = p.parse_args(argv)
    try:
        guard.owned_agent_socket(Path(args.socket), "pi")
    except (guard.GuardError, OSError, ValueError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    try:
        reply = send(args.socket, args.command, sys.stdin.read(), f"agentcomms-{os.getpid()}")
    except (OSError, TimeoutError) as e:
        print(f"failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(summary(reply))
    return 0 if reply.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
