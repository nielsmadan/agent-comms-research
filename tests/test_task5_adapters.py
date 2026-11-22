import base64
import json
import os
import shutil
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from agentcomms import backends, manifest, mesh_probe, procs, profiles
from agentcomms.adapters import ADAPTERS, adapter_backend
from agentcomms.adapters.opencode_server import OpenCodeServer, OpenCodeServerSynthetic, OpenCodeService
from agentcomms.adapters.pi_claude_link import PiClaudeLink, peer_socket, unwrap_link_frame
from agentcomms.adapters.pi_ext import EXTENSION, PiExt
from agentcomms.adapters.pi_session_bridge import PiSessionBridge, bridge_socket
from agentcomms.engine import backend_socket, receiver_hits, resume_extra, write_launch_files
from agentcomms.model import Target
from agentcomms.senders import claude_link, guard, opencode_http, pi_bridge
from agentcomms.transcripts.pi import PiTranscript, idle_from_records

RUN = "20261027-120000-abcd"
ENVELOPE = 'ACK-REQUEST 62633465: reply with exactly "ACK 62633465". This is an idle-wake test from the agentcomms ' \
           'harness; no other action is needed.'
SESSION = "ses_e82f86bc8ffewopJkm6Y69UWuy"


def target(tmp_path: Path, agent: str, pid: int | None = 4242, backend: str = "none",
           backend_ref: str | None = None, session_id: str | None = None) -> Target:
    run = tmp_path / "runs" / RUN
    return Target(run_id=RUN, agent=agent, host="tmux", backend=backend, work_dir=run / "work" / agent,
                  home_dir=run / "home" / agent, session_id=session_id, host_ref="agentcomms:x",
                  backend_ref=backend_ref, transcript=None, agent_pid=pid)


def write_manifest(run_dir: Path, targets: list[dict], sockets: list[str] = (), backends_: list[str] = (),
                   identities: dict | None = None) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(json.dumps({
        "run_id": run_dir.name, "pgids": [], "targets": targets, "sockets": list(sockets),
        "backends": list(backends_), "identities": identities or {}}))


def opencode_env(home: Path) -> dict[str, str]:
    return {"XDG_CONFIG_HOME": str(home / "config"), "XDG_DATA_HOME": str(home / "data"),
            "XDG_STATE_HOME": str(home / "state"), "XDG_CACHE_HOME": str(home / "cache"),
            "OPENCODE_TEST_HOME": str(home), "TMPDIR": str(home / "tmp")}


def test_opencode_route_builders():
    assert opencode_http.route_path("prompt", SESSION) == f"/api/session/{SESSION}/prompt"
    assert opencode_http.route_path("synthetic", SESSION) == f"/api/session/{SESSION}/synthetic"
    assert opencode_http.route_body("hi", "queue") == {"text": "hi", "delivery": "queue"}
    assert opencode_http.create_session_body(SESSION, "/w", "opencode-go/gpt-6-luna") == {
        "id": SESSION, "location": {"directory": "/w"}, "model": {"id": "gpt-6-luna", "providerID": "opencode-go"},
        "agent": "build"}
    assert base64.b64decode(opencode_http.basic_auth("pw").split()[1]) == b"opencode:pw"


@pytest.mark.parametrize("route, session, delivery", [("message", SESSION, "steer"), ("prompt", "../x", "steer"),
                                                      ("prompt", SESSION, "interrupt")])
def test_opencode_route_builders_refuse_unknown_routes_ids_and_deliveries(route, session, delivery):
    with pytest.raises(ValueError):
        opencode_http.route_path(route, session)
        opencode_http.route_body("x", delivery)


def test_opencode_post_sends_auth_and_body_to_the_session_route():
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            seen["auth"] = self.headers["Authorization"]
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            reply = json.dumps({"data": {"id": "msg_1", "delivery": "steer"}}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    status, reply = opencode_http.post(url, "prompt", SESSION, ENVELOPE, "steer", "pw")
    server.server_close()
    assert (status, opencode_http.outcome(status, reply)) == (200, "http 200 inbox=msg_1 delivery=steer")
    assert seen == {"path": f"/api/session/{SESSION}/prompt", "auth": opencode_http.basic_auth("pw"),
                    "body": {"text": ENVELOPE, "delivery": "steer"}}


def test_opencode_server_launch_attaches_the_tui_to_a_loopback_server(tmp_path, fake_pinned):
    t = target(tmp_path, "opencode")
    mods = OpenCodeServer().launch_mods("opencode", t.work_dir, t.home_dir)
    url = mods.extra_args[1]
    assert mods.extra_args[0] == "--server" and url.startswith("http://127.0.0.1:")
    assert mods.backend_argv[0] == str(profiles.SOPS_EXEC)
    assert backends.opencode_args(list(mods.backend_argv))[:3] == ["serve", "--hostname", "127.0.0.1"]
    assert backend_socket(mods, t.home_dir) == url
    assert mods.files[str(t.home_dir / "server-password")] == mods.env["OPENCODE_PASSWORD"]


def test_opencode_service_launch_seeds_an_isolated_service_config(tmp_path, fake_pinned):
    t = target(tmp_path, "opencode")
    mods = OpenCodeService().launch_mods("opencode", t.work_dir, t.home_dir)
    write_launch_files(mods.files, t.work_dir, t.home_dir)
    config = json.loads((t.home_dir / "config" / "opencode" / "service.json").read_text())
    assert config["hostname"] == "127.0.0.1" and config["password"] == (t.home_dir / "server-password").read_text()
    assert backends.opencode_args(list(mods.backend_argv)) == ["service", "start"]
    assert backend_socket(mods, t.home_dir, opencode_env(t.home_dir)) == f"http://127.0.0.1:{config['port']}"
    assert mods.extra_args == ()


def test_opencode_specs_pass_only_inside_the_run(tmp_path):
    run_dir = tmp_path / "runs" / RUN
    home = run_dir / "home" / "opencode"
    serve = backends.BackendSpec("opencode-server", ["sops-exec", "/x/opencode", "serve", "--hostname", "127.0.0.1",
                                                     "--port", "5"], opencode_env(home), str(tmp_path), None, "log")
    assert backends.spec_problem(serve, run_dir, tmp_path) is None
    outside = backends.BackendSpec("opencode-server", serve.argv, opencode_env(tmp_path / "user"), "", None, "log")
    assert "is not under" in backends.spec_problem(outside, run_dir, tmp_path)
    wildcard = backends.BackendSpec("opencode-server", ["/x/opencode", "serve", "--hostname", "0.0.0.0"],
                                    opencode_env(home), "", None, "log")
    assert "--hostname 127.0.0.1" in backends.spec_problem(wildcard, run_dir, tmp_path)


def test_opencode_service_spec_needs_a_seeded_non_default_port(tmp_path):
    run_dir = tmp_path / "runs" / RUN
    home = run_dir / "home" / "opencode"
    spec = backends.BackendSpec("opencode-service", ["/x/opencode", "service", "start"], opencode_env(home), "", None,
                                "log")
    assert "non-default port" in backends.spec_problem(spec, run_dir, tmp_path)
    config = home / "config" / "opencode" / "service.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"hostname": "127.0.0.1", "port": backends.OPENCODE_DEFAULT_SERVICE_PORT}))
    assert "non-default port" in backends.spec_problem(spec, run_dir, tmp_path)
    config.write_text(json.dumps({"hostname": "127.0.0.1", "port": 50123}))
    assert backends.spec_problem(spec, run_dir, tmp_path) is None


def test_opencode_tui_is_standalone_only_without_a_backend(tmp_path):
    binary = profiles.Binary("opencode", Path("/x/opencode"), "2.1.4")
    assert profiles.tui_argv(binary, "auto", tmp_path, SESSION)[1] == "--standalone"
    attached = profiles.tui_argv(binary, "auto", tmp_path, SESSION, "opencode-server", ("--server", "http://h:1"))
    assert attached == ["/x/opencode", "--auto", "--session", SESSION, "--server", "http://h:1", str(tmp_path)]
    resumed = profiles.resume_argv(binary, "auto", tmp_path, SESSION, "opencode-service")
    assert resumed == ["/x/opencode", "--auto", "--session", SESSION, str(tmp_path)]
    assert resume_extra(target(tmp_path, "opencode", backend="opencode-server", backend_ref="http://h:1")) == \
        ("--server", "http://h:1")


def test_opencode_sender_guard_accepts_only_its_runs_live_server(tmp_path):
    url = "http://127.0.0.1:50123"
    me = os.getpid()
    ident = procs.identities({me})[me]
    t = {"agent": "opencode", "backend_ref": url, "session_id": SESSION}
    m = {"run_id": RUN, "targets": [t], "backends": [f"opencode-server:{me}"], "identities": {str(me): ident}}
    opencode_http.check_target(m, url, SESSION, {me: ident})
    refused = opencode_http.guard.GuardError
    with pytest.raises(refused, match="not an opencode target"):
        opencode_http.check_target(m, url, "ses_other0000000000", {me: ident})
    with pytest.raises(refused, match="not a loopback"):
        opencode_http.check_target(m, "http://10.0.0.2:50123", SESSION, {me: ident})
    with pytest.raises(refused, match="no running harness opencode server"):
        opencode_http.check_target(m, url, SESSION, {})


def test_opencode_sender_refuses_a_password_file_outside_runs(tmp_path, capsys):
    pw = tmp_path / "pw"
    pw.write_text("x")
    code = opencode_http.main(["--url", "http://127.0.0.1:1", "--session", SESSION, "--password-file", str(pw)])
    assert code == 2
    assert "is not inside the harness runs dir" in capsys.readouterr().err


def test_opencode_variants_declare_route_delivery_and_backend(tmp_path):
    assert {n: (ADAPTERS[n].route, ADAPTERS[n].delivery, adapter_backend(n, "opencode")) for n in ADAPTERS
            if n.startswith("opencode-")} == {
        "opencode-server-steer": ("prompt", "steer", "opencode-server"),
        "opencode-server-queue": ("prompt", "queue", "opencode-server"),
        "opencode-server-synthetic": ("synthetic", "steer", "opencode-server"),
        "opencode-service-steer": ("prompt", "steer", "opencode-service"),
    }
    t = target(tmp_path, "opencode", backend="opencode-server", backend_ref="http://127.0.0.1:5", session_id=SESSION)
    argv = OpenCodeServerSynthetic().sender_argv(t)
    assert argv[:2] == ["python3", "-I"] and argv[-4:] == ["--route", "synthetic", "--delivery", "steer"]


def test_pi_ext_launch_loads_the_extension_with_its_run_socket(tmp_path):
    t = target(tmp_path, "pi")
    adapter = PiExt()
    mods = adapter.launch_mods("pi", t.work_dir, t.home_dir)
    assert mods.extra_args == ("-e", str(EXTENSION))
    assert mods.env == {"AGENTCOMMS_PI_SOCKET": f"/tmp/ac/{RUN}-pi.sock"}
    assert adapter.run_sockets(t.work_dir) == [Path(f"/tmp/ac/{RUN}-pi.sock")]
    assert adapter.sender_argv(t)[-2:] == ["--socket", f"/tmp/ac/{RUN}-pi.sock"]


def test_vendored_pi_adapters_use_run_owned_dirs(tmp_path):
    t = target(tmp_path, "pi")
    assert bridge_socket(t.work_dir, 4242) == Path(f"/tmp/ac/{RUN}-pb/pi-4242.sock")
    assert peer_socket(t.work_dir, 4242) == Path(f"/tmp/ac/{RUN}-cl/cc-socks/4242.sock")
    assert PiSessionBridge().ready_sockets(t) == [bridge_socket(t.work_dir, 4242)]
    assert PiClaudeLink().sender_argv(t)[-1] == f"/tmp/ac/{RUN}-cl/cc-socks/4242.sock"


def test_pi_claude_link_launch_moves_its_socket_dir_under_tmp_ac(tmp_path):
    t = target(tmp_path, "pi")
    try:
        mods = PiClaudeLink().launch_mods("pi", t.work_dir, t.home_dir)
    except FileNotFoundError:
        pytest.skip("vendor/pi-claude-link not installed")
    assert mods.env == {"XDG_RUNTIME_DIR": f"/tmp/ac/{RUN}-cl"}
    assert mods.extra_args[0] == "-e" and mods.extra_args[1].endswith("pi-claude-link/index.ts")


def test_pi_isolated_home_is_what_the_extensions_see_as_home(tmp_path):
    binary = profiles.Binary("pi", Path("/m/node_modules/pi/cli.js"), "1.4.0", "pi", Path("/n/node"), "24.22.0")
    argv = profiles.tui_argv(binary, "auto", tmp_path, "s", home=tmp_path / "home")
    assert argv[:2] == ["/usr/bin/env", f"HOME={tmp_path / 'home'}"]


def test_unwrap_strips_the_pi_claude_link_frame(fixtures):
    user = [e for e in PiTranscript(fixtures / "pi" / "claude-link.jsonl").entries() if e[1] == "user"]
    assert user[0][2].startswith("[cross-agent message")
    assert PiClaudeLink().unwrap(user[0][2]) == ENVELOPE.replace("62633465", "da907ae7")
    assert unwrap_link_frame(ENVELOPE) == ENVELOPE


def test_pi_extension_turn_markers_make_idle_known(fixtures):
    transcript = PiTranscript(fixtures / "pi" / "ext-turn.jsonl")
    assert transcript.is_idle() is True
    records = transcript.records()
    busy = next(r for r in records if r.get("customType") == "agentcomms-turn")
    assert idle_from_records([*records[:-1], busy]) is False
    assert receiver_hits(transcript.entries(), "62633465")[0][1] == "user"


def test_pi_extension_markers_are_not_received_messages(fixtures):
    entries = PiTranscript(fixtures / "pi" / "ext-turn.jsonl").entries()
    assert [t for _, k, t in entries if k == "custom"] == ['{"state": "busy"}', '{"state": "idle"}']


def test_pi_bridge_wire_builder_and_response_matching():
    line = json.loads(pi_bridge.request_line("prompt", "hello", "r1"))
    assert line == {"id": "r1", "type": "prompt", "message": "hello"}
    lines = ['{"type": "bridge_hello", "protocol": "pi-session-bridge.v1"}', "not json",
             '{"type": "event", "event": "input"}',
             '{"type": "response", "id": "r1", "command": "prompt", "success": true, '
             '"data": {"deliveredAs": "now", "idleBeforeSend": true}}']
    reply = pi_bridge.response_for(lines, "r1")
    assert pi_bridge.summary(reply) == "ok deliveredAs=now idleBeforeSend=True"
    with pytest.raises(ValueError):
        pi_bridge.request_line("shutdown", "x", "r2")


def test_pi_bridge_send_reads_past_hello_and_events(tmp_path):
    path = f"/tmp/ac/t5-{os.getpid()}.sock"
    Path("/tmp/ac").mkdir(exist_ok=True)
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(path)
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        conn.sendall(b'{"type":"bridge_hello"}\n')
        req = json.loads(conn.recv(65536).decode())
        conn.sendall(b'{"type":"event","event":"input"}\n' + json.dumps(
            {"type": "response", "id": req["id"], "success": True, "data": {"deliveredAs": "steer"}}).encode() + b"\n")
        conn.close()

    threading.Thread(target=serve, daemon=True).start()
    try:
        reply = pi_bridge.send(path, "prompt", "hi", "r9")
    finally:
        srv.close()
        os.unlink(path)
    assert reply["data"] == {"deliveredAs": "steer"}


def test_claude_link_peer_frame_is_one_unauthenticated_user_line():
    lines = claude_link.peer_frame("hi", "m-1").decode().splitlines()
    assert [json.loads(line) for line in lines] == [
        {"msgV": 1, "msg_id": "m-1", "type": "user", "priority": "next", "message": {"role": "user", "content": "hi"}}]


def test_agent_socket_guard_accepts_a_listed_socket_of_an_owned_pi(tmp_path):
    me = os.getpid()
    ident = procs.identities({me})[me]
    sock = Path(f"/tmp/ac/{RUN}-pb/pi-{me}.sock")
    write_manifest(tmp_path / "runs" / RUN, [{"agent": "pi", "agent_pid": me}], [str(sock)],
                   identities={str(me): ident})
    assert guard.owned_agent_socket(sock, "pi", tmp_path / "runs") == me


@pytest.mark.parametrize("sock, why", [
    ("/tmp/ac/{run}-pb/pi-1.sock", "not a socket of run"),
    ("/tmp/ac/{run}-pb/pi-{pid}.sock", "does not belong to a claude target"),
    ("/tmp/cc-socks/{pid}.sock", "not inside a harness run socket dir"),
    ("/tmp/ac/{run}.sock", "not inside a harness run socket dir"),
])
def test_agent_socket_guard_refusals(tmp_path, sock, why):
    me = os.getpid()
    listed = Path(f"/tmp/ac/{RUN}-pb/pi-{me}.sock")
    write_manifest(tmp_path / "runs" / RUN, [{"agent": "pi", "agent_pid": me}], [str(listed)],
                   identities={str(me): procs.identities({me})[me]})
    agent = "claude" if "claude" in why else "pi"
    with pytest.raises(guard.GuardError, match=why):
        guard.owned_agent_socket(Path(sock.format(run=RUN, pid=me)), agent, tmp_path / "runs")


def test_agent_socket_guard_refuses_a_reused_pid(tmp_path):
    me = os.getpid()
    sock = Path(f"/tmp/ac/{RUN}-cl/cc-socks/{me}.sock")
    m = {"run_id": RUN, "targets": [{"agent": "pi", "agent_pid": me}], "sockets": [str(sock)],
         "identities": {str(me): "0" * 16}}
    with pytest.raises(guard.GuardError, match="not the process run"):
        guard.check_agent_socket(m, sock, "pi", procs.identities({me}))


def test_cleanup_removes_only_this_runs_socket_dirs(tmp_path):
    for name in (f"{RUN}-pb", f"{RUN}-cl", "20261027-130000-ffff-pb"):
        (tmp_path / name / "instances").mkdir(parents=True)
    (tmp_path / f"{RUN}.sock").write_text("")
    removed = manifest.remove_run_socket_dirs(RUN, tmp_path)
    assert removed == [f"removed socket dir {tmp_path / f'{RUN}-cl'}", f"removed socket dir {tmp_path / f'{RUN}-pb'}"]
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"{RUN}.sock", "20261027-130000-ffff-pb"]


def test_mesh_probe_refuses_unless_only_harness_claude_is_visible(tmp_path):
    claude = target(tmp_path, "claude", pid=10)
    pi_home = tmp_path / "runs" / RUN / "home" / "pi"
    pi_home.mkdir(parents=True)
    claude.home_dir.mkdir(parents=True)
    good_sock = f"/tmp/ac/{RUN}-cl/cc-socks/10.sock"
    assert "is not in" in mesh_probe.mesh_problem(claude, "/tmp/cc-socks/10.sock", pi_home, {10})
    assert "does not resolve" in mesh_probe.mesh_problem(claude, good_sock, pi_home, {10})
    (pi_home / ".claude").symlink_to(claude.home_dir)
    assert "not only the harness Claude" in mesh_probe.mesh_problem(claude, good_sock, pi_home, {10, 11})
    assert mesh_probe.mesh_problem(claude, good_sock, pi_home, {10}) is None


def test_vendored_send_argv_calls_the_packages_own_sender():
    argv = mesh_probe.vendored_send_argv("/tmp/ac/r-cl/cc-socks/1.sock", "hi", "/tmp/ac/r-cl/cc-socks/2.sock")
    assert argv[1] == "-e"
    assert "pi-claude-link/claude-protocol.ts" in argv[2] and '"from": "uds:/tmp/ac/r-cl/cc-socks/2.sock"' in argv[2]


@pytest.mark.skipif(shutil.which("bun") is None, reason="bun not installed")
def test_pi_extension_builds_with_bun(tmp_path):
    out = subprocess.run(["bun", "build", str(EXTENSION), "--target=node", "--external",
                          "@earendil-works/pi-coding-agent", "--outdir", str(tmp_path)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert (tmp_path / "agentcomms-inbox.js").exists()


FAKE_PI = """
const mod = await import(process.argv[2]);
const calls = [];
const handlers = {};
const pi = {
  on: (name, fn) => { handlers[name] = fn; },
  sendUserMessage: (text, options) => calls.push({ text, options: options ?? null }),
  appendEntry: (type, data) => calls.push({ entry: type, data }),
};
mod.default(pi);
await handlers.session_start({}, {});
if (process.argv[3] === "compacting") await handlers.session_before_compact({}, {});
await new Promise((r) => setTimeout(r, 200));
const net = await import("node:net");
const reply = await new Promise((resolve, reject) => {
  const c = net.connect(process.env.AGENTCOMMS_PI_SOCKET, () => c.end("hello \\u00e9"));
  let buf = "";
  c.on("data", (d) => (buf += d));
  c.on("end", () => resolve(buf));
  c.on("error", reject);
});
await handlers.agent_end({}, {});
await handlers.session_shutdown({}, {});
console.log(JSON.stringify({ reply, calls }));
process.exit(0);
"""
IDLE_MARKER = {"entry": "agentcomms-turn", "data": {"state": "idle"}}


@pytest.mark.skipif(shutil.which("bun") is None, reason="bun not installed")
@pytest.mark.parametrize("state, reply, calls", [
    ("ready", "queued followUp\n", [{"text": "hello é", "options": {"deliverAs": "followUp"}}, IDLE_MARKER]),
    ("compacting", "error compacting\n", [IDLE_MARKER]),
])
def test_pi_extension_queues_socket_text_as_follow_up_without_a_model(tmp_path, state, reply, calls):
    script = tmp_path / "fake-pi.mjs"
    script.write_text(FAKE_PI)
    Path("/tmp/ac").mkdir(exist_ok=True)
    sock = f"/tmp/ac/t5x-{os.getpid()}-{state}.sock"
    out = subprocess.run(["bun", str(script), str(EXTENSION), state], capture_output=True, text=True, timeout=30,
                         env={**os.environ, "AGENTCOMMS_PI_SOCKET": sock})
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout.strip().splitlines()[-1]) == {"reply": reply, "calls": calls}
    assert not Path(sock).exists()


STUB_SERVICE = """#!/bin/bash
perl -e 'use POSIX; setsid(); chdir $ENV{OPENCODE_TEST_HOME}; exec "sleep", "60"' &
mkdir -p "$XDG_STATE_HOME/opencode"
printf '{"pid": %d, "url": "%s"}' $! "$STUB_URL" > "$XDG_STATE_HOME/opencode/service.json"
sleep "$STUB_HANG"
exit "$STUB_EXIT"
"""


def stub_service_spec(tmp_path: Path, url: str, hang: str, code: str) -> tuple[Path, backends.BackendSpec]:
    run_dir = tmp_path / "runs" / RUN
    home = run_dir / "home" / "opencode"
    config = home / "config" / "opencode" / "service.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"hostname": "127.0.0.1", "port": 50123}))
    stub = tmp_path / "bin" / "opencode"
    stub.parent.mkdir()
    stub.write_text(STUB_SERVICE)
    stub.chmod(0o755)
    env = {**opencode_env(home), "PATH": "/usr/bin:/bin", "STUB_URL": url, "STUB_HANG": hang, "STUB_EXIT": code}
    return run_dir, backends.BackendSpec("opencode-service", [str(stub), "service", "start"], env, str(home),
                                         "http://127.0.0.1:50123", str(tmp_path / "backend.log"))


def registered_pid(spec: backends.BackendSpec) -> int:
    return json.loads(backends.opencode_service_registration(spec.env).read_text())["pid"]


@pytest.mark.parametrize("url, hang, code, cause", [
    ("http://127.0.0.1:50123", "0", "1", "exit 1"),
    ("http://127.0.0.1:50999", "0", "0", "registered http://127.0.0.1:50999"),
    ("http://127.0.0.1:50123", "30", "0", "still running after 1s"),
])
def test_failed_service_start_stops_the_registered_service(tmp_path, url, hang, code, cause):
    run_dir, spec = stub_service_spec(tmp_path, url, hang, code)
    with pytest.raises(backends.BackendError, match=cause) as failed:
        backends.start_opencode_service(spec, run_dir, tmp_path / "user", timeout_s=1.0)
    pid = registered_pid(spec)
    assert f"stopped the registered service pid {pid}" in str(failed.value)
    assert procs.alive(pid) is False


def test_tcp_endpoints_are_waited_for_by_connecting(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        assert backends.wait_socket(f"http://127.0.0.1:{listener.getsockname()[1]}", 1.0) is True


def serve_once(handler_body) -> str:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            handler_body(self)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 5

    def run():
        server.handle_request()
        server.server_close()

    threading.Thread(target=run, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}"


def reply_with(status: int, body: dict):
    def handle(req):
        req.rfile.read(int(req.headers["Content-Length"]))
        raw = json.dumps(body).encode()
        req.send_response(status)
        req.send_header("Content-Length", str(len(raw)))
        req.end_headers()
        req.wfile.write(raw)
    return handle


def bad_status_line(req):
    req.rfile.read(int(req.headers["Content-Length"]))
    req.wfile.write(b"NOT-HTTP\r\n\r\n")


def silent(req):
    threading.Event().wait(3)


def opencode_target(tmp_path: Path, url: str) -> Target:
    t = target(tmp_path, "opencode", backend="opencode-server", backend_ref=url, session_id=SESSION)
    t.home_dir.mkdir(parents=True, exist_ok=True)
    (t.home_dir / "server-password").write_text("pw")
    return t


@pytest.mark.parametrize("handler, detail", [
    (reply_with(401, {"error": "unauthorized"}), "http 401"),
    (bad_status_line, "BadStatusLine"),
])
def test_opencode_send_rejects_on_auth_failure_or_garbage(tmp_path, handler, detail):
    receipt = OpenCodeServer().send(opencode_target(tmp_path, serve_once(handler)), ENVELOPE)
    assert receipt.accepted is False
    assert detail in receipt.detail


def test_an_opencode_reply_timeout_after_the_write_leaves_the_verdict_to_the_transcript(tmp_path):
    receipt = OpenCodeServer().send(opencode_target(tmp_path, serve_once(silent)), ENVELOPE)
    assert receipt.accepted is True
    assert "request written, no reply: timed out; verdict from the transcript" in receipt.detail


def test_session_creation_failure_is_a_cell_error(tmp_path):
    from agentcomms.adapters.opencode_server import OpenCodeSessionError
    t = opencode_target(tmp_path, "")
    with pytest.raises(OpenCodeSessionError, match="http 409"):
        OpenCodeServer().prepare_backend(serve_once(reply_with(409, {"error": "conflict"})), SESSION, t.work_dir,
                                         t.home_dir)
    with pytest.raises(OpenCodeSessionError, match="Connection refused"):
        OpenCodeServer().prepare_backend("http://127.0.0.1:1", SESSION, t.work_dir, t.home_dir)


def serve_each(*handlers) -> str:
    queue = list(handlers)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            queue.pop(0)(self)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 5

    def run():
        for _ in handlers:
            server.handle_request()
        server.server_close()

    threading.Thread(target=run, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}"


def test_session_creation_waits_while_the_server_reports_service_starting(tmp_path):
    t = opencode_target(tmp_path, "")
    starting = reply_with(503, {"code": "service_starting"})
    url = serve_each(starting, starting, reply_with(200, {"data": {"id": SESSION}}))
    assert OpenCodeServer().prepare_backend(url, SESSION, t.work_dir, t.home_dir) == SESSION


def test_session_creation_gives_up_when_the_server_keeps_starting(tmp_path):
    from agentcomms.adapters.opencode_server import OpenCodeSessionError
    t = opencode_target(tmp_path, "")
    url = serve_once(reply_with(503, {"code": "service_starting"}))
    with pytest.raises(OpenCodeSessionError, match="http 503"):
        OpenCodeServer().prepare_backend(url, SESSION, t.work_dir, t.home_dir, starting_wait_s=0.0)


def test_free_port_skips_the_users_service_port():
    from agentcomms.adapters.opencode_server import free_port
    draws = iter([backends.OPENCODE_DEFAULT_SERVICE_PORT, 50001])
    assert free_port(lambda: next(draws)) == 50001


def test_server_spec_refuses_the_users_service_port(tmp_path):
    run_dir = tmp_path / "runs" / RUN
    spec = backends.BackendSpec("opencode-server", ["/x/opencode", "serve", "--hostname", "127.0.0.1", "--port",
                                                    str(backends.OPENCODE_DEFAULT_SERVICE_PORT)],
                                opencode_env(run_dir / "home" / "opencode"), "", None, "log")
    assert "user's service port" in backends.spec_problem(spec, run_dir, tmp_path)


def restartable(tmp_path: Path, monkeypatch, alive, idents, new_pid: int) -> Path:
    run_dir = tmp_path / "runs" / RUN
    home = run_dir / "home" / "opencode"
    home.mkdir(parents=True)
    backends.save_spec(run_dir, backends.BackendSpec("opencode-server", ["/x/opencode", "serve", "--hostname",
                                                                         "127.0.0.1", "--port", "5"],
                                                     opencode_env(home), "", None, "log"))
    backends.pid_path(run_dir).write_text("100\n")
    monkeypatch.setattr(backends, "owned_backend", lambda rd, pid: True)
    monkeypatch.setattr(backends.procs, "alive", alive)
    monkeypatch.setattr(backends.procs, "identities", idents)
    monkeypatch.setattr(backends, "stop", lambda spec, pid, rd, uh: None)
    monkeypatch.setattr(backends, "start", lambda spec, rd, uh: new_pid)
    return run_dir


def test_restart_fails_when_the_old_backend_survives_the_stop(tmp_path, monkeypatch):
    run_dir = restartable(tmp_path, monkeypatch, lambda pid: True, lambda pids: {p: "same" for p in pids}, 200)
    with pytest.raises(backends.BackendError, match="still running after the stop"):
        backends.restart(run_dir, tmp_path / "user")


def test_restart_fails_when_start_hands_back_the_old_backend(tmp_path, monkeypatch):
    stopped = []
    run_dir = restartable(tmp_path, monkeypatch, lambda pid: not stopped,
                          lambda pids: {p: "same" for p in pids}, 100)
    monkeypatch.setattr(backends, "stop", lambda spec, pid, rd, uh: stopped.append(pid))
    with pytest.raises(backends.BackendError, match="no restart happened"):
        backends.restart(run_dir, tmp_path / "user")


def test_s12_records_a_failed_restart_as_error(monkeypatch):
    from agentcomms.model import Delivery
    from agentcomms.scenarios import s12

    class Adapter:
        def restart_backend(self, target):
            raise backends.BackendError("pid 1 is not running as the run's backend")

    class Engine:
        def check_owned(self, target):
            pass

    class Cell:
        agent, target, adapter, engine = "opencode", None, Adapter(), Engine()

    monkeypatch.setattr(s12, "warm_up", lambda cell, target, timeout: True)
    out = s12.run(Cell())
    assert (out.delivery, out.notes) == (Delivery.ERROR, ["backend-restart-failed: pid 1 is not running as the "
                                                          "run's backend"])


def test_start_registers_pid_named_sockets_for_launch_and_resume(tmp_path, monkeypatch):
    from dataclasses import replace

    from agentcomms import engine as engine_mod
    from agentcomms.paths import Layout

    layout = Layout(tmp_path)
    eng = engine_mod.Engine(layout, environ={"HOME": str(tmp_path), "PATH": "/usr/bin"})

    class FakeTmux:
        def start(self, *args):
            return f"agentcomms:{args[0]}"

        def pane_pid(self, host_ref):
            return 1

        def start_recording(self, host_ref, path):
            pass

    pids = iter([4242, 5353])
    eng.tmux = FakeTmux()
    monkeypatch.setattr(eng, "await_ready", lambda t, b, p: (replace(t, agent_pid=next(pids)), "fake", []))
    monkeypatch.setattr(engine_mod.procs, "identities", lambda found: {p: "x" for p in found})
    m = eng.new_run()
    binary = profiles.Binary("pi", Path("/m/node_modules/pi/cli.js"), "1.4.0", "pi", Path("/n/node"), "24")
    launched = engine_mod.Launched(None, binary, {}, Path(), "", [], "auto", {}, PiSessionBridge())
    m, first = eng.start(m, launched, ["pi"], "s", f"{m.run_id}-pi", "pane-pi.log")
    m, _ = eng.start(m, replace(launched, target=first.target), ["pi"], "s", f"{m.run_id}-pi-resumed", "p2.log")
    assert [s.name for s in m.sockets] == ["pi-4242.sock", "pi-5353.sock"]


def test_secret_env_never_reaches_argv(tmp_path):
    from agentcomms.hosts import tmux

    env = {"PATH": "/usr/bin", "OPENCODE_PASSWORD": "p'w $x;y"}
    with pytest.raises(ValueError, match="private env file"):
        tmux.env_wrapped(["opencode"], env)
    secret = tmp_path / "env-x.sh"
    argv = tmux.private_env_argv(["opencode", "--server", "u"], env, secret)
    assert argv == ["/usr/bin/env", "-i", "PATH=/usr/bin", "/bin/sh", "-c", tmux.SOURCE_AND_EXEC, str(secret),
                    "opencode", "--server", "u"]
    assert secret.read_text() == "export OPENCODE_PASSWORD='p'\"'\"'w $x;y'\n"
    assert secret.stat().st_mode & 0o777 == 0o600
    out = subprocess.run([*argv[:-3], "/bin/sh", "-c", 'printf %s "$OPENCODE_PASSWORD"'], capture_output=True,
                         text=True, timeout=10)
    assert out.stdout == "p'w $x;y"


def test_launch_files_are_private(tmp_path, fake_pinned):
    t = target(tmp_path, "opencode")
    mods = OpenCodeService().launch_mods("opencode", t.work_dir, t.home_dir)
    write_launch_files(mods.files, t.work_dir, t.home_dir)
    assert {Path(p).name: Path(p).stat().st_mode & 0o777 for p in mods.files} == {"server-password": 0o600,
                                                                                  "service.json": 0o600}


def test_s8_scores_a_reply_without_its_pushed_prompt_as_reply_only(fixtures):
    from agentcomms.scenarios import s8

    synthetic = (fixtures / "render" / "s8-attach-opencode-synthetic.log").read_text(errors="replace")
    prompt = (fixtures / "render" / "s8-attach-opencode-prompt.log").read_text(errors="replace")
    assert s8.reply_rendered(synthetic, "ACK 6fff0ebb", s8.ACK_LEAD) is True
    assert s8.render_verdict(True, s8.prompt_rendered(synthetic, "6fff0ebb")) == "reply-only"
    assert s8.render_verdict(True, s8.prompt_rendered(prompt, "bf91adad")) == "yes"


TSCONFIG_PI = Path.home() / ".local/share/mise/installs/npm-earendil-works-pi-coding-agent/1.4.0/node_modules"
TSC = Path(__file__).resolve().parents[1] / "vendor/typescript/node_modules/typescript/bin/tsc"


@pytest.mark.skipif(not TSC.exists() or shutil.which("node") is None, reason="vendored typescript not installed")
def test_pi_extension_type_checks_against_pis_types(tmp_path):
    package = (TSCONFIG_PI / "@earendil-works" / "pi-coding-agent").resolve()
    if not (package / "dist" / "index.d.ts").exists():
        pytest.skip("pinned Pi install not present")
    config = {"compilerOptions": {"strict": True, "noEmit": True, "target": "es2022", "module": "esnext",
                                  "moduleResolution": "bundler", "skipLibCheck": True, "types": ["node"],
                                  "typeRoots": [str(package.parents[1] / "@types"),
                                                str(TSCONFIG_PI / ".mise" / "node_modules" / "@types")],
                                  "paths": {"@earendil-works/pi-coding-agent": [str(package / "dist" / "index.d.ts")]}},
              "files": [str(EXTENSION)]}
    (tmp_path / "tsconfig.json").write_text(json.dumps(config))
    out = subprocess.run(["node", str(TSC), "-p", str(tmp_path / "tsconfig.json")], capture_output=True, text=True,
                         timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr


def test_isolated_pi_keeps_almost_nothing_on_manual_compaction():
    from agentcomms import isolation

    assert isolation.pi_settings("openrouter/x", "off", "1.4.0")["compaction"] == {"keepRecentTokens": 1}


def test_s12_sends_to_the_agent_a_bridge_respawned_during_the_restart(monkeypatch):
    from dataclasses import dataclass

    from agentcomms.model import Delivery
    from agentcomms.scenarios import s12
    from agentcomms.scenarios.common import Outcome

    @dataclass(frozen=True)
    class Launched:
        target: str
        binary: str

    class Adapter:
        startup_marker = "beacon"

        def restart_backend(self, target):
            return "gc supervisor stop+start"

    class Engine:
        def check_owned(self, target):
            pass

        def track_restarted_backend(self, m, target):
            return m

        def track_bridge_daemons(self, m, adapter, target):
            return m

        def readopt_agent(self, m, target, binary, marker):
            return m, f"{target}-respawned", True

        def snapshot(self, target, label):
            pass

    class Cell:
        agent, m, adapter, engine = "codex", "m", Adapter(), Engine()
        launched = Launched("old", "codex-bin")

        @property
        def target(self):
            return self.launched.target

    sent = []
    monkeypatch.setattr(s12, "warm_up", lambda cell, target, timeout: True)
    monkeypatch.setattr(s12.time, "sleep", lambda s: None)
    monkeypatch.setattr(s12, "send_and_observe",
                        lambda cell, target, body, timeout: sent.append(target) or Outcome(Delivery.DELIVERED))
    out = s12.run(Cell())
    assert sent == ["old-respawned"]
    assert out.notes[-2:] == ["backend-restart=gc supervisor stop+start", "agent-respawned-by-bridge"]


def test_s12_records_a_lost_agent_when_the_restart_killed_it_and_nothing_respawned_it(monkeypatch):
    from agentcomms.engine import AgentLostError
    from agentcomms.model import Delivery
    from agentcomms.scenarios import s12

    snapshots = []

    class Adapter:
        def restart_backend(self, target):
            return "gc supervisor stop+start"

    class Engine:
        def check_owned(self, target):
            pass

        def track_restarted_backend(self, m, target):
            return m

        def track_bridge_daemons(self, m, adapter, target):
            return m

        def readopt_agent(self, m, target, binary, marker):
            raise AgentLostError("codex pid 5 gone and nothing respawned it")

        def snapshot(self, target, label):
            snapshots.append(label)

    class Cell:
        agent, m, adapter, engine = "codex", "m", Adapter(), Engine()
        launched = type("L", (), {"target": "old", "binary": "bin"})()
        target = "old"

    monkeypatch.setattr(s12, "warm_up", lambda cell, target, timeout: True)
    monkeypatch.setattr(s12.time, "sleep", lambda s: None)
    out = s12.run(Cell())
    assert out.delivery is Delivery.LOST
    assert out.notes[0] == "backend-restart=gc supervisor stop+start"
    assert out.notes[1].startswith("agent-lost-by-restart: codex pid 5 gone")
    assert snapshots == ["after-restart"]
