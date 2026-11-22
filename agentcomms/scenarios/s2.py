import time

from agentcomms import gate, procs
from agentcomms.engine import RECEIVED_KINDS, REPLY_TIMEOUT_S, envelope, new_token, poll
from agentcomms.model import Delivery
from agentcomms.scenarios.common import Cell, Outcome, observe, precondition_failed
from agentcomms.transcripts.common import Entry

BODY = "This message was sent while your shell command was still running."
MIDTURN_WINDOW_S = 10.0
GATE_TIMEOUT_S = 90.0
TURN_END = frozenset({"task_complete", "turn_aborted", "end_turn"})


def gate_prompt(command: str) -> str:
    return (f"Run this exact shell command and wait for it to finish; it blocks until it is released: {command} "
            "When it has finished, reply with the single word DONE.")


def gate_running(entries: list[Entry], path: str, marker: str) -> bool:
    started = any(k == "tool_use" and path in t for _, k, t in entries)
    finished = any(k == "tool_result" and marker in t for _, k, t in entries)
    return started and not finished


def classify_midturn(entries: list[Entry], token: str, marker: str) -> Delivery | None:
    tok = next((i for i, (_, k, t) in enumerate(entries) if token in t and k in RECEIVED_KINDS), None)
    if tok is None:
        return None
    res = next((i for i, (_, k, t) in enumerate(entries) if k == "tool_result" and marker in t), None)
    if res is None or tok < res:
        return Delivery.INTERRUPTED
    between = entries[res + 1:tok]
    if any(k == "system" and t in TURN_END for _, k, t in between):
        return Delivery.QUEUED
    if any(k == "system" and t in TURN_END for _, k, t in entries):
        return Delivery.INTERRUPTED
    last_reply = max((i for i, (_, k, _t) in enumerate(between) if k == "assistant"), default=None)
    if last_reply is not None and not any(k == "tool_use" for _, k, _t in between[last_reply:]):
        return Delivery.QUEUED
    return Delivery.INTERRUPTED


def midturn_verdict(delivery: Delivery, entries: list[Entry], token: str, marker: str,
                    hidden: bool) -> tuple[Delivery, list[str]]:
    if delivery != Delivery.DELIVERED:
        return delivery, []
    if hidden:
        return delivery, ["parallel-thread"]
    return classify_midturn(entries, token, marker) or delivery, []


def run(cell: Cell) -> Outcome:
    target, engine = cell.target, cell.engine
    path = gate.create(gate.gate_path(cell.m.run_id))
    cell.m = engine.add_socket(cell.m, path)
    marker = gate.open_marker(cell.m.run_id)
    try:
        cell.type_text(target, gate_prompt(gate.gate_command(path)), submit=True)

        def gated() -> bool:
            transcript = engine.transcript_for(target)
            entries = transcript.entries() if transcript else []
            return gate_running(entries, str(path), marker) and gate.reader_running(procs.ps_rows(), path)

        if not poll(gated, GATE_TIMEOUT_S):
            engine.snapshot(target, "precondition")
            return precondition_failed("gated tool call not running (no tool_use without result, or no reader)")
        token = new_token()
        text = envelope(token, BODY)
        receipt = cell.owned_send(target, text)
        time.sleep(MIDTURN_WINDOW_S)
        engine.snapshot(target, "midturn")
        released = gate.release(path, marker)
        transcript, finished = engine.wait_for_token(target, token, REPLY_TIMEOUT_S[cell.agent])
        out = observe(cell, target, token, text, receipt, transcript, finished)
    finally:
        gate.release(path, marker)
        gate.remove(path)
    out.delivery, extra = midturn_verdict(out.delivery, out.entries, token, marker, "hidden-thread" in out.notes)
    out.notes += extra
    out.notes.append(f"gate-released={'yes' if released else 'no-reader'}")
    return out
