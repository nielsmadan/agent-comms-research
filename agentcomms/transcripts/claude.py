import json
import re
from pathlib import Path

from agentcomms.transcripts.common import Entry, content_text, match_token, parse_ts, read_jsonl

PEER_MARK = "<cross-session-message"
CHANNEL_MARK = "<channel source="
PUSHED_ORIGINS = ("peer", "channel")
HELD_MARK = "Held peer message"


def encode_cwd(cwd: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def transcript_path(config_dir: Path, cwd: Path, session_id: str) -> Path:
    direct = config_dir / "projects" / encode_cwd(cwd) / f"{session_id}.jsonl"
    if direct.exists():
        return direct
    found = sorted((config_dir / "projects").glob(f"*/{session_id}.jsonl"))
    return found[0] if found else direct


def _user_kind(record: dict, text: str) -> str:
    if (record.get("origin") or {}).get("kind") in PUSHED_ORIGINS or PEER_MARK in text or text.startswith(CHANNEL_MARK):
        return "peer"
    return "system" if record.get("isMeta") else "user"


def hook_text(content) -> str:
    if isinstance(content, list):
        return "\n".join(c if isinstance(c, str) else content_text([c]) for c in content)
    return content_text(content)


def parse_record(record: dict) -> list[Entry]:
    ts = parse_ts(record.get("timestamp"))
    rtype = record.get("type")
    message = record.get("message") or {}
    content = message.get("content")
    if rtype == "user":
        if isinstance(content, str):
            return [(ts, _user_kind(record, content), content)]
        entries = []
        for block in content or []:
            if block.get("type") == "text":
                entries.append((ts, _user_kind(record, block["text"]), block["text"]))
            elif block.get("type") == "tool_result":
                entries.append((ts, "tool_result", content_text(block.get("content"))))
        return entries
    if rtype == "assistant" and record.get("isApiErrorMessage"):
        return [(ts, "api_error", content_text(content))]
    if rtype == "assistant":
        entries = []
        for block in content or []:
            if block.get("type") == "text":
                entries.append((ts, "assistant", block["text"]))
            elif block.get("type") == "tool_use":
                entries.append((ts, "tool_use", json.dumps(block.get("input", {}))))
        if message.get("stop_reason") == "end_turn":
            entries.append((ts, "system", "end_turn"))
        return entries
    attachment = record.get("attachment") or {}
    if rtype == "attachment" and attachment.get("type") == "queued_command" and attachment.get("prompt"):
        peer = (attachment.get("origin") or {}).get("kind") == "peer" or PEER_MARK in attachment["prompt"]
        return [(ts, "peer" if peer else "user", str(attachment["prompt"]))]
    if rtype == "attachment" and attachment.get("type") == "hook_additional_context":
        return [(ts, "hook", hook_text(attachment.get("content")))]
    if rtype == "attachment" and attachment.get("type") == "hook_system_message":
        return [(ts, "system", str(attachment.get("content") or ""))]
    if rtype == "queue-operation" and record.get("content"):
        return [(ts, "queue", str(record["content"]))]
    text = record.get("content") if isinstance(record.get("content"), str) else ""
    if rtype == "system" and text.startswith(HELD_MARK):
        return [(ts, "held", text)]
    return [(ts, "system", text)] if text else []


def file_ordered(entries: list[Entry]) -> list[Entry]:
    ordered, latest = [], 0.0
    for ts, kind, text in entries:
        latest = max(latest, ts)
        ordered.append((latest if kind in ("user", "peer") else ts, kind, text))
    return ordered


LOCAL_COMMAND_PREFIXES = ("<command-name>", "<local-command-stdout>", "<local-command-caveat>",
                          "<local-command-stderr>")


def is_local_command(record: dict) -> bool:
    content = (record.get("message") or {}).get("content")
    text = content if isinstance(content, str) else content_text(content)
    return record.get("isCompactSummary") or text.lstrip().startswith(LOCAL_COMMAND_PREFIXES)


def idle_from_records(records: list[dict]) -> bool | None:
    for record in reversed(records):
        rtype = record.get("type")
        if rtype == "assistant":
            stop = (record.get("message") or {}).get("stop_reason")
            if stop == "end_turn":
                return True
            if stop == "tool_use":
                return False
            return None
        if rtype == "system" and record.get("subtype") == "compact_boundary":
            return True
        if rtype == "user" and not record.get("isMeta") and not is_local_command(record):
            return False
    return None


def registry_entry(config_dir: Path, pid: int) -> dict | None:
    path = config_dir / "sessions" / f"{pid}.json"
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


class ClaudeTranscript:
    def __init__(self, path: Path):
        self.path = path

    def records(self) -> list[dict]:
        return read_jsonl(self.path)

    def entries(self) -> list[Entry]:
        return file_ordered([e for r in self.records() for e in parse_record(r)])

    def find_token(self, token: str) -> list[Entry]:
        return match_token(self.entries(), token)

    def is_idle(self) -> bool | None:
        return idle_from_records(self.records())
