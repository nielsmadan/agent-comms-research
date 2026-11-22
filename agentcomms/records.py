import hashlib
import json
import re
from dataclasses import asdict, dataclass, field

from agentcomms.model import Ack, Backend, Delivery, DraftFate, HostKind

FIELD_ORDER = (
    "run_id", "stage", "agent", "versions", "mechanism", "host", "backend", "scenario", "rep", "sandbox",
    "delivery", "intact", "draft_fate", "ack", "harmful", "retries", "latency_s", "evidence",
    "sent_sha256", "recv_sha256", "token", "notes", "ts",
)


def tildify(text: str, home: str) -> str:
    if not home.strip("/"):
        return text
    needles = dict.fromkeys([home, re.sub(r"[^A-Za-z0-9]", "-", home), re.sub(r"[^A-Za-z0-9_-]", "-", home)])
    for needle in needles:
        text = text.replace(needle, "~")
    return text


def sha256(text: str | None) -> str | None:
    return hashlib.sha256(text.encode()).hexdigest() if text is not None else None


@dataclass(frozen=True)
class ResultRecord:
    run_id: str
    stage: str
    agent: str
    versions: dict[str, str]
    mechanism: str
    host: HostKind
    backend: Backend
    scenario: str
    rep: int
    sandbox: str
    delivery: Delivery
    intact: bool | None
    draft_fate: DraftFate
    ack: Ack
    harmful: bool
    retries: int
    latency_s: float | None
    evidence: list[str] = field(default_factory=list)
    sent_sha256: str | None = None
    recv_sha256: str | None = None
    token: str | None = None
    notes: str = ""
    ts: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        for key in ("delivery", "draft_fate", "ack"):
            d[key] = str(d[key])
        return {k: d[k] for k in FIELD_ORDER}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> ResultRecord:
        return cls(**{"token": None, **d, "delivery": Delivery(d["delivery"]), "draft_fate": DraftFate(d["draft_fate"]),
                      "ack": Ack(d["ack"])})
