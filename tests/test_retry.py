from pathlib import Path

import pytest

from agentcomms.adapters import retry
from agentcomms.adapters.tmux import TmuxBuffer, TmuxPasteRetry
from agentcomms.hosts.tmux import TmuxError, TmuxHost
from agentcomms.model import Target
from agentcomms.scenarios.common import composer_text

TEXT = 'ACK-REQUEST ab12cd34: reply with exactly "ACK ab12cd34". hello there'
RULE = "─" * 100
CLAUDE_EMPTY = f"{RULE}\n❯ \n{RULE}\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
CLAUDE_STUCK = f"{RULE}\n❯ {TEXT}\n{RULE}\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
CLAUDE_DRAFT = f"{RULE}\n❯ half a thought\n{RULE}\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
CLAUDE_PASTED = f"{RULE}\n❯ [Pasted text #1 +3 lines]\n{RULE}\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
CLAUDE_DIALOG = (f"{RULE}\n❯ {TEXT}\n{RULE}\n  Do you trust the files in this folder?\n"
                 "  ❯ 1. Yes, proceed\n    2. No, exit\n")
CODEX_DRAFT = ("\n› half a thought\n\n  GPT-6-Luna low · ~/x · Wait for command completion\n"
               "  ? for shortcuts\n")
CODEX_EMPTY = ("\n› Ask Codex to do anything\n\n  GPT-6-Luna low · ~/x · Wait for command completion\n"
               "  ? for shortcuts\n")
FIXTURES = Path(__file__).parent / "fixtures" / "opencode"
TARGET = Target("r1", "claude", "tmux", "none", Path("/w"), Path("/h"), None, "agentcomms:r1-claude", None, None, 1)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(retry, "RETRY_WAIT_S", 0.0)
    monkeypatch.setattr("agentcomms.adapters.tmux.time.sleep", lambda _s: None)


def test_idle_and_empty_accepts_empty_claude_and_placeholder_codex():
    assert retry.idle_and_empty("claude", CLAUDE_EMPTY)
    assert retry.idle_and_empty("codex", CODEX_EMPTY)


def test_a_human_draft_is_not_an_empty_box():
    assert not retry.idle_and_empty("claude", CLAUDE_DRAFT)


def test_an_opencode_draft_below_the_padding_row_is_not_an_empty_box():
    pane = (FIXTURES / "pane-draft-home.txt").read_text()
    assert not retry.blank_composer("opencode", composer_text("opencode", pane))
    assert not retry.idle_and_empty("opencode", pane)


def test_an_idle_opencode_session_box_is_empty():
    pane = (FIXTURES / "pane-session-idle.txt").read_text()
    assert retry.blank_composer("opencode", composer_text("opencode", pane))
    assert retry.idle_and_empty("opencode", pane)


def test_stuck_message_is_found_by_text_or_paste_placeholder():
    assert retry.message_stuck("claude", CLAUDE_STUCK, TEXT)
    assert retry.message_stuck("claude", CLAUDE_PASTED, TEXT)
    assert not retry.message_stuck("claude", CLAUDE_EMPTY, TEXT)


def test_a_dialog_is_never_an_empty_box_and_never_a_stuck_message():
    assert not retry.idle_and_empty("claude", CLAUDE_DIALOG)
    assert not retry.message_stuck("claude", CLAUDE_DIALOG, TEXT)


def test_a_codex_draft_is_not_an_empty_box_but_the_placeholder_is():
    assert not retry.idle_and_empty("codex", CODEX_DRAFT)
    assert retry.idle_and_empty("codex", CODEX_EMPTY)


def test_a_draft_that_merely_starts_with_a_placeholder_phrase_is_a_draft():
    assert not retry.blank_composer("opencode", "Ask anything now")
    assert retry.blank_composer("opencode", "Ask anything")


def test_should_retry_needs_confirmed_idle_stuck_and_budget():
    assert retry.should_retry(True, True, 0)
    assert not retry.should_retry(False, True, 0)
    assert not retry.should_retry(True, False, 0)
    assert not retry.should_retry(True, True, retry.RETRY_LIMIT)


class FakeHost:
    def __init__(self, panes: list[str], fail_capture: bool = False):
        self.panes = list(panes)
        self.calls: list[tuple[str, ...]] = []
        self.fail_capture = fail_capture

    def capture(self, host_ref: str) -> str:
        if self.fail_capture:
            raise TmuxError("gone")
        return self.panes.pop(0) if len(self.panes) > 1 else self.panes[0]

    def send_literal(self, host_ref: str, text: str) -> None:
        self.calls.append(("literal", text))

    def send_key(self, host_ref: str, key: str) -> None:
        self.calls.append(("key", key))

    def load_buffer(self, buffer: str, text: str, host_ref: str | None = None) -> None:
        self.calls.append(("load", buffer, text))

    def paste_buffer(self, host_ref: str, buffer: str) -> None:
        self.calls.append(("paste", buffer, host_ref))


def enters(host: FakeHost) -> int:
    return sum(1 for c in host.calls if c == ("key", "Enter"))


def test_retry_adapter_presses_enter_again_while_the_message_sits_in_the_box():
    host = FakeHost([CLAUDE_EMPTY, CLAUDE_STUCK, CLAUDE_STUCK, CLAUDE_EMPTY])
    receipt = TmuxPasteRetry(host).send(TARGET, TEXT)
    assert (receipt.accepted, receipt.retries) == (True, 2)
    assert enters(host) == 3


def test_retry_adapter_does_not_retry_after_a_clean_submit():
    host = FakeHost([CLAUDE_EMPTY, CLAUDE_EMPTY])
    receipt = TmuxPasteRetry(host).send(TARGET, TEXT)
    assert (receipt.retries, enters(host)) == (0, 1)


def test_retry_adapter_reports_its_fixed_wait_so_send_s_can_exclude_it(monkeypatch):
    monkeypatch.setattr(retry, "RETRY_WAIT_S", 1.5)
    receipt = TmuxPasteRetry(FakeHost([CLAUDE_EMPTY, CLAUDE_STUCK, CLAUDE_EMPTY])).send(TARGET, TEXT)
    assert (receipt.retries, receipt.waited_s) == (1, 3.0)


def test_retry_adapter_never_retries_over_a_human_draft():
    host = FakeHost([CLAUDE_DRAFT, CLAUDE_STUCK])
    receipt = TmuxPasteRetry(host).send(TARGET, TEXT)
    assert (receipt.accepted, receipt.retries, enters(host)) == (True, 0, 1)
    assert receipt.detail.startswith("retry-disabled")


def test_retry_adapter_does_not_press_enter_when_a_dialog_opens_after_the_send():
    host = FakeHost([CLAUDE_EMPTY, CLAUDE_DIALOG])
    receipt = TmuxPasteRetry(host).send(TARGET, TEXT)
    assert (receipt.accepted, receipt.retries, enters(host)) == (True, 0, 1)


def test_retry_adapter_leaves_a_draft_typed_after_the_send_alone():
    host = FakeHost([CLAUDE_EMPTY, CLAUDE_DRAFT])
    receipt = TmuxPasteRetry(host).send(TARGET, TEXT)
    assert (receipt.retries, enters(host)) == (0, 1)


def test_retry_adapter_stops_at_the_limit():
    host = FakeHost([CLAUDE_EMPTY, CLAUDE_STUCK])
    receipt = TmuxPasteRetry(host).send(TARGET, TEXT)
    assert receipt.retries == retry.RETRY_LIMIT
    assert enters(host) == retry.RETRY_LIMIT + 1


def test_retry_adapter_reports_a_dead_session_as_not_accepted():
    receipt = TmuxPasteRetry(FakeHost([CLAUDE_EMPTY], fail_capture=True)).send(TARGET, TEXT)
    assert receipt.accepted is False
    assert receipt.detail == "gone"


def test_buffer_adapter_loads_pastes_bracketed_then_one_enter():
    host = FakeHost([CLAUDE_EMPTY])
    receipt = TmuxBuffer(host).send(TARGET, "multi\nline")
    name = host.calls[0][1]
    assert name.startswith("ac-")
    assert host.calls == [("load", name, "multi\nline"), ("paste", name, TARGET.host_ref), ("key", "Enter")]
    assert receipt.accepted and receipt.retries == 0


def test_tmux_host_loads_from_stdin_and_pastes_bracketed_then_deletes_the_buffer(monkeypatch):
    host = TmuxHost(Path("/x/tmux.conf"))
    seen = []

    def run(*args, check=True, input_text=None, socket=None):
        seen.append((args, input_text, socket))
        return ""
    monkeypatch.setattr(host, "run", run)
    host.load_buffer("ac-1", "multi\nline", "agentcomms-gc-1:r1-claude")
    host.paste_buffer("agentcomms-gc-1:r1-claude", "ac-1")
    assert seen == [(("load-buffer", "-b", "ac-1", "-"), "multi\nline", "agentcomms-gc-1"),
                    (("paste-buffer", "-p", "-d", "-b", "ac-1", "-t", "=r1-claude:"), None, "agentcomms-gc-1")]
