import re
import sys
import time
from pathlib import Path
from typing import Literal

from agentcomms.adapters import retry
from agentcomms.hosts.errors import HostError
from agentcomms.hosts.tmux import TmuxHost
from agentcomms.model import AgentName, Backend, HostKind, LaunchMods, SendReceipt, Target

PASTE_START = "\x1b[200~"
PASTE_END = "\x1b[201~"
ALL_AGENTS: frozenset[AgentName] = frozenset({"claude", "codex", "pi", "opencode", "droid"})
PASTE_REFERENCE = re.compile(r'\A\s*<pasted_content id="[^"]*">\n(.*)\n</pasted_content id="[^"]*">\s*\Z', re.S)


def unwrap_paste_reference(recorded: str) -> str:
    m = PASTE_REFERENCE.match(recorded)
    return m.group(1) if m else recorded


def strip_paste_markers(text: str) -> str:
    return text.replace(PASTE_START, "").replace(PASTE_END, "")


def bracketed_paste(text: str) -> str:
    return f"{PASTE_START}{strip_paste_markers(text)}{PASTE_END}"


def cli_sender_argv(target: Target, adapter: str) -> list[str]:
    return [sys.executable, "-m", "agentcomms.cli", "send", "--run", target.run_id,
            "--host-ref", target.host_ref, "--adapter", adapter]


class _TmuxAdapter:
    agents: frozenset[AgentName] = ALL_AGENTS
    kind: Literal["native", "terminal", "bridge"] = "terminal"
    claims_cross_machine: str | None = None
    name: str = ""
    host_kind: HostKind = "tmux"

    def __init__(self, host: TmuxHost):
        self.host = host

    @classmethod
    def backend_for(cls, agent: AgentName) -> Backend:
        return "none"

    def launch_mods(self, agent: AgentName, work_dir: Path, home_dir: Path) -> LaunchMods:
        return LaunchMods(host=self.host_kind, backend=self.backend_for(agent))

    def payload(self, text: str) -> str:
        raise NotImplementedError

    def send(self, target: Target, text: str) -> SendReceipt:
        sent_at, sent_mono = time.time(), time.monotonic()
        try:
            self.host.send_literal(target.host_ref, self.payload(text))
            self.host.send_key(target.host_ref, "Enter")
        except HostError as e:
            return SendReceipt(False, sent_at, sent_mono, detail=str(e))
        return SendReceipt(True, sent_at, sent_mono)

    def unwrap(self, recorded: str) -> str:
        return unwrap_paste_reference(recorded)

    def sender_argv(self, target: Target) -> list[str] | None:
        return cli_sender_argv(target, self.name)

    def restart_backend(self, target: Target) -> str | None:
        return None

    def run_sockets(self, work_dir: Path) -> list[Path]:
        return []


class TmuxKeys(_TmuxAdapter):
    name = "tmux-keys"

    def payload(self, text: str) -> str:
        return text


class TmuxPaste(_TmuxAdapter):
    name = "tmux-paste"

    def payload(self, text: str) -> str:
        return bracketed_paste(text)


class TmuxPasteRetry(TmuxPaste):
    name = "tmux-paste-retry"

    def send(self, target: Target, text: str) -> SendReceipt:
        try:
            confirmed = retry.idle_and_empty(target.agent, self.host.capture(target.host_ref))
        except HostError as e:
            return SendReceipt(False, time.time(), time.monotonic(), detail=str(e))
        receipt = super().send(target, text)
        if not receipt.accepted:
            return receipt
        retries, waited = 0, 0.0
        try:
            while confirmed and retries < retry.RETRY_LIMIT:
                time.sleep(retry.RETRY_WAIT_S)
                waited += retry.RETRY_WAIT_S
                stuck = retry.message_stuck(target.agent, self.host.capture(target.host_ref), text)
                if not retry.should_retry(confirmed, stuck, retries):
                    break
                self.host.send_key(target.host_ref, "Enter")
                retries += 1
        except HostError as e:
            return SendReceipt(True, receipt.sent_at, receipt.sent_mono, retries, f"retry-aborted: {e}",
                               waited_s=waited)
        detail = "" if confirmed else "retry-disabled: receiver not confirmed idle with an empty input box"
        return SendReceipt(True, receipt.sent_at, receipt.sent_mono, retries, detail, waited_s=waited)


def buffer_name(now_ns: int) -> str:
    return f"ac-{now_ns}"


class TmuxBuffer(_TmuxAdapter):
    name = "tmux-buffer"

    def send(self, target: Target, text: str) -> SendReceipt:
        sent_at, sent_mono = time.time(), time.monotonic()
        buffer = buffer_name(time.monotonic_ns())
        try:
            self.host.load_buffer(buffer, text, target.host_ref)
            self.host.paste_buffer(target.host_ref, buffer)
            self.host.send_key(target.host_ref, "Enter")
        except HostError as e:
            return SendReceipt(False, sent_at, sent_mono, detail=str(e))
        return SendReceipt(True, sent_at, sent_mono)
