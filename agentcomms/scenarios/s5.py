import time
from dataclasses import dataclass

from agentcomms import markers
from agentcomms.engine import RECEIVED_KINDS, REPLY_TIMEOUT_S, envelope, new_token
from agentcomms.model import Ack, Delivery, SendReceipt
from agentcomms.scenarios.common import Cell, Outcome, evidence_for, transcript_note, wait_notes
from agentcomms.transcripts.common import Entry

COUNT = 5
WINDOW_S = 1.0


@dataclass(frozen=True)
class Burst:
    received: int
    order: str
    merged: bool
    ts_tie: bool
    merges: int = 0


def positions(entries: list[Entry], tokens: list[str]) -> dict[str, tuple[int, int]]:
    found: dict[str, tuple[int, int]] = {}
    for i, (_, kind, text) in enumerate(entries):
        if kind not in RECEIVED_KINDS:
            continue
        for tok in tokens:
            if tok not in found and tok in text:
                found[tok] = (i, text.index(tok))
    return found


def classify_burst(entries: list[Entry], tokens: list[str]) -> Burst:
    found = positions(entries, tokens)
    seen = [t for t in tokens if t in found]
    by_position = sorted(seen, key=lambda t: found[t])
    holders = {found[t][0] for t in seen}
    stamps = [entries[i][0] for i in sorted(holders)]
    tie = len(set(stamps)) < len(stamps)
    merges = len(seen) - len(holders)
    return Burst(len(seen), "in-order" if by_position == seen else "reordered", merges > 0, tie, merges)


def burst_ack(acks: int, received: int) -> Ack:
    if acks == COUNT:
        return Ack.ACKED
    return Ack.MODEL_NONCOMPLIANT if received else Ack.NONE


def received_bodies(entries: list[Entry], tokens: list[str], unwrap) -> list[str]:
    return [unwrap(t) for _, k, t in entries if k in RECEIVED_KINDS and any(tok in t for tok in tokens)]


def all_intact(bodies: list[str], texts: list[str]) -> bool:
    return all(text in bodies for text in texts)


def burst_verdict(window: float, adapter_s: float) -> tuple[Delivery, str] | None:
    if window <= WINDOW_S:
        return None
    if adapter_s > WINDOW_S:
        return Delivery.NA, f"n/a: adapter cannot burst (window {window:.2f}s)"
    return Delivery.ERROR, (f"precondition: {markers.BURST_WINDOW} (window {window:.2f}s, adapter sends "
                            f"{adapter_s:.2f}s; the harness took the rest)")


def timed_send(cell: Cell, target, text: str) -> tuple[SendReceipt, float]:
    return cell.timed_owned_send(target, text, live=False)


def run(cell: Cell) -> Outcome:
    target, engine = cell.target, cell.engine
    tokens = [new_token() for _ in range(COUNT)]
    texts = [envelope(tok, f"Burst message {i + 1} of {COUNT}.") for i, tok in enumerate(tokens)]
    engine.check_owned(target)
    start = time.monotonic()
    sent = [timed_send(cell, target, text) for text in texts]
    window = time.monotonic() - start
    receipts = [r for r, _ in sent]
    adapter_s = sum(d for _, d in sent)
    transcript, finished = engine.wait_for_acks(target, tokens, REPLY_TIMEOUT_S[cell.agent])
    entries = transcript.entries() if transcript else []
    final_pane = engine.snapshot(target, "final")
    burst = classify_burst(entries, tokens)
    assistant = [t for _, k, t in entries if k == "assistant"]
    acks = sum(any(f"ACK {tok}" in t for t in assistant) for tok in tokens)
    if not all(r.accepted for r in receipts):
        delivery = Delivery.REJECTED
    else:
        delivery = Delivery.DELIVERED if burst.received == COUNT else Delivery.LOST
    bodies = received_bodies(entries, tokens, cell.adapter.unwrap)
    sent, recv = "\n".join(texts), "\n".join(bodies) if bodies else None
    intact = all_intact(bodies, texts) if burst.received else None
    first = [e for e in entries if any(tok in e[2] for tok in tokens) and e[1] in RECEIVED_KINDS]
    notes = [f"burst={burst.received}/{COUNT}", f"order={burst.order}", f"merged={'yes' if burst.merged else 'no'}",
             f"merge_count={burst.merges}", f"acks={acks}/{COUNT}", f"send_window={window:.2f}s"]
    unmet = burst_verdict(window, adapter_s)
    if unmet:
        delivery = unmet[0]
        notes.insert(0, unmet[1])
    notes += [f"send-failed {i + 1}: {r.detail}" for i, r in enumerate(receipts) if not r.accepted]
    if burst.ts_tie:
        notes.append("order unverifiable (timestamps tie)")
    notes += wait_notes(finished, transcript)
    if recv is not None and recv != sent:
        notes.append(f"body-mismatch; diff={engine.write_body_diff(target.run_id, target.agent, sent, recv)}")
    notes += transcript_note(cell, transcript)
    return Outcome(delivery=delivery, intact=intact, ack=burst_ack(acks, burst.received),
                   retries=sum(r.retries for r in receipts),
                   latency_s=round(first[0][0] - receipts[0].sent_at, 3) if first and not unmet else None,
                   evidence=evidence_for(cell, entries, tokens, final_pane), sent=sent, recv=recv, notes=notes,
                   entries=entries, tokens=tokens, final_pane=final_pane, target=target)
