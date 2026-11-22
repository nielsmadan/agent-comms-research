import re
from dataclasses import dataclass

from agentcomms.engine import REPLY_TIMEOUT_S, envelope, new_token, poll, transcript_session
from agentcomms.model import Ack, Delivery, Target
from agentcomms.scenarios.common import Cell, Outcome, observe, precondition_failed, warm_up

STALE_COMMANDS: dict[str, dict[str, str | None]] = {
    "claude": {"clear": "/clear", "compact": "/compact"},
    "codex": {"clear": "/clear", "compact": "/compact"},
    "pi": {"clear": "/new", "compact": "/compact"},
    "opencode": {"clear": "/new", "compact": "/compact"},
    "droid": {"clear": None, "compact": "/compress"},
}
BODY = "This message was sent to your address from before the {step}."
COMMAND_TIMEOUT_S = {"clear": 30.0, "compact": 180.0}
DONE = {"compact": re.compile(r"compacted|compressed|Compaction · [\d.]+K? in", re.I)}
CONFIRM = {"droid": re.compile(r"Confirm /compress[\s\S]*Enter to confirm")}
CONFIRM_WAIT_S = 10.0
DELIVERY_RANK = (Delivery.DELIVERED, Delivery.QUEUED, Delivery.INTERRUPTED, Delivery.HELD, Delivery.LOST,
                 Delivery.REJECTED)


@dataclass(frozen=True)
class Step:
    name: str
    delivery: Delivery
    ack: Ack
    intact: bool | None
    landed: str


def not_applicable(agent: str, backend: str, adapter=None) -> str | None:
    commands = STALE_COMMANDS.get(agent, {})
    return None if any(commands.values()) else f"{agent} has no /clear or /compact equivalent"


def landed(session_ids: list[str | None], old: str | None) -> str:
    if not session_ids:
        return "nowhere"
    return "old-session" if session_ids[0] == old else "new-session"


def combine(steps: list[Step]) -> tuple[Delivery, Ack, bool | None]:
    if not steps:
        return Delivery.NA, Ack.NONE, None
    worst = max(steps, key=lambda s: DELIVERY_RANK.index(s.delivery) if s.delivery in DELIVERY_RANK else 99)
    acks = {s.ack for s in steps}
    ack = Ack.ACKED if acks == {Ack.ACKED} else (Ack.NONE if Ack.NONE in acks else Ack.MODEL_NONCOMPLIANT)
    intacts = [s.intact for s in steps]
    intact = None if None in intacts else all(intacts)
    return worst.delivery, ack, intact


def acked(entries, token: str) -> bool:
    return any(k == "assistant" and f"ACK {token}" in t for _, k, t in entries)


def needs_warm_up(name: str, steps: list[Step]) -> bool:
    return name == "compact" and bool(steps) and steps[-1].landed == "old-session"


def command_done(name: str, pane: str) -> bool:
    pattern = DONE.get(name)
    return pattern is None or bool(pattern.search(pane))


def confirm_visible(agent: str, pane: str) -> bool:
    pattern = CONFIRM.get(agent)
    return bool(pattern and pattern.search(pane))


def run(cell: Cell) -> Outcome:
    engine, old = cell.engine, cell.target
    if not warm_up(cell, old, REPLY_TIMEOUT_S[cell.agent]):
        return precondition_failed("warm-up turn not answered")
    m, current = engine.current_target(cell.m, old)
    cell.m = m
    steps: list[Step] = []
    notes: list[str] = []
    entries = []
    tokens: list[str] = []
    evidence: set[str] = set()
    for name, command in STALE_COMMANDS[cell.agent].items():
        if command is None:
            notes.append(f"{name}=n/a")
            continue
        if needs_warm_up(name, steps):
            if not warm_up(cell, current, REPLY_TIMEOUT_S[cell.agent]):
                return precondition_failed(f"warm-up of the visible session before {command} not answered")
            notes.append(f"{name}-warm-up")
        cell.type_text(current, command, submit=True)
        done = DONE.get(name)
        host = engine.host_of(current)
        asks = cell.agent in CONFIRM and poll(
            lambda ref=current.host_ref, h=host: confirm_visible(cell.agent, h.capture(ref)), CONFIRM_WAIT_S, 0.5)
        if asks:
            cell.send_key(current, "Enter")
            notes.append(f"{name}-confirmed")
        took = not done or poll(lambda n=name, ref=current.host_ref, h=host: command_done(n, h.capture(ref)),
                                COMMAND_TIMEOUT_S[name])
        if not took or not engine.wait_idle(current, COMMAND_TIMEOUT_S[name], settle_s=3.0):
            engine.snapshot(current, f"precondition-{name}")
            return precondition_failed(f"receiver not ready after {command}")
        before = current.session_id
        token = new_token()
        text = envelope(token, BODY.format(step=command))
        receipt = cell.owned_send(current, text)

        def hit(tok: str = token, where: Target = current):
            found = [t for t in engine.all_transcripts(where) if acked(t.entries(), tok)]
            return found[0] if found and engine.idle(where, found[0]) else None

        transcript = poll(hit, REPLY_TIMEOUT_S[cell.agent])
        finished = transcript is not None
        if transcript is None:
            holders = [t for t in engine.all_transcripts(current) if t.find_token(token)]
            transcript = holders[0] if holders else None
        out = observe(cell, current, token, text, receipt, transcript, finished, f"after-{name}")
        where = landed([transcript_session(transcript)]
                       if transcript and out.delivery == Delivery.DELIVERED else [], before)
        steps.append(Step(name, out.delivery, out.ack, out.intact, where))
        notes.append(f"{name}={out.delivery.value}@{where}")
        notes += [n for n in out.notes if n.startswith(("reply-timeout", "body-mismatch", "stuck", "transcript="))]
        entries += out.entries
        tokens.append(token)
        evidence |= set(out.evidence)
        m, current = engine.current_target(cell.m, current)
        cell.m = m
    delivery, ack, intact = combine(steps)
    return Outcome(delivery=delivery, intact=intact, ack=ack, evidence=sorted(evidence), notes=notes,
                   entries=entries, tokens=tokens, target=current)
