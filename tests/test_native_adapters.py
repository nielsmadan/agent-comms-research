import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from agentcomms import backends, manifest
from agentcomms.adapters import ADAPTERS, adapter_backend
from agentcomms.adapters.claude_channel import ClaudeChannel, channel_mcp_config
from agentcomms.adapters.claude_uds import ClaudeUds, ClaudeUdsAccept, ClaudeUdsChild, PeerAddressError, peer_address
from agentcomms.adapters.codex_remote import CodexRemoteStart
from agentcomms.adapters.native import unwrap_channel, unwrap_cross_session
from agentcomms.engine import backend_socket, receiver_hits, write_launch_files
from agentcomms.isolation import IsolationError
from agentcomms.model import LaunchMods, Manifest, Target
from agentcomms.paths import Layout
from agentcomms.senders import claude_child_relay, claude_uds, codex_queue, codex_remote, guard, unix_send
from agentcomms.transcripts.claude import ClaudeTranscript

ENVELOPE = 'ACK-REQUEST e8fede25: reply with exactly "ACK e8fede25". This is an idle-wake test from the agentcomms ' \
           'harness; no other action is needed.'


def target(tmp_path: Path, agent: str = "claude", pid: int = 4242) -> Target:
    work = tmp_path / "runs" / "20261025-000000-abcd" / "work" / agent
    return Target(run_id="20261025-000000-abcd", agent=agent, host="tmux", backend="none", work_dir=work,
                  home_dir=tmp_path / "home", session_id=None, host_ref="agentcomms:x", backend_ref=None,
                  transcript=None, agent_pid=pid)


def isolated_registry(home: Path, pid: int, sock: str, token: str = "ab" * 16) -> None:
    sessions = home / "sessions"
    sessions.mkdir(parents=True)
    (sessions / f"{pid}.json").write_text(json.dumps({"pid": pid, "messagingSocketPath": sock, "status": "idle"}))
    (sessions / f"{pid}.{'0' * 64}.key").write_text(json.dumps({"peerToken": token, "pidDomain": "x"}))


def test_claude_wire_sends_auth_line_then_user_frame():
    lines = claude_uds.wire("t0k", "hello", "m-1").decode().splitlines()
    assert [json.loads(line) for line in lines] == [
        {"type": "auth", "token": "t0k"},
        {"type": "user", "message": {"role": "user", "content": "hello"}, "priority": "next", "msgV": 1,
         "msg_id": "m-1"},
    ]


def test_claude_wire_asserts_mode_when_asked():
    frame = json.loads(claude_uds.wire("t0k", "hi", "m-2", "bypass").decode().splitlines()[1])
    assert frame["from_mode"] == "bypass"
    assert frame["message"]["content"] == "hi"


def test_peer_address_reads_isolated_registry_and_key(tmp_path):
    isolated_registry(tmp_path / "home", 4242, "/tmp/cc-socks/4242.sock")
    assert peer_address(tmp_path / "home", 4242) == ("/tmp/cc-socks/4242.sock", "ab" * 16)


def test_peer_address_refuses_a_socket_of_another_pid(tmp_path):
    isolated_registry(tmp_path / "home", 4242, "/tmp/cc-socks/999.sock")
    with pytest.raises(PeerAddressError, match="does not belong to pid 4242"):
        peer_address(tmp_path / "home", 4242)


def test_unwrap_strips_the_receiver_peer_frame(fixtures):
    record = json.loads((fixtures / "claude" / "peer-accepted.jsonl").read_text().splitlines()[0])
    assert unwrap_cross_session(record["message"]["content"]) == ENVELOPE


def test_unwrap_strips_a_cross_session_envelope():
    recorded = f'<cross-session-message from="uds:/tmp/cc-socks/1.sock" from-mode="bypass">\n{ENVELOPE}\n' \
               "</cross-session-message>"
    assert unwrap_cross_session(recorded) == ENVELOPE


def test_unwrap_channel_strips_the_channel_tag(fixtures):
    entries = ClaudeTranscript(fixtures / "claude" / "channel.jsonl").entries()
    pushed = [t for _, k, t in entries if k == "peer"]
    assert unwrap_channel(pushed[0]) == 'ACK-REQUEST abcd1234: reply with exactly "ACK abcd1234". channel probe'


def test_held_peer_message_is_not_a_receiver_record(fixtures):
    entries = ClaudeTranscript(fixtures / "claude" / "held.jsonl").entries()
    assert [k for _, k, t in entries if "4ebf4109" in t] == ["held"]
    assert receiver_hits(entries, "4ebf4109") == []


def test_accept_adapter_passes_inbound_setting_and_child_adds_relay(tmp_path):
    t = target(tmp_path)
    assert ClaudeUds().launch_mods("claude", t.work_dir, t.home_dir).extra_args == ()
    assert ClaudeUdsAccept().launch_mods("claude", t.work_dir, t.home_dir).extra_args == (
        "--settings", '{"crossSessionInbound": "accept"}')
    mods = ClaudeUdsChild().launch_mods("claude", t.work_dir, t.home_dir)
    config = json.loads(mods.files[str(t.home_dir / "relay-mcp.json")])
    relay = config["mcpServers"]["agentcomms-relay"]
    assert relay["args"][-1].endswith("senders/claude_child_relay.py")
    assert relay["env"]["AGENTCOMMS_RELAY_SOCKET"] == "/tmp/ac/20261025-000000-abcd-relay.sock"


def test_channel_launch_loads_the_development_channel(tmp_path):
    t = target(tmp_path)
    mods = ClaudeChannel().launch_mods("claude", t.work_dir, t.home_dir)
    assert mods.extra_args[-2:] == ("--dangerously-load-development-channels", "server:agentcomms")
    server = channel_mcp_config(Path("/tmp/ac/x-ch.sock"), Path("/l"), "/bin/bun")["mcpServers"]["agentcomms"]
    assert server["args"][0] == "run" and server["args"][1].endswith("agentcomms/channel/server.ts")


def test_senders_are_stdlib_scripts_on_stdin(tmp_path):
    t = target(tmp_path)
    argv = ClaudeUds().sender_argv(t)
    assert argv[:2] == ["python3", "-I"] and argv[2].endswith("senders/claude_uds.py")
    assert argv[-4:] == ["--config-dir", str(t.home_dir), "--pid", "4242"]


def test_codex_rpc_builders():
    assert codex_remote.turn_start_request(3, "th", "hi", "m") == {
        "id": 3, "method": "turn/start",
        "params": {"threadId": "th", "input": [{"type": "text", "text": "hi", "text_elements": []}],
                   "clientUserMessageId": "m"}}
    steer = codex_remote.turn_steer_request(4, "th", "tu", "hi", "m")
    assert steer["method"] == "turn/steer" and steer["params"]["expectedTurnId"] == "tu"
    assert codex_remote.initialize_request(1)["params"]["capabilities"] == {"experimentalApi": True}


def test_codex_turn_state_parsers():
    assert codex_remote.active_turn({"data": [{"id": "t2", "status": "inProgress"}]}) == "t2"
    assert codex_remote.active_turn({"data": [{"id": "t1", "status": "completed"}]}) is None
    assert codex_remote.thread_active({"thread": {"status": {"type": "active", "activeFlags": []}}})
    assert codex_remote.thread_active({"thread": {"status": {"type": "idle"}}}) is False


@pytest.mark.parametrize("size", [5, 300, 70000])
def test_websocket_frames_round_trip(size):
    payload = b"x" * size
    frame = codex_remote.ws_frame(payload, b"\x01\x02\x03\x04")
    assert frame[1] & 0x80
    assert codex_remote.ws_parse(frame + b"rest") == (True, 1, payload, b"rest")


def test_websocket_parse_waits_for_a_whole_frame():
    frame = codex_remote.ws_frame(b"hello", b"abcd")
    assert codex_remote.ws_parse(frame[:-1]) is None


def test_codex_queue_sender_takes_uuids_only():
    uuid = "01a1735e-88cb-7e91-9a5c-98ca2def0048"
    assert codex_queue.queue_argv("codex", uuid, "hi") == ["codex", "queue", "--thread", uuid, "--message", "hi"]
    with pytest.raises(ValueError, match="UUID"):
        codex_queue.queue_argv("codex", "my-session", "hi")


def test_relay_answers_mcp_handshake():
    init = claude_child_relay.mcp_reply({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                         "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert claude_child_relay.mcp_reply({"id": 2, "method": "tools/list"})["result"] == {"tools": []}
    assert claude_child_relay.mcp_reply({"method": "notifications/initialized"}) is None


def test_unix_send_returns_the_server_reply(tmp_path):
    os.makedirs("/tmp/ac", exist_ok=True)
    path = f"/tmp/ac/test-{os.getpid()}.sock"
    server = socket.socket(socket.AF_UNIX)
    server.bind(path)
    server.listen(1)
    received = []

    def serve():
        conn, _ = server.accept()
        received.append(conn.recv(100))
        conn.sendall(b"emitted\n")
        conn.close()

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        assert unix_send.send(path, b"body") == "emitted"
    finally:
        thread.join(2)
        server.close()
        os.unlink(path)
    assert received == [b"body"]


def test_codex_daemon_socket_is_derived_from_the_control_path(tmp_path):
    control = tmp_path.resolve() / "app-server-control" / "app-server-control.sock"
    expected = hashlib.sha256(str(control).encode()).hexdigest()
    assert backends.codex_daemon_socket(tmp_path) == backends.CODEX_DAEMON_SOCK_DIR / expected


def test_isolated_daemon_check_requires_a_home_under_runs(tmp_path):
    runs = tmp_path / "runs"
    inside = runs / "r" / "home" / "codex"
    inside.mkdir(parents=True)
    assert backends.isolated_daemon_problem(inside, tmp_path / "user", runs) is None
    assert "not under" in backends.isolated_daemon_problem(tmp_path / "user" / ".codex", tmp_path / "user", runs)


def test_daemon_pid_file_parsing():
    assert backends.parse_daemon_pid('{"pid":81588,"processStartTime":"x"}') == 81588
    assert backends.parse_daemon_pid("garbage") is None


def test_backend_adapters_declare_their_backend_and_socket(tmp_path, fake_pinned):
    assert adapter_backend("codex-queue", "codex") == "codex-daemon"
    assert adapter_backend("codex-remote-steer", "codex") == "codex-app-server"
    assert adapter_backend("claude-channel", "claude") == "none"
    t = target(tmp_path, "codex")
    mods = CodexRemoteStart().launch_mods("codex", t.work_dir, t.home_dir)
    assert mods.extra_args == ("--remote", "unix:///tmp/ac/20261025-000000-abcd.sock")
    assert backend_socket(mods, t.home_dir) == Path("/tmp/ac/20261025-000000-abcd.sock")
    daemon = LaunchMods(host="tmux", backend="codex-daemon", backend_argv=("codex", "app-server", "daemon", "start"))
    assert backend_socket(daemon, t.home_dir) == backends.codex_daemon_socket(t.home_dir)


def test_every_adapter_is_registered_by_name():
    assert set(ADAPTERS) >= {"claude-uds", "claude-uds-accept", "claude-uds-child", "claude-channel", "codex-queue",
                             "codex-remote-start", "codex-remote-steer"}


def test_launch_files_stay_inside_the_run(tmp_path):
    work = tmp_path / "runs" / "r" / "work" / "claude"
    home = tmp_path / "runs" / "r" / "home" / "claude"
    write_launch_files({str(home / "a.json"): "{}", "$HOME/b.json": "1"}, work, home)
    assert (home / "a.json").read_text() == "{}" and (home / "b.json").read_text() == "1"
    with pytest.raises(IsolationError, match="outside the run"):
        write_launch_files({str(tmp_path / "evil.json"): "x"}, work, home)


def test_codex_derived_sockets_are_removable_only_by_name(tmp_path):
    layout = Layout(tmp_path)
    run_id = "20261025-000000-abcd"
    home = layout.home_dir(run_id, "codex")
    t = replace(target(tmp_path, "codex"), backend="codex-daemon", home_dir=home)
    m = Manifest(run_id, [], [t], [Path(f"/tmp/ac/{run_id}.sock")], [])
    derived = frozenset(manifest.derived_codex_sockets(layout, m))
    link_target = backends.CODEX_DAEMON_SOCK_DIR / hashlib.sha256(f"/tmp/ac/{run_id}.sock".encode()).hexdigest()
    assert manifest.socket_removable(link_target, layout, derived)
    assert manifest.socket_removable(backends.codex_daemon_socket(home), layout, derived)
    assert not manifest.socket_removable(backends.CODEX_DAEMON_SOCK_DIR / ("e" * 64), layout, derived)


@pytest.mark.skipif(shutil.which("bun") is None, reason="bun not installed")
def test_channel_server_builds_with_bun(tmp_path):
    server = Path(__file__).resolve().parents[1] / "agentcomms" / "channel" / "server.ts"
    out = subprocess.run(["bun", "build", str(server), "--target=bun", "--outdir", str(tmp_path)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert (tmp_path / "server.js").exists()


def test_claude_bg_daemon_dir_is_per_config_dir(tmp_path):
    from agentcomms.hosts import claude_bg

    runs = tmp_path / "runs"
    home = runs / "r" / "home" / "claude"
    home.mkdir(parents=True)
    expected = hashlib.sha256(str(home).encode()).hexdigest()[:8]
    assert claude_bg.daemon_sock_dir(home, uid=501) == Path("/tmp/cc-daemon-501") / expected
    assert claude_bg.shared_daemon_problem(home, tmp_path / "user", runs) is None
    assert "not under" in claude_bg.shared_daemon_problem(tmp_path / "user" / ".claude", tmp_path / "user", runs)


def test_claude_bg_argv_and_id_parsing():
    from agentcomms.hosts import claude_bg

    assert claude_bg.bg_argv("claude", "haiku")[:4] == ["claude", "--bg", "--model", "haiku"]
    assert claude_bg.attach_argv("claude", "ab12") == ["claude", "attach", "ab12"]
    assert claude_bg.parse_bg_id("Started.\nOpen it with: claude attach ab12cd\n") == "ab12cd"


def server_frame(payload: bytes, opcode: int = 1, fin: bool = True) -> bytes:
    return bytes([(0x80 if fin else 0) | opcode, len(payload)]) + payload


class FakeSock:
    def __init__(self, chunks: list[bytes]):
        self.chunks = list(chunks)
        self.sent: list[bytes] = []

    def settimeout(self, value):
        pass

    def recv(self, n):
        if not self.chunks:
            raise TimeoutError("no data")
        return self.chunks.pop(0)

    def sendall(self, data):
        self.sent.append(data)


def fake_client(chunks: list[bytes], timeout_s: float = 1.0) -> codex_remote.Client:
    client = codex_remote.Client.__new__(codex_remote.Client)
    client.sock, client.buf, client.next_id, client.timeout_s = FakeSock(chunks), b"", 1, timeout_s
    return client


def unmask(frame: bytes) -> dict:
    n, pos = frame[1] & 0x7F, 2
    if n == 126:
        n, pos = int.from_bytes(frame[2:4]), 4
    mask = frame[pos:pos + 4]
    return json.loads(bytes(b ^ mask[i % 4] for i, b in enumerate(frame[pos + 4:pos + 4 + n])))


def test_websocket_recv_reassembles_fragmented_messages():
    body = json.dumps({"id": 1, "result": {"data": ["t"]}}).encode()
    client = fake_client([server_frame(body[:10], 1, fin=False) + server_frame(body[10:], 0, fin=True)])
    assert client.recv(time.monotonic() + 1) == {"id": 1, "result": {"data": ["t"]}}


def test_call_rejects_server_requests_and_returns_its_own_reply():
    request = json.dumps({"id": 77, "method": "item/tool/requestUserInput", "params": {}}).encode()
    reply = json.dumps({"id": 1, "result": {"ok": True}}).encode()
    client = fake_client([server_frame(request), server_frame(reply)])
    assert client.call(lambda i: codex_remote.rpc_request(i, "thread/read", {})) == {"ok": True}
    answered = unmask(client.sock.sent[1])
    assert answered["id"] == 77 and answered["error"]["code"] == -32601


def test_call_has_an_overall_deadline_despite_notifications():
    note = server_frame(json.dumps({"method": "thread/status/changed", "params": {}}).encode())
    client = fake_client([note] * 1000, timeout_s=0.0)
    with pytest.raises(TimeoutError, match="deadline"):
        client.call(lambda i: codex_remote.rpc_request(i, "thread/read", {}))


def test_drain_delivers_spooled_messages_in_send_order(tmp_path):
    spool = tmp_path / "deferred" / "thread"
    for i, text in enumerate(["one", "two", "three"]):
        codex_remote.enqueue(spool, text, 1000 + i)
    delivered, lines = [], []
    assert codex_remote.drain(spool, lambda text: delivered.append(text) or "turn/start t", lines.append) == 3
    assert delivered == ["one", "two", "three"]
    assert [line.split()[2] for line in lines] == ["ok", "ok", "ok"]
    assert codex_remote.pending(spool) is False


def test_concurrent_drainers_deliver_each_message_once_in_order(tmp_path):
    spool = tmp_path / "spool"
    for i in range(6):
        codex_remote.enqueue(spool, f"m{i}", 2000 + i)
    delivered = []

    def slow(text):
        time.sleep(0.02)
        delivered.append(text)
        return "ok"

    threads = [threading.Thread(target=codex_remote.drain, args=(spool, slow, lambda line: None)) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert delivered == [f"m{i}" for i in range(6)]


def test_a_running_drainer_holds_the_spool_lock(tmp_path):
    spool = tmp_path / "spool"
    codex_remote.enqueue(spool, "first", 1)
    seen = []

    def deliver(text):
        seen.append(codex_remote.drainer_running(spool))
        return "ok"

    codex_remote.drain(spool, deliver, lambda line: None)
    assert seen == [True]
    assert codex_remote.drainer_running(spool) is False


def test_drain_logs_a_failed_delivery_and_continues(tmp_path):
    spool = tmp_path / "spool"
    codex_remote.enqueue(spool, "bad", 1)
    codex_remote.enqueue(spool, "good", 2)
    lines = []

    def deliver(text):
        if text == "bad":
            raise RuntimeError("turn already running")
        return "turn/start t2"

    codex_remote.drain(spool, deliver, lines.append)
    assert [line.split(" ", 3)[2:] for line in lines] == [["error", "RuntimeError: turn already running"],
                                                          ["ok", "turn/start t2"]]


def test_deferred_log_summary_counts_outcomes():
    from agentcomms.scenarios.common import deferred_summary

    log = "1.0 a.msg ok turn/start t1\n2.0 b.msg error RuntimeError: x\n3.0 c.msg ok turn/start t3\n"
    assert deferred_summary(log) == "deferred=2/3"


def run_manifest_dict(tmp_path: Path, pid: int, idents: dict[str, str] | None, **extra) -> dict:
    run_dir = tmp_path / "runs" / "20261025-000000-abcd"
    home = run_dir / "home" / "claude"
    home.mkdir(parents=True)
    data = {"run_id": run_dir.name, "pgids": [], "sockets": [], "backends": [],
            "targets": [{"agent": "claude", "agent_pid": pid, "home_dir": str(home), "backend_ref": None}], **extra}
    if idents is not None:
        data["identities"] = idents
    (run_dir / "manifest.json").write_text(json.dumps(data))
    return data


def test_sender_guard_accepts_a_live_target_with_its_recorded_identity(tmp_path):
    data = run_manifest_dict(tmp_path, 4242, {"4242": "id-1"})
    home = Path(data["targets"][0]["home_dir"])
    assert guard.check_claude_target(data, home, 4242, {4242: "id-1"})["agent_pid"] == 4242


@pytest.mark.parametrize("idents,current,why", [
    (None, {4242: "id-1"}, "not the process"),
    ({"4242": "id-1"}, {4242: "id-other"}, "not the process"),
    ({"4242": "id-1"}, {}, "not the process"),
])
def test_sender_guard_refuses_legacy_reused_or_dead_pids(tmp_path, idents, current, why):
    data = run_manifest_dict(tmp_path, 4242, idents)
    with pytest.raises(guard.GuardError, match=why):
        guard.check_claude_target(data, Path(data["targets"][0]["home_dir"]), 4242, current)


def test_sender_guard_refuses_a_pid_that_is_not_a_target(tmp_path):
    data = run_manifest_dict(tmp_path, 4242, {"4242": "id-1"})
    with pytest.raises(guard.GuardError, match="is not a target"):
        guard.check_claude_target(data, Path(data["targets"][0]["home_dir"]), 999, {999: "id-1"})


def test_claude_sender_refuses_a_config_dir_outside_runs(tmp_path, capsys):
    os.makedirs(tmp_path / "user" / ".claude" / "sessions")
    assert claude_uds.main(["--config-dir", str(tmp_path / "user" / ".claude"), "--pid", str(os.getpid())]) == 2
    assert "is not inside the harness runs dir" in capsys.readouterr().err


def test_claude_sender_refuses_a_run_without_a_manifest(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(claude_uds.guard, "RUNS", tmp_path / "runs")
    home = tmp_path / "runs" / "20261025-000000-abcd" / "home" / "claude"
    home.mkdir(parents=True)
    assert claude_uds.main(["--config-dir", str(home), "--pid", "4242"]) == 2
    assert "no harness manifest" in capsys.readouterr().err


def test_codex_queue_sender_requires_an_owned_codex_home(tmp_path, capsys):
    with pytest.raises(SystemExit):
        codex_queue.main(["--thread", "01a1735e-88cb-7e91-9a5c-98ca2def0048"])
    assert codex_queue.main(["--codex-home", str(tmp_path / ".codex"),
                             "--thread", "01a1735e-88cb-7e91-9a5c-98ca2def0048"]) == 2
    assert "is not inside the harness runs dir" in capsys.readouterr().err


def test_codex_home_guard_needs_a_live_harness_daemon(tmp_path):
    run_dir = tmp_path / "runs" / "20261025-000000-abcd"
    home = run_dir / "home" / "codex"
    data = {"run_id": run_dir.name, "targets": [{"agent": "codex", "home_dir": str(home)}],
            "backends": ["codex-daemon:500"], "identities": {"500": "d-1"}}
    guard.check_codex_home(data, home, {500: "d-1"})
    with pytest.raises(guard.GuardError, match="no running harness codex daemon"):
        guard.check_codex_home(data, home, {500: "reused"})


def test_codex_remote_sender_refuses_a_foreign_socket(capsys):
    assert codex_remote.main(["--socket", "/private/tmp/codex-daemon-501/" + "e" * 64, "--thread", "t"]) == 2
    assert "is not a harness socket" in capsys.readouterr().err


def test_codex_socket_guard_needs_the_targets_live_app_server(tmp_path):
    sock = "/tmp/ac/20261025-000000-abcd.sock"
    data = {"run_id": "20261025-000000-abcd", "targets": [{"agent": "codex", "backend_ref": sock}],
            "backends": ["codex-app-server:600"], "identities": {"600": "a-1"}}
    guard.check_codex_socket(data, Path(sock), {600: "a-1"})
    with pytest.raises(guard.GuardError, match="no running harness codex app server"):
        guard.check_codex_socket(data, Path(sock), {})


def test_unix_sender_only_writes_to_sockets_listed_in_their_run(tmp_path, monkeypatch, capsys):
    run_dir = tmp_path / "runs" / "20261025-000000-abcd"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(json.dumps({"run_id": run_dir.name,
                                                       "sockets": ["/tmp/ac/20261025-000000-abcd-ch.sock"]}))
    assert guard.owned_run_socket(Path("/tmp/ac/20261025-000000-abcd-ch.sock"), tmp_path / "runs")["run_id"] == \
        run_dir.name
    with pytest.raises(guard.GuardError, match="is not a socket of run"):
        guard.owned_run_socket(Path("/tmp/ac/20261025-000000-abcd-relay.sock"), tmp_path / "runs")
    assert unix_send.main(["--socket", "/tmp/cc-socks/1.sock"]) == 2
    assert "is not a harness socket" in capsys.readouterr().err


def test_process_identity_parses_ps_lstart_and_accounting_name():
    out = " 4242 Sun Oct 25 09:34:44 2026     zsh\n  77 Sat Oct  4 06:33:44 2026     Claude Helper (R\n"
    parsed = guard.parse_identities(out)
    assert parsed == {4242: guard.identity("Sun Oct 25 09:34:44 2026", "zsh"),
                      77: guard.identity("Sat Oct 4 06:33:44 2026", "Claude Helper (R")}


def test_identity_survives_an_argv0_rewrite(tmp_path):
    proc = subprocess.Popen(["perl", "-e", 'select(undef, undef, undef, 0.5); $0 = "renamed-xyz"; sleep 30'])
    try:
        time.sleep(0.1)
        before = guard.identities({proc.pid})
        time.sleep(1.0)
        renamed = subprocess.run(["ps", "-o", "comm=", "-p", str(proc.pid)], capture_output=True, text=True)
        assert "renamed-xyz" in renamed.stdout
        assert guard.identities({proc.pid}) == before
    finally:
        proc.kill()
        proc.wait()


def test_identity_of_this_process_is_stable():
    first = guard.identities({os.getpid()})
    assert first and guard.identities({os.getpid()}) == first


def test_missing_peer_key_is_a_rejected_send(tmp_path, monkeypatch):
    data = run_manifest_dict(tmp_path, 4242, {"4242": "id-1"})
    home = Path(data["targets"][0]["home_dir"])
    (home / "sessions").mkdir(parents=True)
    (home / "sessions" / "4242.json").write_text(json.dumps({"messagingSocketPath": "/tmp/cc-socks/4242.sock"}))
    monkeypatch.setattr(claude_uds.guard, "identities", lambda pids: {4242: "id-1"})
    receipt = ClaudeUds().send(replace(target(tmp_path), home_dir=home), "hi")
    assert receipt.accepted is False and "no peer key for pid 4242" in receipt.detail


def test_in_process_claude_send_refuses_a_pid_the_run_does_not_own(tmp_path, monkeypatch):
    data = run_manifest_dict(tmp_path, 4242, {"4242": "id-1"})
    home = Path(data["targets"][0]["home_dir"])
    monkeypatch.setattr(claude_uds.guard, "identities", lambda pids: {4242: "someone-else"})
    receipt = ClaudeUds().send(replace(target(tmp_path), home_dir=home), "hi")
    assert receipt.accepted is False and "not the process run" in receipt.detail


def test_launch_sockets_are_declared_for_cleanup(tmp_path):
    t = target(tmp_path)
    assert ClaudeChannel().run_sockets(t.work_dir) == [Path("/tmp/ac/20261025-000000-abcd-ch.sock")]
    assert ClaudeUdsChild().run_sockets(t.work_dir) == [Path("/tmp/ac/20261025-000000-abcd-relay.sock")]
    assert ClaudeUds().run_sockets(t.work_dir) == []


def test_codex_sender_argv_waits_for_a_thread_id(tmp_path, fake_pinned):
    from dataclasses import replace

    from agentcomms.adapters.codex_queue import CodexQueue

    t = target(tmp_path, "codex")
    assert CodexQueue().sender_argv(t) is None and CodexRemoteStart().sender_argv(t) is None
    thread = "01a1735e-88cb-7e91-9a5c-98ca2def0048"
    assert CodexQueue().sender_argv(replace(t, session_id=thread))[-2:] == ["--thread", thread]
    assert CodexRemoteStart().sender_argv(replace(t, session_id=thread))[-4:] == ["--thread", thread, "--mode",
                                                                                  "start"]


def test_owned_thread_prefers_the_only_loaded_thread_then_the_rollout(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from agentcomms.adapters import codex_remote as remote_adapter

    t = target(tmp_path, "codex")
    monkeypatch.setattr(remote_adapter, "loaded_threads", lambda sock: ["only"])
    assert remote_adapter.owned_thread(Path("/s"), t) == "only"
    monkeypatch.setattr(remote_adapter, "loaded_threads", lambda sock: ["a", "b"])
    monkeypatch.setattr(remote_adapter.CodexTranscript, "locate",
                        staticmethod(lambda home, work, sid: SimpleNamespace(session_id=lambda: "b")))
    assert remote_adapter.owned_thread(Path("/s"), t) == "b"
    monkeypatch.setattr(remote_adapter.CodexTranscript, "locate", staticmethod(lambda home, work, sid: None))
    with pytest.raises(remote_adapter.ThreadError, match="found 2 loaded"):
        remote_adapter.owned_thread(Path("/s"), t)


def codex_spec(tmp_path: Path, env: dict[str, str]) -> backends.BackendSpec:
    return backends.BackendSpec("codex-daemon", ["codex", "app-server", "daemon", "start"], env, str(tmp_path),
                                None, str(tmp_path / "backend.log"))


def test_daemon_commands_refuse_a_spec_without_an_isolated_codex_home(tmp_path, monkeypatch):
    run_dir = tmp_path / "runs" / "r"
    (run_dir / "home" / "codex").mkdir(parents=True)
    ran = []
    monkeypatch.setattr(backends.subprocess, "run", lambda *a, **k: ran.append(a))
    with pytest.raises(IsolationError, match="no CODEX_HOME"):
        backends.run_daemon_command(codex_spec(tmp_path, {"HOME": "/Users/me"}), "stop", run_dir, tmp_path / "user")
    with pytest.raises(IsolationError, match="is not under"):
        backends.run_daemon_command(codex_spec(tmp_path, {"CODEX_HOME": str(tmp_path / "user" / ".codex")}), "stop",
                                    run_dir, tmp_path / "user")
    assert ran == []


def test_backends_without_an_isolation_check_are_refused(tmp_path):
    spec = backends.BackendSpec("droid-daemon", ["droid", "daemon"], {}, str(tmp_path), None, "log")
    assert backends.spec_problem(spec, tmp_path / "runs" / "r", tmp_path) == \
        "no isolation check for backend kind droid-daemon"


def test_isolated_app_server_spec_passes(tmp_path):
    run_dir = tmp_path / "runs" / "r"
    home = run_dir / "home" / "codex"
    home.mkdir(parents=True)
    spec = backends.BackendSpec("codex-app-server", ["codex", "app-server"], {"CODEX_HOME": str(home)},
                                str(tmp_path), None, "log")
    assert backends.spec_problem(spec, run_dir, tmp_path / "user") is None


def test_restart_measures_downtime_from_before_the_stop(tmp_path, monkeypatch):
    run_dir = tmp_path / "runs" / "r"
    home = run_dir / "home" / "codex"
    home.mkdir(parents=True)
    backends.save_spec(run_dir, codex_spec(tmp_path, {"CODEX_HOME": str(home)}))
    backends.pid_path(run_dir).write_text("100\n")
    calls = []
    monkeypatch.setattr(backends, "owned_backend", lambda rd, pid: True)
    monkeypatch.setattr(backends.procs, "alive", lambda pid: not calls)
    monkeypatch.setattr(backends.procs, "identities", lambda pids: {p: f"started-{p}" for p in pids})
    monkeypatch.setattr(backends, "stop", lambda spec, pid, rd, uh: calls.append(("stop", pid)))
    monkeypatch.setattr(backends, "start", lambda spec, rd, uh: calls.append(("start",)) or 200)
    ticks = iter([1000.0, 1033.5, 1034.0])
    new_pid, detail = backends.restart(run_dir, tmp_path / "user", clock=lambda: next(ticks))
    assert (new_pid, calls) == (200, [("stop", 100), ("start",)])
    assert detail == "codex-daemon graceful stop+start, pid 100 -> 200; stop 33.5s + start 0.5s = down 34.0s"
    assert backends.current_pid(run_dir) == 200


@pytest.mark.skipif(shutil.which("bun") is None, reason="bun not installed")
def test_channel_server_decodes_a_multibyte_char_split_across_reads(tmp_path):
    server = Path(__file__).resolve().parents[1] / "agentcomms" / "channel" / "server.ts"
    os.makedirs("/tmp/ac", exist_ok=True)
    path = f"/tmp/ac/test-{os.getpid()}-ch.sock"
    env = {**os.environ, "AGENTCOMMS_CHANNEL_SOCKET": path, "AGENTCOMMS_CHANNEL_LOG": str(tmp_path / "ch.log")}
    proc = subprocess.Popen(["bun", "run", str(server)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)
    try:
        proc.stdin.write(b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n')
        proc.stdin.flush()
        init = json.loads(proc.stdout.readline())
        assert init["result"]["capabilities"]["experimental"] == {"claude/channel": {}}
        assert backends.wait_socket(Path(path), 10.0)
        body = "tab\there \U0001f600 café `$HOME`".encode()
        cut = body.index("\U0001f600".encode()) + 2
        s = socket.socket(socket.AF_UNIX)
        s.connect(path)
        s.sendall(body[:cut])
        time.sleep(0.3)
        s.sendall(body[cut:])
        s.shutdown(socket.SHUT_WR)
        assert s.recv(100) == b"emitted\n"
        s.close()
        pushed = json.loads(proc.stdout.readline())
        assert pushed["method"] == "notifications/claude/channel"
        assert pushed["params"] == {"content": body.decode(), "meta": {"sender": "agentcomms"}}
    finally:
        proc.stdin.close()
        proc.wait(10)
    assert not os.path.exists(path)


def test_an_active_thread_whose_turn_is_not_listed_yet_counts_as_busy():
    active = json.dumps({"id": 1, "result": {"thread": {"status": {"type": "active"}}}}).encode()
    not_ready = json.dumps({"id": 2, "error": {"message": "thread not materialized yet"}}).encode()
    client = fake_client([server_frame(active), server_frame(not_ready)])
    assert client.busy_turn("th") == codex_remote.TURN_STARTING


def test_a_thread_whose_first_rollout_is_still_empty_counts_as_busy():
    empty = json.dumps({"id": 1, "error": {"message": "failed to read thread: rollout at x.jsonl is empty"}}).encode()
    assert fake_client([server_frame(empty)]).busy_turn("th") == codex_remote.TURN_STARTING


def test_bg_probe_verdicts(tmp_path):
    from agentcomms.hosts import claude_bg

    expected = claude_bg.daemon_sock_dir(tmp_path / "home")
    clean = claude_bg.ProbeState({"/u/.claude/daemon": 1.0}, set())
    started = claude_bg.ProbeState({"/u/.claude/daemon": 1.0}, {expected.name})
    assert claude_bg.probe_verdict("", clean, started, expected)[0] == "started"
    elsewhere = claude_bg.ProbeState({"/u/.claude/daemon": 1.0}, {"deadbeef"})
    assert claude_bg.probe_verdict("", clean, elsewhere, expected)[0] == "unusable"
    touched = claude_bg.ProbeState({"/u/.claude/daemon": 2.0}, set())
    assert claude_bg.probe_verdict("", clean, touched, expected) == (
        "unusable", "the user's ~/.claude/daemon changed: /u/.claude/daemon")
    disabled = "claude daemon: background agents disabled (3P/opt-out)"
    assert claude_bg.probe_verdict(disabled, clean, clean, expected)[0] == "untested"


def test_bg_start_times_are_parsed_as_utc():
    from agentcomms.hosts import claude_bg

    assert claude_bg.parse_utc_lstart("Sun Oct 25 09:34:44 2026") == 1792920884.0


def app_server_run(tmp_path: Path, pid: int, ident: str) -> tuple[Path, backends.BackendSpec]:
    run_dir = tmp_path / "runs" / "r"
    home = run_dir / "home" / "codex"
    home.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(json.dumps({"run_id": "r", "backends": [f"codex-app-server:{pid}"],
                                                       "identities": {str(pid): ident}}))
    spec = backends.BackendSpec("codex-app-server", ["codex", "app-server"], {"CODEX_HOME": str(home)},
                                str(tmp_path), None, str(tmp_path / "backend.log"))
    return run_dir, spec


def test_stop_signals_a_backend_group_only_while_its_identity_matches(tmp_path, monkeypatch):
    run_dir, spec = app_server_run(tmp_path, 4321, "started-then")
    signalled = []
    monkeypatch.setattr(backends.os, "killpg", lambda pid, sig: signalled.append((pid, sig)))
    monkeypatch.setattr(backends.procs, "alive", lambda pid: True)
    monkeypatch.setattr(backends.procs, "identities", lambda pids: {4321: "reused-by-someone-else"})
    backends.stop(spec, 4321, run_dir, tmp_path / "user")
    assert signalled == []
    monkeypatch.setattr(backends.procs, "identities", lambda pids: {4321: "started-then"})
    monkeypatch.setattr(backends.procs, "alive", lambda pid: not signalled)
    backends.stop(spec, 4321, run_dir, tmp_path / "user")
    assert signalled[0] == (4321, signal.SIGTERM)


def test_restart_of_a_reused_pid_signals_nothing_and_fails(tmp_path, monkeypatch):
    run_dir, spec = app_server_run(tmp_path, 4321, "started-then")
    backends.save_spec(run_dir, spec)
    backends.pid_path(run_dir).write_text("4321\n")
    signalled, started = [], []
    monkeypatch.setattr(backends.os, "killpg", lambda pid, sig: signalled.append((pid, sig)))
    monkeypatch.setattr(backends.procs, "alive", lambda pid: True)
    monkeypatch.setattr(backends.procs, "identities", lambda pids: {4321: "reused-by-someone-else"})
    monkeypatch.setattr(backends, "start", lambda spec, rd, uh: started.append(1) or 5555)
    with pytest.raises(backends.BackendError, match="not running as the run's backend"):
        backends.restart(run_dir, tmp_path / "user")
    assert (signalled, started) == ([], [])


def test_unknown_thread_errors_are_not_mistaken_for_a_busy_thread():
    unknown = json.dumps({"id": 1, "error": {"message": "thread not found: 0000"}}).encode()
    with pytest.raises(RuntimeError, match="thread not found"):
        fake_client([server_frame(unknown)]).busy_turn("th")


def test_drain_dir_must_be_the_sockets_own_run_and_thread_spool(tmp_path):
    runs = tmp_path / "runs"
    sock = Path("/tmp/ac/20261025-000000-abcd.sock")
    own = runs / "20261025-000000-abcd" / "deferred" / "th-1"
    assert codex_remote.drain_spool(sock, "th-1", own, runs) == own.resolve()
    with pytest.raises(codex_remote.guard.GuardError, match="spool"):
        codex_remote.drain_spool(sock, "th-1", runs / "20261025-111111-ffff" / "deferred" / "th-1", runs)
    with pytest.raises(codex_remote.guard.GuardError, match="spool"):
        codex_remote.drain_spool(sock, "th-1", runs / "20261025-000000-abcd" / "deferred" / "th-2", runs)
    with pytest.raises(codex_remote.guard.GuardError, match="plain id"):
        codex_remote.drain_spool(sock, "..", runs / "20261025-000000-abcd", runs)


def test_a_drainer_that_cannot_start_logs_the_cause_for_every_spooled_message(tmp_path, capsys):
    spool = tmp_path / "spool"
    codex_remote.enqueue(spool, "a", 1)
    codex_remote.enqueue(spool, "b", 2)
    assert codex_remote.fail_spool(spool, ConnectionRefusedError("no app server")) == 2
    lines = capsys.readouterr().out.splitlines()
    assert [line.split(" ", 3)[2:] for line in lines] == [
        ["error", "RuntimeError: drainer could not start: ConnectionRefusedError: no app server"]] * 2


def test_pending_spooled_messages_are_noted_at_finish(tmp_path):
    from agentcomms.scenarios.common import deferred_notes

    codex_remote.enqueue(tmp_path / "deferred" / "th", "late", 1)
    (tmp_path / "deferred.log").write_text("1.0 a.msg ok turn/start t1\n")
    assert deferred_notes(tmp_path) == ["deferred=1/1", "deferred-pending=1"]


def test_unix_send_survives_a_server_that_replies_and_closes_before_the_client_shuts_down(tmp_path):
    os.makedirs("/tmp/ac", exist_ok=True)
    path = f"/tmp/ac/test-fast-{os.getpid()}.sock"
    server = socket.socket(socket.AF_UNIX)
    server.bind(path)
    server.listen(8)

    def serve():
        for _ in range(300):
            conn, _ = server.accept()
            conn.recv(100)
            conn.sendall(b"emitted\n")
            conn.close()

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        replies = [unix_send.send(path, b"body") for _ in range(300)]
    finally:
        thread.join(5)
        server.close()
        os.unlink(path)
    assert replies == ["emitted"] * 300
