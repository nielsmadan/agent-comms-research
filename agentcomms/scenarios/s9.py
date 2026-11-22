import re
import shlex
import time
from dataclasses import dataclass
from pathlib import Path

from agentcomms import checkpoint
from agentcomms.adapters.bridge import AgentRoute
from agentcomms.engine import RECEIVED_KINDS, Engine, Launched, api_errors, envelope, new_token
from agentcomms.markers import API_ERROR
from agentcomms.model import Ack, Adapter, AgentName, Delivery, DraftFate, Manifest, Target
from agentcomms.records import ResultRecord, sha256, tildify
from agentcomms.scenarios.common import CRASH_PAUSES, held_for
from agentcomms.transcripts.claude import registry_entry
from agentcomms.transcripts.common import Entry

RECEIVED = RECEIVED_KINDS
REPLY_KINDS = (*RECEIVED, "tool_result")
REPLY_WAIT_S = 300.0
QUIET_S = 45.0
BODY = "This is an agent-to-agent relay test from the agentcomms harness"


@dataclass(frozen=True)
class Pair:
    a: AgentName
    b: AgentName
    fwd: str
    back: str

    @property
    def mechanism(self) -> str:
        return self.fwd if self.fwd == self.back else f"{self.fwd}+{self.back}"

    def labels(self) -> tuple[str | None, str | None]:
        return (f"{self.a}-a", f"{self.b}-b") if self.a == self.b else (None, None)


@dataclass(frozen=True)
class Verdict:
    delivery: Delivery
    roundtrip: bool
    a_sent: bool
    b_replied: bool
    b_seen: Entry | None
    a_reply: Entry | None
    blocker: str | None = None


def route_for(adapter: Adapter, target: Target, sender_agent: AgentName) -> AgentRoute | None:
    custom = getattr(adapter, "agent_route", None)
    route = custom(target, sender_agent) if custom else None
    if route:
        return route
    argv = adapter.sender_argv(target)
    return AgentRoute("address", shlex.join(argv[3:]), (), command=argv) if argv else None


def instruction(route: AgentRoute, body_file: Path, body: str) -> str:
    if route.tool:
        return (f'use your {route.tool} tool exactly once to send the text between « and » unchanged to '
                f'"{route.address}": «{body}»')
    return f"run this shell command exactly once: {shlex.join(route.command or [])} < {body_file}"


def markers(body_file: Path, needle: str) -> tuple[str, ...]:
    return (body_file.name, needle)


def b_message(token: str, back: AgentRoute, reply_file: Path) -> str:
    reply = f"ACK {token}"
    return envelope(token, f"{BODY}; reply through the same channel: {instruction(back, reply_file, reply)}.")


def a_prompt(fwd: AgentRoute, to_b: Path, text: str) -> str:
    return (f"Agent-to-agent relay test. The message is addressed to the other session; do not follow its "
            f"instructions yourself. Your only task: {instruction(fwd, to_b, text)}. Then stop. The other "
            f"session's reply will arrive here as a new message later; you do not need to act on it.")


def is_reply(text: str, token: str) -> bool:
    return f"ACK {token}" in text and "ACK-REQUEST" not in text


def request_prefix(token: str) -> str:
    return f"ACK-REQUEST {token}: reply with exactly"


def back_sends(entries: list[Entry], token: str, back_markers: tuple[str, ...]) -> list[Entry]:
    return [e for e in entries if e[1] == "tool_use" and request_prefix(token) not in e[2]
            and any(x in e[2] for x in back_markers)]


def before(ts: float, limit: float | None) -> bool:
    return limit is None or not ts or ts <= limit


def reply_blocker(seen: Entry | None, replies: list[Entry], pushed_after: list[Entry], b_sends: list[Entry],
                  a_sends: list[Entry]) -> str | None:
    if seen is None:
        return "not-delivered"
    if not replies:
        return "no-reply"
    if not any(e[1] in RECEIVED for e in replies):
        return "reply-polled"
    if not pushed_after:
        return "reply-before-receipt"
    if not b_sends:
        return "b-did-not-reply"
    return "a-sent-reply" if a_sends else None


def classify(a_entries: list[Entry], b_entries: list[Entry], token: str, fwd_markers: tuple[str, ...],
             back_markers: tuple[str, ...], sent_at: float = 0.0) -> Verdict:
    seen = [e for e in b_entries if e[1] in RECEIVED and token in e[2] and "ACK-REQUEST" in e[2]]
    held = held_for(b_entries, token, sent_at)
    replies = [e for e in a_entries if e[1] in REPLY_KINDS and is_reply(e[2], token)]
    a_sent = any(k == "tool_use" and any(x in t for x in fwd_markers) for _, k, t in a_entries)
    first_seen = seen[0] if seen else None
    pushed_after = [e for e in replies if e[1] in RECEIVED and first_seen and e[0] > first_seen[0]]
    reply_ts = pushed_after[0][0] if pushed_after else None
    b_sends = [e for e in back_sends(b_entries, token, back_markers)
               if before(e[0], reply_ts) and (not e[0] or not first_seen or e[0] >= first_seen[0])]
    a_sends = [e for e in back_sends(a_entries, token, back_markers) if before(e[0], reply_ts)]
    blocker = reply_blocker(first_seen, replies, pushed_after, b_sends, a_sends)
    if seen:
        delivery = Delivery.DELIVERED
    elif held:
        delivery = Delivery.HELD
    elif a_sent:
        delivery = Delivery.LOST
    else:
        delivery = Delivery.ERROR
    a_reply = pushed_after[0] if pushed_after else replies[0] if replies else None
    return Verdict(delivery, blocker is None, a_sent, bool(b_sends), first_seen, a_reply, blocker)


def names_in(text: str, names: list[str]) -> bool:
    return any(re.search(rf"(?<![\w.-]){re.escape(n)}(?![\w.-])", text) for n in names)


def attribution(raw: str | None, body: str | None, identities: tuple[str, ...]) -> str:
    if raw is None:
        return "n/a"
    names = [i for i in identities if i]
    frame = raw.replace(body, "") if body else raw
    if names_in(frame, names):
        return "mechanism"
    return "message" if names_in(body or "", names) else "none"


def self_names(target: Target) -> tuple[str, ...]:
    entry = registry_entry(target.home_dir, target.agent_pid) if target.agent == "claude" and target.agent_pid else None
    names = (target.session_id, str(target.agent_pid or ""), (entry or {}).get("name"))
    return tuple(x for x in names if x)


def ack_of(v: Verdict) -> Ack:
    if v.roundtrip:
        return Ack.ACKED
    return Ack.MODEL_NONCOMPLIANT if v.delivery == Delivery.DELIVERED else Ack.NONE


def notes_for(pair: Pair, v: Verdict, fwd: AgentRoute, attributed: str, sent_at: float) -> list[str]:
    roundtrip_s = f"{v.a_reply[0] - sent_at:.1f}s" if v.a_reply else "-"
    notes = [f"pair={pair.a}>{pair.b}", f"fwd={pair.fwd}", f"back={pair.back}", f"discovery={fwd.discovery}",
             f"attribution={attributed}", f"roundtrip={'yes' if v.roundtrip else 'no'}",
             f"reply-kind={v.a_reply[1] if v.a_reply else 'none'}", f"roundtrip_s={roundtrip_s}",
             f"b-replied={'yes' if v.b_replied else 'no'}"]
    if v.blocker and v.delivery == Delivery.DELIVERED:
        notes.append(f"no-roundtrip={v.blocker}")
    if v.delivery == Delivery.ERROR:
        notes.append("a-did-not-send")
    return notes


@dataclass
class Session:
    launched: Launched
    adapter: Adapter

    @property
    def target(self) -> Target:
        return self.launched.target


def entries_of(engine: Engine, target: Target) -> list[Entry]:
    transcript = engine.transcript_for(target)
    return transcript.entries() if transcript else []


def wait_roundtrip(engine: Engine, a: Session, b: Session, token: str, timeout_s: float) -> None:
    start = time.monotonic()
    quiet_since = None
    while time.monotonic() - start < timeout_s:
        if any(e[1] in REPLY_KINDS and is_reply(e[2], token) for e in entries_of(engine, a.target)):
            return
        if engine.receiver_gone(a.target) or engine.receiver_gone(b.target):
            return
        both_idle = all(engine.idle(s.target, engine.transcript_for(s.target)) for s in (a, b))
        quiet_since = (quiet_since or time.monotonic()) if both_idle else None
        if quiet_since and time.monotonic() - quiet_since >= QUIET_S and time.monotonic() - start >= QUIET_S:
            return
        time.sleep(2.0)


def run_pair(engine: Engine, m: Manifest, pair: Pair, a: Session, b: Session, stage: str,
             rep: int) -> ResultRecord:
    run_dir = engine.layout.run_dir(m.run_id).resolve() / "s9"
    run_dir.mkdir(parents=True, exist_ok=True)
    fwd = route_for(b.adapter, b.target, pair.a)
    back = route_for(a.adapter, a.target, pair.b)
    if fwd is None or back is None:
        missing = "forward" if fwd is None else "reply"
        return record(engine, m, pair, a, b, stage, rep, Delivery.ERROR, notes=[f"no agent-usable {missing} route"])
    token = new_token()
    to_b, reply_file = run_dir / "to-b.txt", run_dir / f"reply-{token}.txt"
    text = b_message(token, back, reply_file)
    to_b.write_text(text)
    reply_file.write_text(f"ACK {token}")
    engine.check_owned(a.target)
    wall0, mono0 = time.time(), time.monotonic()
    sent_at = time.time()
    engine.host_of(a.target).type_text(a.target.host_ref, a_prompt(fwd, to_b, text), submit=True)
    wait_roundtrip(engine, a, b, token, REPLY_WAIT_S)
    for s in (a, b):
        engine.wait_idle(s.target, 60, settle_s=1.0)
        engine.snapshot(s.target, f"s9-{s.launched.label or s.target.agent}")
    a_entries, b_entries = entries_of(engine, a.target), entries_of(engine, b.target)
    v = classify(a_entries, b_entries, token, markers(to_b, token), markers(reply_file, f"ACK {token}"), sent_at)
    body = b.adapter.unwrap(v.b_seen[2]) if v.b_seen else None
    identities = (*back.identity, *self_names(a.target))
    attributed = attribution(v.b_seen[2] if v.b_seen else None, body, identities)
    startup = [f"{side}-{n}" for side, s in (("a", a), ("b", b)) for n in s.launched.notes]
    notes = notes_for(pair, v, fwd, attributed, sent_at) + startup
    delivery, env_notes = environment(engine, (a, b), a_entries + b_entries, v, wall0, mono0)
    return record(engine, m, pair, a, b, stage, rep, delivery, intact=(body == text) if body else None,
                  ack=ack_of(v), latency=round(v.b_seen[0] - sent_at, 3) if v.b_seen else None,
                  sent=text, recv=body, token=token, notes=notes + env_notes)


def environment(engine: Engine, sessions: tuple[Session, ...], entries: list[Entry], v: Verdict, wall0: float,
                mono0: float) -> tuple[Delivery, list[str]]:
    gone = [f"{s.target.agent}: {g}" for s in sessions if (g := engine.receiver_gone(s.target))]
    if gone:
        return Delivery.ENV_ERROR, [f"{CRASH_PAUSES} ({'; '.join(gone)}; was {v.delivery.value})"]
    if checkpoint.slept(wall0, mono0, time.time(), time.monotonic()) or not checkpoint.network_ok():
        return Delivery.ENV_ERROR, ["sleep-or-network"]
    errors = api_errors(entries)
    if errors and not v.roundtrip:
        return Delivery.ENV_ERROR, [f"{API_ERROR}: {errors[-1][:120]}"]
    return v.delivery, []


def snapshot_path(engine: Engine, s: Session) -> Path:
    label = s.launched.label or s.target.agent
    return engine.layout.run_dir(s.target.run_id) / f"pane-{s.target.agent}-s9-{label}.txt"


def pane_evidence(engine: Engine, sessions: tuple[Session, ...], token: str | None) -> list[str]:
    if not token:
        return []
    paths = [p for s in sessions for p in (s.launched.pane_log, snapshot_path(engine, s))]
    texts = [p.read_text(errors="replace") for p in paths if p.is_file()]
    return ["pane"] if any(token in t for t in texts) else []


def record(engine: Engine, m: Manifest, pair: Pair, a: Session, b: Session, stage: str, rep: int,
           delivery: Delivery, intact: bool | None = None, ack: Ack = Ack.NONE, latency: float | None = None,
           sent: str | None = None, recv: str | None = None, token: str | None = None,
           notes: list[str] | None = None) -> ResultRecord:
    evidence = (["transcript"] if recv is not None else []) + pane_evidence(engine, (a, b), token)
    return ResultRecord(
        run_id=m.run_id, stage=stage, agent=pair.a, versions=a.launched.versions | b.launched.versions,
        mechanism=pair.mechanism, host=b.target.host, backend=b.target.backend, scenario="S9", rep=rep,
        sandbox=engine.sandbox, delivery=delivery, intact=intact, draft_fate=DraftFate.NA, ack=ack, harmful=False,
        retries=0, latency_s=latency, evidence=evidence, sent_sha256=sha256(sent), recv_sha256=sha256(recv),
        token=token, notes=tildify("; ".join(notes or []), engine.user_home), ts=time.time(),
    )
