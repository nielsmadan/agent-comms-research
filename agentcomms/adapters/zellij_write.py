import time

from agentcomms.adapters.tmux import _TmuxAdapter
from agentcomms.hosts.errors import HostError
from agentcomms.model import HostKind, SendReceipt, Target


class ZellijWrite(_TmuxAdapter):
    name = "zellij-write"
    host_kind: HostKind = "zellij"

    def payload(self, text: str) -> str:
        return text


class ZellijPaste(ZellijWrite):
    name = "zellij-paste"

    def send(self, target: Target, text: str) -> SendReceipt:
        sent_at, sent_mono = time.time(), time.monotonic()
        try:
            self.host.send_paste(target.host_ref, text)
            self.host.send_key(target.host_ref, "Enter")
        except HostError as e:
            return SendReceipt(False, sent_at, sent_mono, detail=str(e))
        return SendReceipt(True, sent_at, sent_mono)
