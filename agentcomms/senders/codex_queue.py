from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

UUID_LEN = 36
QUEUE_TIMEOUT_S = 30


def load_sibling(name: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                     f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def queue_argv(codex: str, thread: str, text: str) -> list[str]:
    if len(thread) != UUID_LEN or thread.count("-") != 4:
        raise ValueError(f"thread must be a UUID, not a name: {thread!r}")
    return [codex, "queue", "--thread", thread, "--message", text]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="queue stdin for a harness Codex thread via `codex queue` (UUID only)")
    p.add_argument("--codex", default="codex")
    p.add_argument("--codex-home", required=True, help="CODEX_HOME of the harness daemon that owns the thread")
    p.add_argument("--thread", required=True)
    args = p.parse_args(argv)
    guard = load_sibling("guard")
    try:
        guard.owned_codex_home(Path(args.codex_home))
        command = queue_argv(args.codex, args.thread, sys.stdin.read())
    except (guard.GuardError, OSError, ValueError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    out = subprocess.run(command, env=dict(os.environ, CODEX_HOME=args.codex_home), capture_output=True, text=True,
                         timeout=QUEUE_TIMEOUT_S)
    sys.stdout.write(out.stdout)
    sys.stderr.write(out.stderr)
    return out.returncode


if __name__ == "__main__":
    sys.exit(main())
