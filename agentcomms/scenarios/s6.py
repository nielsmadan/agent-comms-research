from dataclasses import replace

from agentcomms import manifest, procs
from agentcomms.engine import REPLY_TIMEOUT_S, envelope, new_token, poll, receiver_hits
from agentcomms.model import Target
from agentcomms.scenarios.common import Cell, Outcome, precondition_failed, send_and_observe, warm_up, with_target

DOWN_BODY = "This message was sent while you were not running."
AFTER_BODY = "This message was sent after you were resumed."
QUEUE_WAIT_S = 15.0
KILL_GRACE_S = 5.0


def down_fate(accepted: bool, seen_after_resume: bool) -> str:
    if not accepted:
        return "rejected"
    return "queued" if seen_after_resume else "lost"


def kill(cell: Cell, target: Target) -> str:
    cell.engine.check_owned(target)
    pid = target.agent_pid
    sigkilled = manifest.terminate_same({pid}, KILL_GRACE_S)
    poll(lambda: not procs.alive(pid), 5.0, 0.2)
    return "SIGKILL" if sigkilled else "SIGTERM"


def down_seen(transcripts, token: str) -> bool:
    return any(receiver_hits(t.entries(), token) for t in transcripts)


def run(cell: Cell) -> Outcome:
    engine = cell.engine
    if not warm_up(cell, cell.target, REPLY_TIMEOUT_S[cell.agent]):
        return precondition_failed("warm-up turn not answered")
    m, target = engine.current_target(cell.m, cell.target)
    cell.m = m
    if not target.session_id or not target.agent_pid:
        return precondition_failed("no session id or agent pid to kill and resume")
    signal_used = kill(cell, target)
    pane_gone = poll(lambda: not engine.host_of(target).alive(target.host_ref), 10.0, 0.5)
    down_token = new_token()
    down = cell.owned_send(target, envelope(down_token, DOWN_BODY), live=False)
    m, launched = engine.resume(cell.m, replace(cell.launched, target=target), target.session_id)
    m, resumed = engine.current_target(m, launched.target)
    launched = replace(launched, target=resumed)
    after = with_target(cell, m, launched)
    seen = poll(lambda: down_seen(engine.all_transcripts(resumed), down_token), QUEUE_WAIT_S)
    out = send_and_observe(after, resumed, AFTER_BODY, REPLY_TIMEOUT_S[cell.agent])
    out.tokens = [down_token, *out.tokens]
    out.notes += [f"down={down_fate(down.accepted, bool(seen))}", f"killed={signal_used}",
                  f"pane={'closed' if pane_gone else 'survived'}",
                  f"session={'same' if resumed.session_id == target.session_id else 'new'}"]
    if not down.accepted:
        out.notes.append(f"down-send: {down.detail[:80]}")
    return out
