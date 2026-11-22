import re
import time

from agentcomms.engine import REPLY_TIMEOUT_S, envelope, new_token, poll
from agentcomms.scenarios.common import Cell, Outcome, observe, precondition_failed

BODY = "This message was pushed while a human was attached to your terminal."
HUMAN_TIMEOUT_S = 120.0
RENDER_WAIT_S = 45.0
UNSAFE_HUMAN = re.compile(r"^\s*[/!@#]|/loop|\bimport\b", re.I)
PROMPT_TAIL = "│┃"
HUMAN_LEAD = "exactly"
ACK_LEAD = '"'


def human_text(marker: str) -> str:
    return f"Reply with exactly {marker} and nothing else."


def safe_human_text(text: str) -> bool:
    return not UNSAFE_HUMAN.search(text)


def reply_rendered(stream: str, needle: str, prompt_lead: str) -> bool:
    flat = re.sub(r"\s+", "", stream)
    hits = re.finditer(re.escape(re.sub(r"\s+", "", needle)), flat)
    return any(not flat[:m.start()].rstrip(PROMPT_TAIL).endswith(prompt_lead) for m in hits)


def prompt_rendered(stream: str, token: str) -> bool:
    return f"ACK-REQUEST{token}" in re.sub(r"\s+", "", stream)


def render_verdict(reply_shown: bool, prompt_shown: bool) -> str:
    if reply_shown:
        return "yes" if prompt_shown else "reply-only"
    return "no"


def human_turn_rendered(client, marker: str, wait_s: float, interval_s: float = 0.5) -> bool:
    return poll(lambda: reply_rendered(client.text(), marker, HUMAN_LEAD), wait_s, interval_s)


def client_env(environ: dict[str, str]) -> dict[str, str]:
    keep = {k: environ[k] for k in ("HOME", "PATH", "LANG", "USER", "TMPDIR") if k in environ}
    return keep | {"TERM": "xterm-256color"}


def answered(cell: Cell, marker: str) -> bool:
    transcript = cell.engine.transcript_for(cell.target)
    if transcript is None:
        return False
    replied = any(k == "assistant" and marker in t for _, k, t in transcript.entries())
    return replied and cell.engine.idle(cell.target, transcript)


def run(cell: Cell) -> Outcome:
    target, engine = cell.target, cell.engine
    log = engine.layout.run_dir(target.run_id) / f"attach-{cell.agent}.log"
    host = engine.host_of(target)
    client = host.attach_client(target.host_ref, log, engine.layout.run_dir(target.run_id),
                                client_env(engine.environ))
    cell.m = engine.add_pgid(cell.m, client.proc.pid)
    try:
        marker = f"HUMAN-{new_token()}"
        text = human_text(marker)
        if not safe_human_text(text):
            raise ValueError(f"human-proxy text would open a command or import screen: {text!r}")
        cell.type_text(target, text, submit=True)
        if not poll(lambda: answered(cell, marker), HUMAN_TIMEOUT_S):
            engine.snapshot(target, "precondition")
            return precondition_failed("human-typed prompt not answered")
        if not human_turn_rendered(client, marker, RENDER_WAIT_S):
            return precondition_failed("attached client did not render the human turn")
        token = new_token()
        pushed = envelope(token, BODY)
        receipt = cell.owned_send(target, pushed)
        transcript, finished = engine.wait_for_token(target, token, REPLY_TIMEOUT_S[cell.agent])
        out = observe(cell, target, token, pushed, receipt, transcript, finished)
        shown = poll(lambda: reply_rendered(client.text(), f"ACK {token}", ACK_LEAD), RENDER_WAIT_S, 0.5)
        prompt_shown = prompt_rendered(client.text(), token)
        out.evidence = sorted({*out.evidence, "attached-client"} if shown else set(out.evidence))
        rendered = "no" if "hidden-thread" in out.notes else render_verdict(shown, prompt_shown)
        out.notes += [f"rendered={rendered}", f"human={marker}",
                      f"attach_log={log.relative_to(engine.layout.root)}"]
        return out
    finally:
        host.detach_client(target.host_ref)
        time.sleep(0.5)
        client.close()
