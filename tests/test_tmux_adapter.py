import shutil
import time
from pathlib import Path

import pytest

from agentcomms.adapters.tmux import TmuxKeys, TmuxPaste, bracketed_paste
from agentcomms.hosts.tmux import TmuxError, TmuxHost, env_wrapped, session_name, split_trailing_semicolons
from agentcomms.model import Target
from agentcomms.paths import SOCKET_DIR


class FakeHost:
    def __init__(self, fail: bool = False):
        self.calls: list[tuple[str, str]] = []
        self.fail = fail

    def send_literal(self, host_ref: str, text: str) -> None:
        if self.fail:
            raise TmuxError("no such session")
        self.calls.append(("literal", text))

    def send_key(self, host_ref: str, key: str) -> None:
        self.calls.append(("key", key))


TARGET = Target(run_id="r1", agent="codex", host="tmux", backend="none", work_dir=Path("/w"), home_dir=Path("/h"),
                session_id=None, host_ref="agentcomms:r1-codex", backend_ref=None, transcript=None, agent_pid=None)


def test_bracketed_paste_wraps_with_real_escape_bytes():
    assert bracketed_paste("hi\nthere") == "\x1b[200~hi\nthere\x1b[201~"


def test_bracketed_paste_strips_embedded_markers():
    assert bracketed_paste("a\x1b[201~b\x1b[200~c") == "\x1b[200~abc\x1b[201~"


def test_paste_adapter_sends_payload_then_exactly_one_enter():
    host = FakeHost()
    receipt = TmuxPaste(host).send(TARGET, "msg")
    assert host.calls == [("literal", "\x1b[200~msg\x1b[201~"), ("key", "Enter")]
    assert receipt.accepted and receipt.retries == 0


def test_keys_adapter_sends_literal_text_then_enter():
    host = FakeHost()
    TmuxKeys(host).send(TARGET, "msg")
    assert host.calls == [("literal", "msg"), ("key", "Enter")]


def test_send_failure_is_reported_as_not_accepted():
    receipt = TmuxPaste(FakeHost(fail=True)).send(TARGET, "msg")
    assert receipt.accepted is False
    assert receipt.detail == "no such session"


def test_host_ref_and_env_wrapping():
    assert session_name("agentcomms:r1-claude") == "r1-claude"
    assert env_wrapped(["claude"], {"B": "2", "A": "1"}) == ["/usr/bin/env", "-i", "A=1", "B=2", "claude"]


def test_trailing_semicolons_are_split_off():
    assert split_trailing_semicolons("a;b;;") == ("a;b", 2)
    assert split_trailing_semicolons("plain") == ("plain", 0)


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not installed")
def test_trailing_semicolon_survives_real_tmux(tmp_path):
    host = TmuxHost(tmp_path / "tmux.conf", socket=f"agentcomms-test{time.monotonic_ns() % 10**8}")
    ref = host.start("t", ["/bin/cat"], {"PATH": "/bin:/usr/bin"}, tmp_path)
    try:
        host.send_literal(ref, "hello world;")
        host.send_literal(ref, "second\\;")
        time.sleep(0.5)
        assert "hello world;second\\;" in host.capture(ref)
    finally:
        host.run("kill-server", check=False)
        (SOCKET_DIR / host.socket).unlink(missing_ok=True)


def test_unwrap_strips_claudes_paste_reference_wrapper():
    recorded = '\n\n<pasted_content id="c3a3">\nACK-REQUEST x: body\nline\twith tab\n</pasted_content id="c3a3">'
    assert TmuxPaste(FakeHost()).unwrap(recorded) == "ACK-REQUEST x: body\nline\twith tab"
    assert TmuxPaste(FakeHost()).unwrap("plain text") == "plain text"
