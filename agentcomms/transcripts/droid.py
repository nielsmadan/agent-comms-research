import json
import re
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

HIDDEN_VISIBILITY = ("llm_only", "hidden", "user_only")
REMINDER = "<system-reminder>"


def cwd_slug(cwd: Path) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", str(cwd))


def session_start(path: Path) -> dict | None:
    return first_record(path, "session_start")


def sessions_dirs(home: Path) -> list[Path]:
    return [home / ".factory" / "sessions", home / "sessions"]


def find_session_file(home: Path, cwd: Path, session_id: str | None = None) -> Path | None:
    candidates = [p for root in sessions_dirs(home) for p in (root / cwd_slug(cwd.resolve())).glob("*.jsonl")]
    if not candidates:
        candidates = [p for root in sessions_dirs(home) for p in root.glob("*/*.jsonl")]
    starts = [(session_start(path), path) for path in candidates]
    return newest_session([(path.stat().st_mtime, s, path) for s, path in starts if s], cwd, session_id)


def _hook_text(message: dict) -> str:
    results = message.get("hookResults") or []
    outputs = [str(r.get("stdout", "")) + str(r.get("stderr", "")) for r in results if isinstance(r, dict)]
    return "\n".join([f"hook:{message.get('hookEventName')}", *outputs])


def _user_kind(message: dict, text: str) -> str:
    if message.get("visibility") in HIDDEN_VISIBILITY or text.lstrip().startswith(REMINDER):
        return "system"
    return "user"


def _user_entries(ts: float, message: dict) -> list[Entry]:
    if message.get("hookEventName"):
        return [(ts, "system", _hook_text(message))]
    entries = []
    for block in message.get("content") or []:
        if block.get("type") == "text":
            entries.append((ts, _user_kind(message, block.get("text", "")), block.get("text", "")))
        elif block.get("type") == "tool_result":
            entries.append((ts, "tool_result", content_text(block.get("content"))))
    return entries


def _assistant_entries(ts: float, message: dict) -> list[Entry]:
    entries = []
    for block in message.get("content") or []:
        if block.get("type") == "text":
            entries.append((ts, "assistant", block.get("text", "")))
        elif block.get("type") == "tool_use":
            entries.append((ts, "tool_use", json.dumps(block.get("input", {}))))
    return entries


def parse_record(record: dict, ts: float = 0.0) -> list[Entry]:
    ts = parse_ts(record["timestamp"]) if record.get("timestamp") else ts
    rtype = record.get("type")
    if rtype == "message":
        message = record.get("message") or {}
        if message.get("role") == "user":
            return _user_entries(ts, message)
        if message.get("role") == "assistant":
            return _assistant_entries(ts, message)
        return []
    if rtype == "agent_turn_outcome":
        reason = str(record.get("reason", ""))
        kind = "api_error" if "error" in reason or "fail" in reason else "system"
        return [(ts, kind, f"turn_outcome:{reason}")]
    return []


def parse_records(records: list[dict]) -> list[Entry]:
    entries: list[Entry] = []
    for record in records:
        last_ts = entries[-1][0] if entries else 0.0
        entries.extend(parse_record(record, last_ts))
    return entries


def is_turn_input(record: dict) -> bool:
    message = record.get("message") or {}
    if record.get("type") != "message" or message.get("role") != "user" or message.get("hookEventName"):
        return False
    return any(k == "user" for _, k, _ in _user_entries(0.0, message))


def idle_from_records(records: list[dict]) -> bool | None:
    for record in reversed(records):
        if record.get("type") == "agent_turn_outcome":
            return True
        if is_turn_input(record) or (record.get("message") or {}).get("role") == "assistant":
            return False
    return None


class DroidTranscript:
    def __init__(self, path: Path):
        self.path = path

    @classmethod
    def locate(cls, home: Path, cwd: Path, session_id: str | None = None) -> DroidTranscript | None:
        path = find_session_file(home, cwd, session_id)
        return cls(path) if path else None

    def records(self) -> list[dict]:
        return read_jsonl(self.path)

    def session_id(self) -> str | None:
        start = session_start(self.path)
        return start.get("id") if start else None

    def entries(self) -> list[Entry]:
        return parse_records(self.records())

    def find_token(self, token: str) -> list[Entry]:
        return match_token(self.entries(), token)

    def is_idle(self) -> bool | None:
        return idle_from_records(self.records())
