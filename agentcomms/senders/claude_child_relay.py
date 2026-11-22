from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
import time
import uuid

SERVER_INFO = {"name": "agentcomms-relay", "version": "0.1"}


def load_sibling(name: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                     f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


uds = load_sibling("claude_uds")


def mcp_reply(request: dict) -> dict | None:
    method, req_id = request.get("method"), request.get("id")
    if req_id is None:
        return None
    if method == "initialize":
        version = (request.get("params") or {}).get("protocolVersion", "2025-06-18")
        return {"jsonrpc": "2.0", "id": req_id,
                "result": {"protocolVersion": version, "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": []}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"method not found: {method}"}}


def parent_of(pid: int) -> int:
    out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True)
    return int(out.stdout.strip() or 0)


def claude_ancestor(config_dir: str, pid: int) -> int | None:
    while pid > 1:
        if os.path.exists(os.path.join(config_dir, "sessions", f"{pid}.json")):
            return pid
        pid = parent_of(pid)
    return None


def target(environ: dict[str, str]) -> tuple[str, str, str]:
    if environ.get("CLAUDE_CODE_MESSAGING_SOCKET") and environ.get("CLAUDE_CODE_MESSAGING_TOKEN"):
        return environ["CLAUDE_CODE_MESSAGING_SOCKET"], environ["CLAUDE_CODE_MESSAGING_TOKEN"], "child-env"
    config_dir = environ["CLAUDE_CONFIG_DIR"]
    pid = claude_ancestor(config_dir, os.getppid())
    if pid is None:
        raise RuntimeError("no Claude ancestor with a registry entry")
    sock, token = uds.peer_address(config_dir, pid)
    return sock, token, "peer-key"


def log(path: str | None, line: str) -> None:
    if path:
        with open(path, "a") as f:
            f.write(f"{time.time():.3f} {line}\n")


def handle(conn: socket.socket, log_path: str | None) -> None:
    with conn:
        chunks = []
        while True:
            data = conn.recv(65536)
            if not data:
                break
            chunks.append(data)
        text = b"".join(chunks).decode()
        try:
            sock, token, source = target(dict(os.environ))
            uds.send(sock, uds.wire(token, text, str(uuid.uuid4())))
            reply = f"forwarded via {source}"
        except Exception as e:
            reply = f"error {type(e).__name__}: {e}"
        log(log_path, reply)
        conn.sendall(reply.encode())


def serve(path: str, log_path: str | None) -> None:
    if os.path.exists(path):
        os.unlink(path)
    server = socket.socket(socket.AF_UNIX)
    server.bind(path)
    server.listen(8)
    names = ("CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN")
    has = {k: "yes" if os.environ.get(k) else "no" for k in names}
    log(log_path, f"listening ppid={os.getppid()} child_socket={has['CLAUDE_CODE_MESSAGING_SOCKET']} "
                  f"child_token={has['CLAUDE_CODE_MESSAGING_TOKEN']}")
    while True:
        conn, _ = server.accept()
        threading.Thread(target=handle, args=(conn, log_path), daemon=True).start()


def main() -> int:
    path = os.environ["AGENTCOMMS_RELAY_SOCKET"]
    threading.Thread(target=serve, args=(path, os.environ.get("AGENTCOMMS_RELAY_LOG")), daemon=True).start()
    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                continue
            reply = mcp_reply(request)
            if reply is not None:
                sys.stdout.write(json.dumps(reply) + "\n")
                sys.stdout.flush()
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
