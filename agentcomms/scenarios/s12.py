import time
from dataclasses import replace

from agentcomms import backends, markers
from agentcomms.engine import REPLY_TIMEOUT_S, AgentLostError
from agentcomms.model import Delivery
from agentcomms.scenarios.common import Cell, Outcome, precondition_failed, send_and_observe, warm_up

BODY = "This message was sent after your backing server was restarted."
RECONNECT_S = 5.0
RESPAWNED_NOTE = markers.RESPAWNED
LOST_NOTE = markers.LOST_BY_RESTART


def not_applicable(agent: str, backend: str, adapter=None) -> str | None:
    if backend != "none" or getattr(adapter, "bridge_daemon", False):
        return None
    return "no backing server (backend none)"


def run(cell: Cell) -> Outcome:
    if not warm_up(cell, cell.target, REPLY_TIMEOUT_S[cell.agent]):
        return precondition_failed("warm-up turn not answered before the backend restart")
    cell.engine.check_owned(cell.target)
    try:
        detail = cell.adapter.restart_backend(cell.target)
    except backends.BackendError as e:
        return Outcome(Delivery.ERROR, notes=[f"backend-restart-failed: {e}"])
    if detail is None:
        return precondition_failed(f"adapter {cell.adapter.name} has no backend to restart")
    cell.m = cell.engine.track_restarted_backend(cell.m, cell.target)
    cell.m = cell.engine.track_bridge_daemons(cell.m, cell.adapter, cell.target)
    time.sleep(RECONNECT_S)
    try:
        cell.m, target, respawned = cell.engine.readopt_agent(cell.m, cell.target, cell.launched.binary,
                                                              getattr(cell.adapter, "startup_marker", None))
    except AgentLostError as e:
        cell.engine.snapshot(cell.target, "after-restart")
        return Outcome(Delivery.LOST, notes=[f"backend-restart={detail}", f"{LOST_NOTE}: {e}"],
                       receiver_exit_expected=True)
    cell.launched = replace(cell.launched, target=target)
    cell.engine.snapshot(cell.target, "after-restart")
    out = send_and_observe(cell, cell.target, BODY, REPLY_TIMEOUT_S[cell.agent])
    out.notes.append(f"backend-restart={detail}")
    if respawned:
        out.notes.append(RESPAWNED_NOTE)
    return out
