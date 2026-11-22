from collections.abc import Callable
from typing import Any

from agentcomms.adapters.agent_deck import AgentDeck, AgentDeckComposerFallback
from agentcomms.adapters.claude_channel import ClaudeChannel
from agentcomms.adapters.claude_uds import ClaudeUds, ClaudeUdsAccept, ClaudeUdsChild
from agentcomms.adapters.codex_queue import CodexQueue, CodexQueueEmbedded
from agentcomms.adapters.codex_remote import CodexRemoteStart, CodexRemoteSteer
from agentcomms.adapters.csd import Csd
from agentcomms.adapters.gc_nudge import GcNudge
from agentcomms.adapters.hcom import Hcom
from agentcomms.adapters.intercom import Intercom, IntercomAccept
from agentcomms.adapters.iterm2_text import Iterm2Paste, Iterm2Text
from agentcomms.adapters.opencode_server import (
    OpenCodeServer,
    OpenCodeServerQueue,
    OpenCodeServerSynthetic,
    OpenCodeService,
)
from agentcomms.adapters.pi_claude_link import PiClaudeLink
from agentcomms.adapters.pi_ext import PiExt
from agentcomms.adapters.pi_session_bridge import PiSessionBridge
from agentcomms.adapters.tmux import TmuxBuffer, TmuxKeys, TmuxPaste, TmuxPasteRetry
from agentcomms.adapters.zellij_write import ZellijPaste, ZellijWrite
from agentcomms.adapters.zmx_send import ZmxPaste, ZmxSend
from agentcomms.model import Adapter, AgentName, Backend, HostKind

ADAPTERS = {cls.name: cls for cls in (TmuxKeys, TmuxPaste, TmuxPasteRetry, TmuxBuffer, ZmxSend, ZmxPaste,
                                      ZellijWrite, ZellijPaste, Iterm2Text, Iterm2Paste,
                                      ClaudeUds, ClaudeUdsAccept, ClaudeUdsChild, ClaudeChannel,
                                      CodexQueue, CodexQueueEmbedded, CodexRemoteStart, CodexRemoteSteer,
                                      OpenCodeServer, OpenCodeServerQueue, OpenCodeServerSynthetic, OpenCodeService,
                                      PiExt, PiSessionBridge, PiClaudeLink, Hcom, Intercom,
                                      IntercomAccept, Csd, AgentDeck,
                                      AgentDeckComposerFallback, GcNudge)}
ADAPTER_NAMES = tuple(ADAPTERS)


def make_adapter(name: str, host_for: Callable[[HostKind], Any]) -> Adapter:
    if name in ADAPTERS:
        cls = ADAPTERS[name]
        return cls(host_for(getattr(cls, "host_kind", "tmux")))
    raise KeyError(f"unknown adapter {name!r}; known: {', '.join(sorted(ADAPTERS))}")


def adapter_host(name: str) -> HostKind:
    return getattr(ADAPTERS[name], "host_kind", "tmux")


def adapter_backend(name: str, agent: AgentName) -> Backend:
    return ADAPTERS[name].backend_for(agent)


def adapter_agents(name: str) -> frozenset[AgentName]:
    return ADAPTERS[name].agents


def shared_state_of(cls) -> str | None:
    declared = getattr(cls, "shared_state", None)
    return declared or (cls.name if getattr(cls, "kind", None) == "bridge" else None)


def adapter_shared_state(name: str) -> str | None:
    return shared_state_of(ADAPTERS[name])
