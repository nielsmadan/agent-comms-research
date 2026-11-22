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

CONTEXT_PREFIXES = ("<environment_context>", "<user_instructions>", "# AGENTS.md instructions", "<INSTRUCTIONS>",
                    "<turn_aborted>", "<skills_instructions>", "<permissions instructions>")
IDLE_EVENTS = {"task_complete": True, "turn_aborted": True, "task_started": False}


def session_meta(path: Path) -> dict | None:
    first = first_record(path, "session_meta")
    return first.get("payload") if first else None


def find_rollout(sessions_dir: Path, cwd: Path, session_id: str | None = None) -> Path | None:
    metas = [(session_meta(path), path) for path in sessions_dir.rglob("rollout-*.jsonl")]
    headers = [(meta.get("timestamp", ""), meta, path) for meta, path in metas
               if meta and meta.get("thread_source") != "subagent"]
    return newest_session(headers, cwd, session_id)


def is_hook_context(payload: dict) -> bool:
    meta = payload.get("internal_chat_message_metadata_passthrough") or {}
    return "hooks.additional_context" in (meta.get("content_item_kinds") or [])


def parse_record(record: dict) -> list[Entry]:
    ts = parse_ts(record.get("timestamp"))
    rtype = record.get("type")
    p = record.get("payload") or {}
    ptype = p.get("type")
    if rtype == "response_item":
        if ptype == "message":
            text = content_text(p.get("content"))
            role = p.get("role")
            if role == "assistant":
                return [(ts, "assistant", text)]
            if role == "user":
                return [(ts, "system" if text.lstrip().startswith(CONTEXT_PREFIXES) else "user", text)]
            return [(ts, "hook" if is_hook_context(p) else "system", text)]
        if ptype in ("function_call", "custom_tool_call", "local_shell_call"):
            return [(ts, "tool_use", str(p.get("arguments") or p.get("input") or json.dumps(p.get("action"))))]
        if ptype in ("function_call_output", "custom_tool_call_output"):
            return [(ts, "tool_result", content_text(p.get("output")))]
        if ptype == "agent_message":
            return [(ts, "peer", content_text(p.get("content")))]
        return []
    if rtype == "event_msg" and ptype == "error":
        return [(ts, "api_error", str(p.get("message") or ""))]
    if rtype == "event_msg" and ptype in IDLE_EVENTS:
        return [(ts, "system", ptype)]
    return []


def idle_from_records(records: list[dict]) -> bool | None:
    for record in reversed(records):
        if record.get("type") == "event_msg":
            ptype = (record.get("payload") or {}).get("type")
            if ptype in IDLE_EVENTS:
                return IDLE_EVENTS[ptype]
    return None


class CodexTranscript:
    def __init__(self, path: Path):
        self.path = path

    @classmethod
    def locate(cls, codex_home: Path, cwd: Path, session_id: str | None = None) -> CodexTranscript | None:
        path = find_rollout(codex_home / "sessions", cwd, session_id)
        return cls(path) if path else None

    def records(self) -> list[dict]:
        return read_jsonl(self.path)

    def session_id(self) -> str | None:
        meta = session_meta(self.path)
        return meta.get("id") if meta else None

    def entries(self) -> list[Entry]:
        return [e for r in self.records() for e in parse_record(r)]

    def find_token(self, token: str) -> list[Entry]:
        return match_token(self.entries(), token)

    def is_idle(self) -> bool | None:
        return idle_from_records(self.records())
