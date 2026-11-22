import statistics
import subprocess
from dataclasses import dataclass

from agentcomms.model import Delivery
from agentcomms.scoring import UNCOUNTED

MIX: tuple[tuple[str, str], ...] = (
    ("claude", "claude-channel"), ("claude", "claude-channel"),
    ("codex", "codex-remote-start"), ("codex", "codex-remote-start"),
    ("pi", "pi-ext"), ("pi", "pi-ext"),
    ("opencode", "opencode-server-queue"),
    ("droid", "tmux-paste"),
)
MESSAGES = 3
SCALE_BODY = "This is a scale test from the agentcomms harness (8 receivers at once); no other action is needed."


@dataclass(frozen=True)
class Receiver:
    label: str
    agent: str
    mechanism: str


@dataclass(frozen=True)
class Spread:
    n: int
    min: float
    median: float
    max: float


@dataclass(frozen=True)
class LoadRow:
    receiver: str
    pid: int
    rss_kb: int
    pcpu: float


def receivers(mix: tuple[tuple[str, str], ...] = MIX) -> list[Receiver]:
    return [Receiver(f"{agent}#{sum(1 for a, _ in mix[:i] if a == agent) + 1}", agent, mechanism)
            for i, (agent, mechanism) in enumerate(mix)]


def message_rep(receiver: Receiver, round_no: int, messages: int = MESSAGES) -> int:
    ordinal = int(receiver.label.rsplit("#", 1)[1])
    return (ordinal - 1) * messages + round_no


def spread(values: list[float]) -> Spread | None:
    if not values:
        return None
    return Spread(len(values), min(values), statistics.median(values), max(values))


def aggregate(records: list[dict]) -> dict:
    counted = [r for r in records if r["delivery"] not in UNCOUNTED]
    delivered = [r for r in counted if r["delivery"] == Delivery.DELIVERED]
    by_agent = {a: [r for r in counted if r["agent"] == a] for a in dict.fromkeys(r["agent"] for r in counted)}
    return {
        "delivered": (len(delivered), len(counted)),
        "acked": (sum(1 for r in counted if r["ack"] == "acked"), len(counted)),
        "errors": len(records) - len(counted),
        "latency": spread([r["latency_s"] for r in delivered if r["latency_s"] is not None]),
        "per_agent": {a: {"delivered": (sum(1 for r in rs if r["delivery"] == Delivery.DELIVERED), len(rs)),
                          "latency": spread([r["latency_s"] for r in rs if r["delivery"] == Delivery.DELIVERED
                                             and r["latency_s"] is not None])}
                      for a, rs in by_agent.items()},
    }


def parse_load(text: str, owner: dict[int, str]) -> list[LoadRow]:
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 3 or not parts[0].isdigit() or int(parts[0]) not in owner:
            continue
        rows.append(LoadRow(owner[int(parts[0])], int(parts[0]), int(parts[1]), float(parts[2])))
    return rows


def sample_load(owner: dict[int, str]) -> list[LoadRow]:
    if not owner:
        return []
    out = subprocess.run(["ps", "-o", "pid=,rss=,pcpu=", "-p", ",".join(str(p) for p in sorted(owner))],
                         capture_output=True, text=True, timeout=30)
    return parse_load(out.stdout, owner)


def load_summary(samples: list[list[LoadRow]]) -> dict:
    taken = [s for s in samples if s]
    if not taken:
        return {"samples": 0}
    totals_rss = [sum(r.rss_kb for r in s) for s in taken]
    totals_cpu = [sum(r.pcpu for r in s) for s in taken]
    labels = sorted({r.receiver for s in taken for r in s})
    return {
        "samples": len(taken),
        "processes_max": max(len(s) for s in taken),
        "total_rss_mb_peak": round(max(totals_rss) / 1024, 1),
        "total_rss_mb_median": round(statistics.median(totals_rss) / 1024, 1),
        "total_cpu_pct_peak": round(max(totals_cpu), 1),
        "total_cpu_pct_median": round(statistics.median(totals_cpu), 1),
        "per_receiver_rss_mb_peak": {label: round(max(sum(r.rss_kb for r in s if r.receiver == label)
                                                      for s in taken) / 1024, 1) for label in labels},
        "per_receiver_cpu_pct_peak": {label: round(max(sum(r.pcpu for r in s if r.receiver == label)
                                                       for s in taken), 1) for label in labels},
    }


def spread_text(s: Spread | None) -> str:
    return "-" if s is None else f"{s.min:.3f} / {s.median:.3f} / {s.max:.3f} s (n={s.n})"
