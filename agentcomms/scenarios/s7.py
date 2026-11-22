import time

from agentcomms.engine import REPLY_TIMEOUT_S, envelope, new_token, poll
from agentcomms.model import DraftFate
from agentcomms.scenarios.common import RECEIVED_KINDS, Cell, Outcome, composer_text, observe, precondition_failed
from agentcomms.transcripts.common import Entry

BODY = "This message was sent while a human had a half-typed draft in the input box."
DRAFT_VISIBLE_S = 10.0


def draft_text(marker: str) -> str:
    return f"{marker} please also look at the"


def classify_draft(entries: list[Entry], token: str, marker: str, composer: str) -> DraftFate:
    with_draft = [t for _, k, t in entries if k in RECEIVED_KINDS and marker in t]
    if any(token in t for t in with_draft):
        return DraftFate.MERGED
    if with_draft:
        return DraftFate.SUBMITTED
    if marker in composer:
        return DraftFate.MERGED if token in composer else DraftFate.PRESERVED
    return DraftFate.LOST


def run(cell: Cell) -> Outcome:
    target, engine = cell.target, cell.engine
    marker = f"DRAFT-{new_token()}"
    cell.type_text(target, draft_text(marker), submit=False)
    visible = poll(lambda: marker in composer_text(cell.agent, engine.host_of(target).capture(target.host_ref)),
                   DRAFT_VISIBLE_S, 0.5)
    if not visible:
        engine.snapshot(target, "precondition")
        return precondition_failed("draft not visible in the input box")
    engine.snapshot(target, "draft")
    token = new_token()
    text = envelope(token, BODY)
    receipt = cell.owned_send(target, text)
    transcript, finished = engine.wait_for_token(target, token, REPLY_TIMEOUT_S[cell.agent])
    time.sleep(1.0)
    out = observe(cell, target, token, text, receipt, transcript, finished)
    out.draft_fate = classify_draft(out.entries, token, marker, composer_text(cell.agent, out.final_pane))
    out.evidence = sorted({*out.evidence, "pane"} if marker in out.final_pane else set(out.evidence))
    out.notes.append(f"draft={marker}")
    return out
