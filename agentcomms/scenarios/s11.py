import re
import time

from agentcomms.engine import DIGIT_FREE, envelope, new_token, poll
from agentcomms.scenarios.common import Cell, Outcome, dismiss, held_outcome, precondition_failed

BODY = "This message was sent while a picker dialog was open."
MODAL_COMMANDS = {"claude": "/model", "codex": "/model", "pi": "/model", "opencode": "/models", "droid": "/model"}
MODAL = {
    "claude": re.compile(r"Select model\b"),
    "codex": re.compile(r"Select (Model( and Effort)?|Reasoning Level)"),
    "pi": re.compile(r"Ctrl\+S to set as default · Escape/Ctrl\+C to cancel"),
    "opencode": re.compile(r"Select model", re.I),
    "droid": re.compile(r"(Select model|Choose a model)", re.I),
}
MODEL_SHOWN = {
    "claude": re.compile(r"(?:▜█+▀\s+|Set model to )((?:Haiku|Sonnet|Opus|Fable) \d+(?:\.\d+)?)"),
    "codex": re.compile(r"(GPT-[\w.]+(?:-\w+)? (?:minimal|low|medium|high|xhigh))"),
}
MODAL_TIMEOUT_S = 15.0
OBSERVE_S = 8.0
DISMISS_TRIES = 2


def modal_visible(agent: str, pane: str) -> bool:
    return bool(MODAL[agent].search(pane))


def modal_title(agent: str, pane: str) -> str | None:
    matches = [m.group(0) for m in MODAL[agent].finditer(pane)]
    return matches[-1] if matches else None


def selection_made(agent: str, modal_pane: str, after_send: str) -> bool:
    switched = modal_visible(agent, after_send) and modal_title(agent, after_send) != modal_title(agent, modal_pane)
    return "Set model to" in after_send or switched


def shown_model(agent: str, pane: str) -> str | None:
    pattern = MODEL_SHOWN.get(agent)
    matches = [m.group(1) for m in pattern.finditer(pane)] if pattern else []
    return matches[-1] if matches else None


def run(cell: Cell) -> Outcome:
    target, engine = cell.target, cell.engine
    before = shown_model(cell.agent, engine.host_of(target).capture(target.host_ref))
    cell.type_text(target, MODAL_COMMANDS[cell.agent], submit=True)
    host = engine.host_of(target)
    if not poll(lambda: modal_visible(cell.agent, host.capture(target.host_ref)), MODAL_TIMEOUT_S, 0.5):
        engine.snapshot(target, "precondition")
        return precondition_failed("modal not visible")
    modal_pane = engine.snapshot(target, "modal")
    token = new_token(DIGIT_FREE)
    text = envelope(token, BODY)
    receipt = cell.owned_send(target, text)
    time.sleep(OBSERVE_S)
    after_send = engine.snapshot(target, "after-send")
    release_ts = dismiss(cell, target, lambda pane: modal_visible(cell.agent, pane), DISMISS_TRIES, 1.5)
    out = held_outcome(cell, target, token, text, receipt, release_ts)
    after = shown_model(cell.agent, out.final_pane)
    out.notes.append(f"modal={'open-after-send' if modal_visible(cell.agent, after_send) else 'closed-by-send'}")
    if selection_made(cell.agent, modal_pane, after_send):
        out.notes.append("modal-selection-made")
    if before and after and before != after:
        out.harmful = True
        out.notes.append(f"model-changed={before.replace(' ', '_')}->{after.replace(' ', '_')}")
    return out
