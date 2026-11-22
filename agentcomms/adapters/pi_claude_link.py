import re
import uuid
from pathlib import Path

from agentcomms.adapters.bridge import AgentRoute
from agentcomms.adapters.native import NativeAdapter, now, receipt, run_id_of, sender
from agentcomms.adapters.pi_ext import VENDOR, vendored
from agentcomms.model import AgentName, LaunchMods, SendReceipt, Target
from agentcomms.paths import SOCKET_DIR
from agentcomms.senders import claude_link, unix_send

PACKAGE = VENDOR / "pi-claude-link" / "node_modules" / "pi-claude-link"
EXTENSION = PACKAGE / "index.ts"
LINK_FRAME = re.compile(r"\A\[cross-agent message — from a Claude Code session, not your user\]\nFrom [^\n]*\n\n(.*)\Z",
                        re.S)


def unwrap_link_frame(recorded: str) -> str:
    m = LINK_FRAME.match(recorded)
    return m.group(1) if m else recorded


def runtime_dir(work_dir: Path) -> Path:
    return SOCKET_DIR / f"{run_id_of(work_dir)}-cl"


def peer_socket(work_dir: Path, pid: int) -> Path:
    return runtime_dir(work_dir) / "cc-socks" / f"{pid}.sock"


class PiClaudeLink(NativeAdapter):
    name = "pi-claude-link"
    agents: frozenset[AgentName] = frozenset({"pi"})

    def launch_mods(self, agent: AgentName, work_dir: Path, home_dir: Path) -> LaunchMods:
        return LaunchMods(host="tmux", extra_args=("-e", str(vendored(EXTENSION))),
                          env={"XDG_RUNTIME_DIR": str(runtime_dir(work_dir))})

    def ready_sockets(self, target: Target) -> list[Path]:
        return [peer_socket(target.work_dir, target.agent_pid)] if target.agent_pid else []

    def send(self, target: Target, text: str) -> SendReceipt:
        started = now()
        if not target.agent_pid:
            return receipt(started, False, "pi-claude-link: target has no agent pid")
        sock = peer_socket(target.work_dir, target.agent_pid)
        try:
            unix_send.send(str(sock), claude_link.peer_frame(text, str(uuid.uuid4())))
        except OSError as e:
            return receipt(started, False, f"pi-claude-link: {type(e).__name__}: {e}")
        return receipt(started, True, f"pi-claude-link: frame written to {sock.name}")

    def unwrap(self, recorded: str) -> str:
        return unwrap_link_frame(recorded)

    def sender_argv(self, target: Target) -> list[str] | None:
        if not target.agent_pid:
            return None
        return sender("claude_link.py", "--socket", str(peer_socket(target.work_dir, target.agent_pid)))

    def agent_route(self, target: Target, sender_agent: AgentName) -> AgentRoute | None:
        if sender_agent != "claude" or not target.agent_pid:
            return None
        sock = str(peer_socket(target.work_dir, target.agent_pid))
        return AgentRoute("address", f"uds:{sock}", (sock, str(target.agent_pid)), tool="SendMessage")
