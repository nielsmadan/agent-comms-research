import re
from collections.abc import Callable
from dataclasses import dataclass

from agentcomms import markers
from agentcomms.model import Delivery, DraftFate

UNCOUNTED = frozenset({Delivery.NA, Delivery.ERROR, Delivery.ENV_ERROR})
SCENARIO_ORDER = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12", "SCALE")
ROW_KEYS = ("agent", "mechanism", "host", "backend")


def note_value(notes: str, key: str) -> str | None:
    m = re.search(rf"(?:^|[;\s]){re.escape(key)}=([^;\s]+)", notes or "")
    return m.group(1) if m else None


def delivered(r: dict) -> bool:
    return r["delivery"] == Delivery.DELIVERED


def intact(r: dict) -> bool:
    return r.get("intact") is True


def queued_or_delivered(r: dict) -> bool:
    return r["delivery"] in (Delivery.DELIVERED, Delivery.QUEUED)


def respawned(r: dict) -> bool:
    return markers.RESPAWNED in (r.get("notes") or "")


def compact_unexercised(r: dict) -> bool:
    return r["scenario"] == "S10" and "clear=delivered@old-session" in (r.get("notes") or "")


GOOD: dict[str, Callable[[dict], bool]] = {
    "S1": lambda r: delivered(r) and intact(r),
    "S2": lambda r: r["delivery"] in (Delivery.QUEUED, Delivery.INTERRUPTED) and intact(r),
    "S3": lambda r: queued_or_delivered(r) and not r["harmful"],
    "S4": lambda r: delivered(r) and intact(r),
    "S5": lambda r: delivered(r) and intact(r) and note_value(r["notes"], "order") == "in-order"
    and note_value(r["notes"], "merged") != "yes",
    "S6": lambda r: delivered(r) and note_value(r["notes"], "down") in ("rejected", "queued"),
    "S7": lambda r: delivered(r) and r["draft_fate"] == DraftFate.PRESERVED,
    "S8": lambda r: delivered(r) and note_value(r["notes"], "rendered") == "yes",
    "S9": lambda r: delivered(r) and note_value(r["notes"], "roundtrip") == "yes",
    "S10": delivered,
    "S11": lambda r: queued_or_delivered(r) and not r["harmful"],
    "S12": lambda r: queued_or_delivered(r) and not respawned(r),
    "SCALE": delivered,
}


def is_good(r: dict) -> bool:
    return r["delivery"] not in UNCOUNTED and GOOD[r["scenario"]](r)


def counted(r: dict) -> bool:
    return r["delivery"] not in UNCOUNTED


@dataclass(frozen=True)
class Tally:
    k: int = 0
    n: int = 0
    errors: int = 0
    na: int = 0
    harmful: int = 0
    held: int = 0
    respawned: int = 0
    unexercised: int = 0

    def add(self, r: dict) -> Tally:
        return Tally(
            k=self.k + is_good(r), n=self.n + counted(r), errors=self.errors + (r["delivery"] == Delivery.ERROR),
            na=self.na + (r["delivery"] == Delivery.NA), harmful=self.harmful + bool(r.get("harmful")),
            held=self.held + (r["delivery"] == Delivery.HELD), respawned=self.respawned + respawned(r),
            unexercised=self.unexercised + compact_unexercised(r),
        )


def os_era(r: dict) -> str:
    label = r.get("versions", {}).get("os")
    if label is None:
        return "26"
    m = re.match(r"(\d+)(?:\.|\s|$)", str(label))
    return m.group(1) if m else "unknown"


USER_CONFIG_STAGE = "user-config"


def condition(r: dict) -> str:
    sandbox = r.get("sandbox") or "raw"
    return f"{sandbox} + user config" if r.get("stage") == USER_CONFIG_STAGE else sandbox


def row_key(r: dict) -> tuple:
    return (*(r[k] for k in ROW_KEYS), os_era(r), condition(r))


def tally(records: list[dict], stage: str | None = None) -> dict[tuple, dict[str, Tally]]:
    table: dict[tuple, dict[str, Tally]] = {}
    for r in records:
        if r["delivery"] == Delivery.ENV_ERROR or (stage and r["stage"] != stage):
            continue
        row = table.setdefault(row_key(r), {})
        row[r["scenario"]] = row.get(r["scenario"], Tally()).add(r)
    return table


def cell_text(t: Tally | None) -> str:
    if t is None:
        return "-"
    if t.n == 0 and t.errors == 0:
        return "n/a"
    parts = [f"{t.k}/{t.n}"]
    if t.errors:
        parts.append(f"err {t.errors}")
    if t.harmful:
        parts.append(f"harm {t.harmful}")
    if t.held:
        parts.append(f"held {t.held}")
    if t.respawned:
        parts.append(f"respawned {t.respawned}")
    if t.unexercised:
        parts.append("compaction not exercised on the delivered session")
    return " · ".join(parts)
