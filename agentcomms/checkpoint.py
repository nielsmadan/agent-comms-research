import json
import os
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from agentcomms.model import Delivery
from agentcomms.records import tildify
from agentcomms.report import notes_section, render_progress

SLEEP_THRESHOLD_S = 30.0
PROGRESS_INTERVAL_S = 30 * 60
DEFAULT_BUDGET_MIN = 360.0
CELL_KEYS = ("stage", "agent", "mechanism", "host", "backend", "scenario", "rep", "sandbox")
NETWORK_PROBES = (("api.anthropic.com", 443), ("chatgpt.com", 443))


def cell_key(cell: dict) -> tuple:
    return tuple(cell[k] for k in CELL_KEYS)


APPEND_LOCK = threading.Lock()


def append_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with APPEND_LOCK, path.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def parse_records(text: str) -> list[dict]:
    lines = [line for line in text.splitlines() if line.strip()]
    if lines and not text.endswith("\n"):
        try:
            json.loads(lines[-1])
        except json.JSONDecodeError:
            lines = lines[:-1]
    return [json.loads(line) for line in lines]


def load_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with APPEND_LOCK:
        text = path.read_text()
    return parse_records(text)


def completed_cells(records: list[dict], retry_errors: bool = False) -> set[tuple]:
    retried = {Delivery.ENV_ERROR, Delivery.ERROR} if retry_errors else {Delivery.ENV_ERROR}
    return {cell_key(r) for r in records if r.get("delivery") not in retried}


def pending_cells(cells: list[dict], records: list[dict], resume: bool, retry_errors: bool = False) -> list[dict]:
    if not resume:
        return list(cells)
    done = completed_cells(records, retry_errors)
    return [c for c in cells if cell_key(c) not in done]


def slept(wall0: float, mono0: float, wall1: float, mono1: float, threshold: float = SLEEP_THRESHOLD_S) -> bool:
    return (wall1 - wall0) - (mono1 - mono0) > threshold


def network_ok(probes: tuple[tuple[str, int], ...] = NETWORK_PROBES, timeout: float = 5.0) -> bool:
    for host, port in probes:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                pass
        except OSError:
            return False
    return True


@dataclass(frozen=True)
class TimeBudget:
    start_mono: float
    minutes: float = DEFAULT_BUDGET_MIN

    def expired(self, now_mono: float) -> bool:
        return now_mono - self.start_mono >= self.minutes * 60


@dataclass
class ProgressWriter:
    path: Path
    raw: Path
    interval_s: float = PROGRESS_INTERVAL_S
    last_mono: float | None = None
    open_issues: list[str] = field(default_factory=list)
    home: str = ""

    def maybe_write(self, now_mono: float, next_cells: list[dict], force: bool = False) -> bool:
        if not force and self.last_mono is not None and now_mono - self.last_mono < self.interval_s:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        issues = [tildify(i, self.home) for i in self.open_issues]
        notes = notes_section(self.path.read_text()) if self.path.exists() else []
        self.path.write_text(render_progress(load_records(self.raw), issues, next_cells, time.time(), notes))
        self.last_mono = now_mono
        return True
