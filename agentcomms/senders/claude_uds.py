from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import os
import sys
import uuid
from pathlib import Path

FROM_MODES = ("bypass", "prompting")


def load_sibling(name: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                     f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = load_sibling("guard")
unix_send = load_sibling("unix_send")


def auth_line(token: str) -> str:
    return json.dumps({"type": "auth", "token": token})


def user_frame(text: str, msg_id: str, from_mode: str | None = None) -> str:
    frame = {"type": "user", "message": {"role": "user", "content": text}, "priority": "next", "msgV": 1,
             "msg_id": msg_id}
    if from_mode:
        frame["from_mode"] = from_mode
    return json.dumps(frame)


def wire(token: str, text: str, msg_id: str, from_mode: str | None = None) -> bytes:
    return (f"{auth_line(token)}\n{user_frame(text, msg_id, from_mode)}\n").encode()


def key_files(config_dir: str, pid: int) -> list[str]:
    return sorted(glob.glob(os.path.join(config_dir, "sessions", f"{pid}.*.key")))


def registry(config_dir: str, pid: int) -> dict:
    with open(os.path.join(config_dir, "sessions", f"{pid}.json")) as f:
        return json.load(f)


def peer_token(key_file: str) -> str:
    with open(key_file) as f:
        return json.load(f)["peerToken"]


def peer_address(config_dir: str, pid: int) -> tuple[str, str]:
    sock = registry(config_dir, pid).get("messagingSocketPath")
    if not sock:
        raise guard.GuardError(f"no messagingSocketPath in {config_dir}/sessions/{pid}.json")
    if not guard.owned_claude_socket(sock, pid):
        raise guard.GuardError(f"registry socket {sock} does not belong to pid {pid}")
    keys = key_files(config_dir, pid)
    if not keys:
        raise guard.GuardError(f"no peer key for pid {pid} in {config_dir}/sessions")
    return sock, peer_token(keys[0])


def send(sock_path: str, payload: bytes) -> None:
    unix_send.send(sock_path, payload)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="push stdin into a harness-owned Claude Code session's peer inbox")
    p.add_argument("--config-dir", required=True, help="the receiver's CLAUDE_CONFIG_DIR, under the harness runs/")
    p.add_argument("--pid", type=int, required=True, help="the receiver's Claude pid (a target of that run)")
    p.add_argument("--from-mode", choices=FROM_MODES, help="assert the sender's permission-mode class")
    args = p.parse_args(argv)
    try:
        guard.owned_claude_target(Path(args.config_dir), args.pid)
        sock, token = peer_address(args.config_dir, args.pid)
    except (guard.GuardError, OSError, ValueError, KeyError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    send(sock, wire(token, sys.stdin.read(), str(uuid.uuid4()), args.from_mode))
    print(f"sent to {sock}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
