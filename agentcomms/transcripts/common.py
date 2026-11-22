import json
from datetime import datetime
from pathlib import Path

Entry = tuple[float, str, str]


def parse_ts(value: str | float | int | None) -> float:
    if value is None:
        return 0.0
    if isinstance(value, int | float):
        return float(value) / (1000.0 if value > 1e11 else 1.0)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(errors="replace").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def match_token(entries: list[Entry], token: str) -> list[Entry]:
    return [e for e in entries if token in e[2]]


def first_record(path: Path, rtype: str) -> dict | None:
    try:
        with path.open() as f:
            first = json.loads(f.readline())
    except (OSError, json.JSONDecodeError):
        return None
    return first if isinstance(first, dict) and first.get("type") == rtype else None


TEXT_BLOCKS = ("text", "input_text", "output_text")


def content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") in TEXT_BLOCKS)
    return ""


def newest_session(headers: list[tuple[object, dict, Path]], cwd: Path, session_id: str | None = None) -> Path | None:
    want = str(cwd.resolve())
    matches = [(rank, path) for rank, header, path in headers
               if header.get("cwd") == want and (not session_id or header.get("id") == session_id)]
    return max(matches)[1] if matches else None
