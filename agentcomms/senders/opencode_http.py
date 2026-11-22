from __future__ import annotations

import argparse
import base64
import http.client
import importlib.util
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROUTES = ("prompt", "synthetic")
DELIVERIES = ("steer", "queue")
LOCAL_URL = re.compile(r"\Ahttp://127\.0\.0\.1:\d{1,5}\Z")
SESSION_ID = re.compile(r"\Ases_[0-9A-Za-z]{10,40}\Z")
OPENCODE_BACKENDS = ("opencode-server", "opencode-service")
TIMEOUT_S = 1.5
TRANSPORT_ERRORS = (OSError, ValueError, http.client.HTTPException)


def load_sibling(name: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                     f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = load_sibling("guard")


def route_path(route: str, session: str) -> str:
    if route not in ROUTES or not SESSION_ID.match(session):
        raise ValueError(f"unknown route {route!r} or malformed session id {session!r}")
    return f"/api/session/{session}/{route}"


def route_body(text: str, delivery: str) -> dict:
    if delivery not in DELIVERIES:
        raise ValueError(f"unknown delivery {delivery!r}")
    return {"text": text, "delivery": delivery}


def model_ref(model: str) -> dict:
    provider, _, model_id = model.partition("/")
    return {"id": model_id, "providerID": provider}


def create_session_body(session: str, directory: str, model: str, agent: str = "build") -> dict:
    return {"id": session, "location": {"directory": directory}, "model": model_ref(model), "agent": agent}


def basic_auth(password: str) -> str:
    return "Basic " + base64.b64encode(f"opencode:{password}".encode()).decode()


def request(url: str, path: str, body: dict, password: str, timeout_s: float = TIMEOUT_S) -> tuple[int, dict]:
    req = urllib.request.Request(url + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": basic_auth(password)})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return e.code, {"error": raw.decode(errors="replace")[:200]}


def post(url: str, route: str, session: str, text: str, delivery: str, password: str) -> tuple[int, dict]:
    return request(url, route_path(route, session), route_body(text, delivery), password)


def outcome(status: int, reply: dict) -> str:
    data = reply.get("data") if isinstance(reply.get("data"), dict) else {}
    if 200 <= status < 300:
        return f"http {status} inbox={data.get('id')} delivery={data.get('delivery')}"
    return f"http {status} {json.dumps(reply)[:160]}"


def check_target(manifest: dict, url: str, session: str, current: dict[int, str]) -> None:
    if not LOCAL_URL.match(url):
        raise guard.GuardError(f"{url} is not a loopback harness server")
    if not any(t.get("agent") == "opencode" and t.get("backend_ref") == url and t.get("session_id") == session
               for t in manifest["targets"]):
        raise guard.GuardError(f"{url} session {session} is not an opencode target of run {manifest['run_id']}")
    if not any(guard.live_backends(manifest, kind, current) for kind in OPENCODE_BACKENDS):
        raise guard.GuardError(f"run {manifest['run_id']} has no running harness opencode server")


def owned_target(password_file: Path, url: str, session: str, runs: Path | None = None) -> None:
    manifest = guard.load_manifest(guard.run_dir_for(password_file, runs or guard.RUNS))
    check_target(manifest, url, session, guard.identities(guard.backend_pids(manifest)))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="post stdin to a harness-owned OpenCode session over its v2 HTTP API")
    p.add_argument("--url", required=True, help="http://127.0.0.1:<port> of the run's opencode server")
    p.add_argument("--session", required=True, help="ses_… id of the target session")
    p.add_argument("--password-file", required=True, help="runs/<run_id>/home/opencode/server-password")
    p.add_argument("--route", choices=ROUTES, default="prompt")
    p.add_argument("--delivery", choices=DELIVERIES, default="steer")
    args = p.parse_args(argv)
    try:
        owned_target(Path(args.password_file), args.url, args.session)
        password = Path(args.password_file).read_text().strip()
    except (guard.GuardError, OSError, ValueError, KeyError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    try:
        status, reply = post(args.url, args.route, args.session, sys.stdin.read(), args.delivery, password)
    except TRANSPORT_ERRORS as e:
        print(f"failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(outcome(status, reply))
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    sys.exit(main())
