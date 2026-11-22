from agentcomms.adapters.tmux import _TmuxAdapter, bracketed_paste
from agentcomms.model import HostKind


class Iterm2Text(_TmuxAdapter):
    name = "iterm2-text"
    host_kind: HostKind = "iterm2"

    def payload(self, text: str) -> str:
        return text


class Iterm2Paste(Iterm2Text):
    name = "iterm2-paste"

    def payload(self, text: str) -> str:
        return bracketed_paste(text)
