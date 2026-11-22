import json
from datetime import UTC, datetime
from pathlib import Path

from agentcomms.transcripts.claude import ClaudeTranscript, encode_cwd, transcript_path
from agentcomms.transcripts.codex import CodexTranscript, find_rollout


def write_rollout(path: Path, source: Path, cwd: str, session_id: str, thread_source: str = "user") -> Path:
    lines = source.read_text().splitlines()
    first = json.loads(lines[0])
    first["payload"] |= {"cwd": cwd, "id": session_id, "thread_source": thread_source}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([json.dumps(first), *lines[1:]]) + "\n")
    return path


def test_codex_rollout_lookup_matches_session_meta_cwd(tmp_path, fixtures):
    src = fixtures / "codex" / "s1-probe.jsonl"
    sessions = tmp_path / "sessions" / "2026" / "10" / "24"
    work = tmp_path / "work" / "codex"
    work.mkdir(parents=True)
    write_rollout(sessions / "rollout-2026-10-24T07-00-00-a.jsonl", src, "/elsewhere/one", "a")
    wanted = write_rollout(sessions / "rollout-2026-10-24T07-05-00-b.jsonl", src, str(work), "b")
    write_rollout(sessions / "rollout-2026-10-24T07-09-00-c.jsonl", src, "/elsewhere/two", "c")
    write_rollout(sessions / "rollout-2026-10-24T07-10-00-d.jsonl", src, str(work), "d", "subagent")
    assert find_rollout(tmp_path / "sessions", work) == wanted
    assert CodexTranscript.locate(tmp_path, work).session_id() == "b"


def test_codex_parser_extracts_probe_entries(fixtures):
    t = CodexTranscript(fixtures / "codex" / "s1-probe.jsonl")
    kinds = [k for _, k, _ in t.entries()]
    user = [text for _, k, text in t.entries() if k == "user"]
    assert user == ['ACK-REQUEST cafef00d: reply with exactly "ACK cafef00d". probe']
    assert [text for _, k, text in t.entries() if k == "assistant"] == ["ACK cafef00d"]
    assert kinds[0] == "system"
    assert t.is_idle() is True


def test_codex_finds_token_in_peer_message(fixtures):
    t = CodexTranscript(fixtures / "codex" / "peer.jsonl")
    assert [k for _, k, _ in t.find_token("1234abcd")] == ["peer", "assistant"]
    assert [k for _, k, _ in t.entries()][2:4] == ["tool_use", "tool_result"]


def test_claude_parser_extracts_probe_entries(fixtures):
    t = ClaudeTranscript(fixtures / "claude" / "s1-probe.jsonl")
    assert [(k, text) for _, k, text in t.entries()] == [
        ("user", 'ACK-REQUEST deadbeef: reply with exactly "ACK deadbeef". probe'),
        ("assistant", "ACK deadbeef"),
        ("system", "end_turn"),
    ]
    start = datetime(2026, 10, 24, 12, 11, 10, tzinfo=UTC).timestamp()
    assert start <= t.entries()[0][0] < start + 1


def test_claude_finds_token_in_wrapped_peer_message(fixtures):
    t = ClaudeTranscript(fixtures / "claude" / "peer.jsonl")
    assert [k for _, k, _ in t.find_token("0badf00d")] == ["queue", "peer", "assistant"]
    assert t.is_idle() is True


def test_claude_transcript_path_encodes_cwd(tmp_path):
    cwd = Path("/Users/me/wrksp/_scratch/agent-comms/runs/r1/work/claude")
    assert encode_cwd(cwd) == "-Users-me-wrksp--scratch-agent-comms-runs-r1-work-claude"
    assert transcript_path(tmp_path, cwd, "sid") == tmp_path / "projects" / encode_cwd(cwd) / "sid.jsonl"


def test_claude_api_error_record_becomes_api_error_entry():
    from agentcomms.transcripts.claude import parse_record
    record = {"type": "assistant", "isApiErrorMessage": True, "timestamp": "2026-10-24T12:00:00Z",
              "message": {"content": [{"type": "text", "text": "API Error: 429 rate limited"}]}}
    assert [(k, t) for _, k, t in parse_record(record)] == [("api_error", "API Error: 429 rate limited")]


def test_codex_error_event_becomes_api_error_entry():
    from agentcomms.transcripts.codex import parse_record
    record = {"type": "event_msg", "timestamp": "2026-10-24T12:00:00Z",
              "payload": {"type": "error", "message": "usage limit reached"}}
    assert [(k, t) for _, k, t in parse_record(record)] == [("api_error", "usage limit reached")]


def test_claude_is_idle_after_compact_and_its_local_command_echoes(fixtures):
    from agentcomms.transcripts.claude import ClaudeTranscript
    assert ClaudeTranscript(fixtures / "claude" / "s10-compact.jsonl").is_idle() is True
