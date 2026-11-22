from agentcomms.engine import REPLY_TIMEOUT_S, S1_BODY
from agentcomms.scenarios.common import Cell, Outcome, send_and_observe


def run(cell: Cell) -> Outcome:
    return send_and_observe(cell, cell.target, S1_BODY, REPLY_TIMEOUT_S[cell.agent])
