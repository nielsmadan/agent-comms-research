import re
import time
from dataclasses import dataclass, field, replace

from agentcomms import checkpoint, markers
from agentcomms.engine import (
    READY_PANE,
    RECEIVED_KINDS,
    REPLY_TIMEOUT_S,
    Engine,
    Launched,
    api_errors,
    classify_ack,
    classify_delivery,
    envelope,
    new_token,
    receiver_hits,
    recorded_body,
)
from agentcomms.model import Ack, Adapter, AgentName, Delivery, DraftFate, Manifest, SendReceipt, Target, Transcript
from agentcomms.paths import DEFERRED_LOG
from agentcomms.records import ResultRecord, sha256, tildify
from agentcomms.transcripts.common import Entry

PROMPT_LINE = {
    "claude": re.compile(r"^❯ ?"),
    "codex": re.compile(r"^› ?"),
    "opencode": re.compile(r"^\s*┃ ?"),
    "droid": re.compile(r"^│ > ?"),
}
PI_BORDER = re.compile(r"^─{20,}$")
PASTE_PLACEHOLDER = re.compile(r"\[(Pasted (text|Content)|Image)", re.I)
WARMUP_BODY = "Warm-up turn from the agentcomms harness; no other action is needed."


@dataclass
class Cell:
    engine: Engine
    m: Manifest
    launched: Launched
    adapter: Adapter
    scenario: str
    stage: str
    rep: int
    send_s: list[float] = field(default_factory=list)

    @property
    def target(self) -> Target:
        return self.launched.target

    @property
    def agent(self) -> AgentName:
        return self.launched.target.agent

    def owned_send(self, target: Target, text: str, live: bool = True) -> SendReceipt:
        return self.timed_owned_send(target, text, live)[0]

    def timed_owned_send(self, target: Target, text: str, live: bool = True) -> tuple[SendReceipt, float]:
        self.engine.check_owned(target, live)
        called = time.monotonic()
        receipt = self.adapter.send(target, text)
        returned = time.monotonic()
        self.send_s.append(returned - receipt.sent_mono - receipt.waited_s)
        self.m = self.engine.track_spawned(self.m, receipt.spawned)
        return receipt, returned - called

    def type_text(self, target: Target, text: str, submit: bool) -> None:
        self.engine.check_owned(target)
        self.engine.host_of(target).type_text(target.host_ref, text, submit)

    def send_key(self, target: Target, key: str) -> None:
        self.engine.check_owned(target)
        self.engine.host_of(target).send_key(target.host_ref, key)


@dataclass
class Outcome:
    delivery: Delivery
    intact: bool | None = None
    draft_fate: DraftFate = DraftFate.NA
    ack: Ack = Ack.NONE
    harmful: bool = False
    retries: int = 0
    latency_s: float | None = None
    evidence: list[str] = field(default_factory=list)
    sent: str | None = None
    recv: str | None = None
    notes: list[str] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)
    final_pane: str = ""
    target: Target | None = None
    receiver_exit_expected: bool = False


CRASH_PAUSES = markers.CRASH


def precondition_failed(cause: str, entries: list[Entry] | None = None) -> Outcome:
    return Outcome(Delivery.ERROR, notes=[f"precondition: {cause}"], entries=entries or [])


def composer_text(agent: str, pane: str) -> str:
    lines = pane.rstrip("\n").splitlines()
    if agent == "pi":
        borders = [i for i, line in enumerate(lines) if PI_BORDER.match(line)]
        return "\n".join(lines[borders[-2] + 1:borders[-1]]) if len(borders) >= 2 else ""
    prompt = PROMPT_LINE.get(agent)
    starts = [i for i, line in enumerate(lines) if prompt and prompt.match(line)]
    if not starts:
        return ""
    block = last_block(starts)
    footer = READY_PANE[agent][1]
    return "\n".join(prompt.sub("", line, count=1) if i in block else line
                     for i, line in enumerate(lines)
                     if i >= min(block) and not footer.search(line) and not line.startswith("─"))


def last_block(indices: list[int]) -> set[int]:
    present = set(indices)
    first = indices[-1]
    while first - 1 in present:
        first -= 1
    return set(range(first, indices[-1] + 1))


def stuck_note(agent: str, pane: str, token: str, recorded: bool) -> str | None:
    composer = composer_text(agent, pane)
    if recorded:
        return None
    if token in composer:
        return "stuck-in-composer"
    return "stuck-in-composer (paste placeholder)" if PASTE_PLACEHOLDER.search(composer) else None


def held_for(entries: list[Entry], token: str, sent_at: float) -> bool:
    return any(k == "held" and (token in t or ts >= sent_at) for ts, k, t in entries)


def first_seen(entries: list[Entry], token: str) -> float | None:
    seen = receiver_hits(entries, token)
    return seen[0][0] if seen else None


def classify_held(accepted: bool, seen_ts: float | None, release_ts: float | None) -> Delivery:
    if not accepted:
        return Delivery.REJECTED
    if seen_ts is None:
        return Delivery.LOST
    if release_ts is not None and seen_ts >= release_ts:
        return Delivery.QUEUED
    return Delivery.DELIVERED


def pane_log_text(launched: Launched) -> str:
    return launched.pane_log.read_text(errors="replace") if launched.pane_log.exists() else ""


def evidence_for(cell: Cell, entries: list[Entry], tokens: list[str], final_pane: str) -> list[str]:
    log = pane_log_text(cell.launched)
    in_transcript = any(tok in e[2] for e in entries for tok in tokens)
    in_pane = any(tok in log or tok in final_pane for tok in tokens)
    return (["transcript"] if in_transcript else []) + (["pane"] if in_pane else [])


def wait_notes(finished: bool, transcript: Transcript | None) -> list[str]:
    return (["reply-timeout"] if not finished else []) + (["transcript-not-found"] if transcript is None else [])


def transcript_note(cell: Cell, transcript: Transcript | None) -> list[str]:
    if transcript is None:
        return []
    root = cell.engine.layout.root
    shown = transcript.path.relative_to(root) if transcript.path.is_relative_to(root) else transcript.path
    return [f"transcript={shown}"]


def other_thread(transcript: Transcript | None, shown: Transcript | None) -> bool:
    return transcript is not None and shown is not None and transcript.path != shown.path


def observe(cell: Cell, target: Target, token: str, text: str, receipt: SendReceipt,
            transcript: Transcript | None, finished: bool, label: str = "final") -> Outcome:
    entries = transcript.entries() if transcript else []
    seen = receiver_hits(entries, token)
    received = [e for e in seen if e[1] in RECEIVED_KINDS]
    held = held_for(entries, token, receipt.sent_at)
    delivery = classify_delivery(receipt.accepted, seen, held)
    assistant = [t for _, k, t in entries if k == "assistant"]
    ack = classify_ack(delivery == Delivery.DELIVERED, assistant, token)
    body = recorded_body(received, cell.adapter)
    final_pane = cell.engine.snapshot(target, label)
    notes = wait_notes(finished, transcript)
    if not receipt.accepted:
        notes.append(f"send-failed: {receipt.detail}")
    if body is not None and body != text:
        notes.append(f"body-mismatch; diff={cell.engine.write_body_diff(target.run_id, target.agent, text, body)}")
    if held:
        notes.append("held-for-approval")
    stuck = stuck_note(target.agent, final_pane, token, bool(seen))
    if stuck:
        notes.append(stuck)
    if seen and other_thread(transcript, cell.engine.transcript_for(target)):
        notes.append("hidden-thread")
    notes += transcript_note(cell, transcript)
    latency = round(seen[0][0] - receipt.sent_at, 3) if seen else None
    return Outcome(delivery=delivery, intact=(body == text) if body is not None else None, ack=ack,
                   retries=receipt.retries, latency_s=latency,
                   evidence=evidence_for(cell, entries, [token], final_pane), sent=text, recv=body, notes=notes,
                   entries=entries, tokens=[token], final_pane=final_pane, target=target)


def dismiss(cell: Cell, target: Target, visible, tries: int, wait_s: float) -> float | None:
    release_ts = None
    for _ in range(tries):
        if not visible(cell.engine.host_of(target).capture(target.host_ref)):
            break
        release_ts = release_ts or time.time()
        cell.send_key(target, "Escape")
        time.sleep(wait_s)
    return release_ts


def held_outcome(cell: Cell, target: Target, token: str, text: str, receipt: SendReceipt,
                 release_ts: float | None) -> Outcome:
    transcript, finished = cell.engine.wait_for_token(target, token, REPLY_TIMEOUT_S[cell.agent])
    out = observe(cell, target, token, text, receipt, transcript, finished)
    if out.delivery == Delivery.DELIVERED:
        out.delivery = classify_held(receipt.accepted, first_seen(out.entries, token), release_ts)
    return out


def send_and_observe(cell: Cell, target: Target, body: str, timeout_s: float, label: str = "final") -> Outcome:
    token = new_token()
    text = envelope(token, body)
    receipt = cell.owned_send(target, text)
    transcript, finished = cell.engine.wait_for_token(target, token, timeout_s)
    return observe(cell, target, token, text, receipt, transcript, finished, label)


def warm_up(cell: Cell, target: Target, timeout_s: float) -> bool:
    token = new_token()
    cell.type_text(target, envelope(token, WARMUP_BODY), submit=True)
    _, finished = cell.engine.wait_for_token(target, token, timeout_s)
    return finished


def finish(cell: Cell, out: Outcome, wall0: float, mono0: float) -> ResultRecord:
    notes = list(out.notes)
    delivery = out.delivery
    expected = delivery == Delivery.NA or out.receiver_exit_expected
    gone = None if expected else cell.engine.receiver_gone(out.target or cell.target)
    if gone:
        notes.append(f"{CRASH_PAUSES} ({gone}; was {delivery.value})")
        delivery = Delivery.ENV_ERROR
    wall1, mono1 = time.time(), time.monotonic()
    if delivery not in (Delivery.NA, Delivery.ENV_ERROR) and (checkpoint.slept(wall0, mono0, wall1, mono1)
                                            or not checkpoint.network_ok()):
        delivery = Delivery.ENV_ERROR
        notes.append("sleep-or-network")
    errors = api_errors(out.entries)
    if errors and out.ack != Ack.ACKED:
        delivery = Delivery.ENV_ERROR
        notes.append(f"{markers.API_ERROR}: {errors[-1][:120]}")
    latency = out.latency_s if delivery not in (Delivery.ENV_ERROR, Delivery.ERROR) else None
    ready = [f"ready={cell.launched.ready_signal}"] + ([f"dialogs={','.join(cell.launched.dialogs)}"]
                                                       if cell.launched.dialogs else []) + list(cell.launched.notes)
    if cell.send_s:
        notes.append(f"send_s={max(cell.send_s):.2f}")
    notes += getattr(cell.engine.host_of(cell.target), "take_notes", lambda: [])()
    notes += deferred_notes(cell.engine.layout.run_dir(cell.m.run_id))
    return ResultRecord(
        run_id=cell.m.run_id, stage=cell.stage, agent=cell.agent, versions=cell.launched.versions,
        mechanism=cell.adapter.name, host=cell.target.host, backend=cell.target.backend, scenario=cell.scenario,
        rep=cell.rep, sandbox=cell.engine.sandbox, delivery=delivery, intact=out.intact, draft_fate=out.draft_fate,
        ack=out.ack,
        harmful=out.harmful, retries=out.retries, latency_s=latency, evidence=out.evidence,
        sent_sha256=sha256(out.sent), recv_sha256=sha256(out.recv), token=",".join(out.tokens) or None,
        notes=tildify("; ".join(ready + notes), cell.engine.user_home), ts=time.time(),
    )


def deferred_summary(log_text: str) -> str | None:
    lines = [line.split() for line in log_text.splitlines() if line.strip()]
    outcomes = [parts[2] for parts in lines if len(parts) > 2 and parts[2] in ("ok", "error")]
    if not outcomes:
        return None
    return f"deferred={outcomes.count('ok')}/{len(outcomes)}"


def deferred_notes(run_dir) -> list[str]:
    path = run_dir / DEFERRED_LOG
    summary = deferred_summary(path.read_text(errors="replace")) if path.exists() else None
    pending = len(list((run_dir / "deferred").glob("*/*.msg")))
    return ([summary] if summary else []) + ([f"deferred-pending={pending}"] if pending else [])


def with_target(cell: Cell, m: Manifest, launched: Launched) -> Cell:
    return replace(cell, m=m, launched=launched)
