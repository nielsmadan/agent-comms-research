import json
from pathlib import Path

from agentcomms.transcripts.common import (
    Entry,
    content_text,
    first_record,
    match_token,
    newest_session,
    parse_ts,
    read_jsonl,
)

BUSY_STOP_REASONS = ("toolUse", "pending", "deferred")
TURN_MARKER = "agentcomms-turn"


def session_header(path: Path) -> dict | None:
    return first_record(path, "session")


def find_session_file(session_dir: Path, cwd: Path, session_id: str | None = None) -> Path | None:
    headers = [(session_header(path), path) for path in session_dir.glob("*.jsonl")]
    return newest_session([(h.get("timestamp", ""), h, path) for h, path in headers if h], cwd, session_id)


def _assistant_entries(ts: float, message: dict) -> list[Entry]:
    entries = []
    for block in message.get("content") or []:
        if block.get("type") == "text":
            entries.append((ts, "assistant", block.get("text", "")))
        elif block.get("type") == "toolCall":
            entries.append((ts, "tool_use", json.dumps(block.get("arguments", {}))))
    if message.get("stopReason") == "error":
        entries.append((ts, "api_error", str(message.get("errorMessage") or "error")))
    return entries


def parse_message(ts: float, message: dict) -> list[Entry]:
    match message.get("role"):
        case "user":
            return [(ts, "user", content_text(message.get("content")))]
        case "assistant":
            return _assistant_entries(ts, message)
        case "toolResult":
            return [(ts, "tool_result", content_text(message.get("content")))]
        case "custom":
            return [(ts, "custom", content_text(message.get("content")))]
        case "bashExecution":
            return [(ts, "tool_result", f"{message.get('command', '')}\n{message.get('output', '')}")]
        case "branchSummary" | "compactionSummary":
            return [(ts, "system", str(message.get("summary", "")))]
    return []


def parse_record(record: dict) -> list[Entry]:
    ts = parse_ts(record.get("timestamp"))
    match record.get("type"):
        case "message":
            return parse_message(ts, record.get("message") or {})
        case "custom_message":
            return [(ts, "custom", content_text(record.get("content")))]
        case "custom":
            return [(ts, "custom", json.dumps(record.get("data")))]
        case "compaction" | "branch_summary":
            return [(ts, "system", str(record.get("summary", "")))]
    return []


def idle_from_records(records: list[dict]) -> bool | None:
    for record in reversed(records):
        if record.get("type") == "custom" and record.get("customType") == TURN_MARKER:
            return (record.get("data") or {}).get("state") == "idle"
        if record.get("type") == "custom_message":
            return None
        if record.get("type") != "message":
            continue
        message = record.get("message") or {}
        role = message.get("role")
        if role == "assistant":
            return message.get("stopReason") not in BUSY_STOP_REASONS
        if role in ("user", "toolResult", "custom", "bashExecution"):
            return False
    return None


class PiTranscript:
    def __init__(self, path: Path):
        self.path = path

    @classmethod
    def locate(cls, session_dir: Path, cwd: Path, session_id: str | None = None) -> PiTranscript | None:
        path = find_session_file(session_dir, cwd, session_id)
        return cls(path) if path else None

    def records(self) -> list[dict]:
        return read_jsonl(self.path)

    def session_id(self) -> str | None:
        header = session_header(self.path)
        return header.get("id") if header else None

    def entries(self) -> list[Entry]:
        return [e for r in self.records() for e in parse_record(r)]

    def find_token(self, token: str) -> list[Entry]:
        return match_token(self.entries(), token)

    def is_idle(self) -> bool | None:
        return idle_from_records(self.records())
