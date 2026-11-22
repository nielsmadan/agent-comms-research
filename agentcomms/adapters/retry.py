import re
from itertools import takewhile

from agentcomms.engine import match_dialog, pane_ready
from agentcomms.scenarios.common import PASTE_PLACEHOLDER, composer_text

RETRY_LIMIT = 3
RETRY_WAIT_S = 1.5
FINGERPRINT = 16
BOX = re.compile(r"[│┃╭╮╰╯─╹▀>]")
PLACEHOLDER = re.compile(r"\s*(?:Ask Codex to do anything|Ask anything\S*|Message \S+|Type your message\S*)\s*", re.I)
FIRST_LINE_ONLY = frozenset({"claude", "codex", "droid"})
OPENCODE_MODE_LINE = re.compile(r"^\s*Build (auto )?· ")


def squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def input_lines(agent: str, composer: str) -> str:
    lines = composer.splitlines()
    if agent == "opencode":
        return "\n".join(takewhile(lambda line: not OPENCODE_MODE_LINE.match(line), lines))
    return lines[0] if agent in FIRST_LINE_ONLY and lines else composer


def blank_composer(agent: str, composer: str) -> bool:
    visible = input_lines(agent, composer)
    shown = BOX.sub("", visible).strip()
    return not shown or PLACEHOLDER.fullmatch(shown) is not None


def idle_and_empty(agent: str, pane: str) -> bool:
    return (pane_ready(agent, pane) and match_dialog(agent, pane) is None
            and blank_composer(agent, composer_text(agent, pane)))


def message_stuck(agent: str, pane: str, text: str) -> bool:
    if match_dialog(agent, pane) is not None:
        return False
    composer = composer_text(agent, pane)
    return squash(text)[-FINGERPRINT:] in squash(composer) or bool(PASTE_PLACEHOLDER.search(composer))


def should_retry(confirmed_idle_empty: bool, stuck: bool, retries: int, limit: int = RETRY_LIMIT) -> bool:
    return confirmed_idle_empty and stuck and retries < limit
