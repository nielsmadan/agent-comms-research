from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import uuid
from pathlib import Path


def load_sibling(name: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                     f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = load_sibling("guard")
unix_send = load_sibling("unix_send")


def peer_frame(text: str, msg_id: str) -> bytes:
    frame = {"msgV": 1, "msg_id": msg_id, "type": "user", "priority": "next",
             "message": {"role": "user", "content": text}}
    return (json.dumps(frame) + "\n").encode()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="send stdin as a Claude peer frame to a harness Pi running pi-claude-link")
    p.add_argument("--socket", required=True,
                   help="/tmp/ac/<run_id>-cl/cc-socks/<pi pid>.sock, listed in that run's manifest")
    args = p.parse_args(argv)
    try:
        guard.owned_agent_socket(Path(args.socket), "pi")
    except (guard.GuardError, OSError, ValueError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    unix_send.send(args.socket, peer_frame(sys.stdin.read(), str(uuid.uuid4())))
    print(f"sent to {args.socket}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
