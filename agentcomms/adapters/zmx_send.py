from agentcomms.adapters.tmux import _TmuxAdapter, bracketed_paste
from agentcomms.model import HostKind


class ZmxSend(_TmuxAdapter):
    name = "zmx-send"
    host_kind: HostKind = "zmx"

    def payload(self, text: str) -> str:
        return text


class ZmxPaste(ZmxSend):
    name = "zmx-paste"

    def payload(self, text: str) -> str:
        return bracketed_paste(text)
