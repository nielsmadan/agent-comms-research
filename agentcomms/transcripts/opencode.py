import json
import sqlite3
from contextlib import closing
from pathlib import Path

from agentcomms.transcripts.common import Entry, content_text, match_token, parse_ts

QUEUE_TABLES = (("session_inbox", "payload"), ("session_pending", "data"))


def db_path(home: Path) -> Path:
    return home / "data" / "opencode" / "opencode.db"


def connect_ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


OPTIONAL_TABLES = frozenset({"session_v2", *(t for t, _ in QUEUE_TABLES)})
TRANSIENT = ("database is locked", "database is busy", "unable to open database file")


class SchemaDriftError(RuntimeError):
    pass


def tolerated(error: sqlite3.OperationalError) -> bool:
    text = str(error)
    missing = text.removeprefix("no such table: ") if text.startswith("no such table: ") else None
    return missing in OPTIONAL_TABLES or text.startswith(TRANSIENT)


def drift(error: sqlite3.OperationalError, sql: str) -> SchemaDriftError:
    return SchemaDriftError(f"OpenCode database schema changed ({error}) for: {' '.join(sql.split())[:120]}")


def query(path: Path, sql: str, params: tuple = ()) -> list[dict]:
    if not path.exists():
        return []
    try:
        with closing(connect_ro(path)) as conn:
            return [dict(r) for r in conn.execute(sql, params)]
    except sqlite3.OperationalError as e:
        if tolerated(e):
            return []
        raise drift(e, sql) from e


def select(conn: sqlite3.Connection, sql: str, params: tuple) -> list[dict]:
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    except sqlite3.OperationalError as e:
        if tolerated(e):
            return []
        raise drift(e, sql) from e


def read_session(path: Path, session: str) -> tuple[list[dict], list[tuple[dict, str]]]:
    if not path.exists():
        return [], []
    try:
        with closing(connect_ro(path)) as conn:
            conn.execute("BEGIN")
            messages = select(conn, "SELECT id, type, seq, time_created, data FROM session_message "
                                    "WHERE session_id = ? ORDER BY seq", (session,))
            queued = [(row, column) for table, column in QUEUE_TABLES
                      for row in select(conn, f"SELECT id, {column}, time_created FROM {table} "
                                              "WHERE session_id = ? ORDER BY time_created", (session,))]
            conn.rollback()
    except sqlite3.OperationalError as e:
        if tolerated(e):
            return [], []
        raise drift(e, "read_session") from e
    return messages, queued


def find_sessions(path: Path, cwd: Path) -> list[str]:
    rows = query(path, "SELECT id FROM session_v2 WHERE directory = ? AND parent_id IS NULL "
                       "ORDER BY time_created DESC", (str(cwd.resolve()),))
    return [r["id"] for r in rows]


def find_session(path: Path, cwd: Path, session_id: str | None = None) -> str | None:
    ids = find_sessions(path, cwd)
    if session_id:
        return session_id if session_id in ids else None
    return ids[0] if ids else None


def _json(text: str | None) -> dict:
    try:
        value = json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _error_text(error) -> str:
    if isinstance(error, dict):
        return str(error.get("message") or (error.get("data") or {}).get("message") or json.dumps(error))
    return str(error)


def _error_entry(ts: float, error) -> Entry:
    if isinstance(error, dict) and error.get("type") == "aborted":
        return (ts, "system", f"aborted: {_error_text(error)}")
    return (ts, "api_error", _error_text(error))


def _assistant_entries(ts: float, data: dict) -> list[Entry]:
    entries = []
    for part in data.get("content") or []:
        if part.get("type") == "text":
            entries.append((ts, "assistant", part.get("text", "")))
        elif part.get("type") == "tool":
            state = part.get("state") or {}
            entries.append((ts, "tool_use", json.dumps(state.get("input", {}))))
            if state.get("status") in ("completed", "error"):
                entries.append((ts, "tool_result", content_text(state.get("content"))))
    if data.get("error"):
        entries.append(_error_entry(ts, data["error"]))
    return entries


def parse_message(row: dict) -> list[Entry]:
    ts = parse_ts(row.get("time_created"))
    data = _json(row.get("data"))
    match row.get("type"):
        case "user":
            return [(ts, "user", str(data.get("text", "")))]
        case "synthetic":
            return [(ts, "custom", str(data.get("text", "")))]
        case "system" | "skill":
            return [(ts, "system", str(data.get("text", "")))]
        case "shell":
            return [(ts, "tool_result", json.dumps(data))]
        case "assistant":
            return _assistant_entries(ts, data)
        case "idle":
            idle = [(ts, "system", f"idle:{data.get('outcome')}")]
            return idle + ([_error_entry(ts, data["error"])] if data.get("error") else [])
    return []


def parse_queued(row: dict, column: str) -> list[Entry]:
    payload = _json(row.get(column))
    text = payload.get("text")
    return [(parse_ts(row.get("time_created")), "queue", str(text))] if text is not None else []


def merge_entries(messages: list[dict], queued: list[tuple[dict, str]]) -> list[Entry]:
    seen = {m["id"] for m in messages}
    entries = [e for m in messages for e in parse_message(m)]
    return entries + [e for row, column in queued if row["id"] not in seen for e in parse_queued(row, column)]


def idle_from_rows(messages: list[dict], queued_count: int) -> bool | None:
    if queued_count:
        return False
    for row in reversed(messages):
        if row.get("type") == "idle":
            return True
        if row.get("type") in ("user", "assistant", "synthetic", "shell"):
            return False
    return None


class OpenCodeTranscript:
    def __init__(self, path: Path, session: str):
        self.path = path
        self.session = session

    @classmethod
    def locate(cls, home: Path, cwd: Path, session_id: str | None = None) -> OpenCodeTranscript | None:
        path = db_path(home)
        session = find_session(path, cwd, session_id)
        return cls(path, session) if session else None

    @classmethod
    def locate_all(cls, home: Path, cwd: Path) -> list[OpenCodeTranscript]:
        path = db_path(home)
        return [cls(path, session) for session in find_sessions(path, cwd)]

    def session_id(self) -> str:
        return self.session

    def snapshot(self) -> tuple[list[dict], list[tuple[dict, str]]]:
        return read_session(self.path, self.session)

    def entries(self) -> list[Entry]:
        return merge_entries(*self.snapshot())

    def find_token(self, token: str) -> list[Entry]:
        return match_token(self.entries(), token)

    def is_idle(self) -> bool | None:
        messages, queued = self.snapshot()
        return idle_from_rows(messages, len(queued))
