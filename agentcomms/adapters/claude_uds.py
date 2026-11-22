import json
import uuid
from pathlib import Path

from agentcomms.adapters.bridge import AgentRoute
from agentcomms.adapters.native import (
    SENDERS,
    NativeAdapter,
    now,
    python3,
    receipt,
    run_socket,
    sender,
    unwrap_cross_session,
)
from agentcomms.model import AgentName, LaunchMods, SendReceipt, Target
from agentcomms.senders import claude_uds, unix_send
from agentcomms.transcripts.claude import registry_entry

CROSS_MACHINE = ('settings schema: isolatePeerMachines "Require explicit approval before SendMessage can reach a peer '
                 'session on another machine via Remote Control" (claude 2.1.310 binary)')
PeerAddressError = claude_uds.guard.GuardError


def peer_address(config_dir: Path, pid: int) -> tuple[str, str]:
    return claude_uds.peer_address(str(config_dir), pid)


def relay_mcp_config(relay_socket: Path, log: Path, interpreter: str) -> dict:
    return {"mcpServers": {"agentcomms-relay": {
        "command": interpreter, "args": ["-I", str(SENDERS / "claude_child_relay.py")],
        "env": {"AGENTCOMMS_RELAY_SOCKET": str(relay_socket), "AGENTCOMMS_RELAY_LOG": str(log)}}}}


class ClaudeUds(NativeAdapter):
    name = "claude-uds"
    agents: frozenset[AgentName] = frozenset({"claude"})
    claims_cross_machine = CROSS_MACHINE
    settings: dict = {}

    def launch_mods(self, agent: AgentName, work_dir: Path, home_dir: Path) -> LaunchMods:
        extra = ("--settings", json.dumps(self.settings)) if self.settings else ()
        return LaunchMods(host="tmux", extra_args=extra)

    def send(self, target: Target, text: str) -> SendReceipt:
        started = now()
        try:
            if not target.agent_pid:
                raise PeerAddressError("target has no agent pid")
            claude_uds.guard.owned_claude_target(target.home_dir, target.agent_pid, target.work_dir.parents[2])
            sock, token = peer_address(target.home_dir, target.agent_pid)
            claude_uds.send(sock, claude_uds.wire(token, text, str(uuid.uuid4())))
        except (OSError, PeerAddressError, ValueError, KeyError) as e:
            return receipt(started, False, f"{type(e).__name__}: {e}")
        return receipt(started, True, "auth=yes")

    def unwrap(self, recorded: str) -> str:
        return unwrap_cross_session(recorded)

    def sender_argv(self, target: Target) -> list[str] | None:
        if not target.agent_pid:
            return None
        return sender("claude_uds.py", "--config-dir", str(target.home_dir), "--pid", str(target.agent_pid))

    def agent_route(self, target: Target, sender_agent: AgentName) -> AgentRoute | None:
        if sender_agent != "claude" or not target.agent_pid:
            return None
        sock = (registry_entry(target.home_dir, target.agent_pid) or {}).get("messagingSocketPath")
        return send_message_route(sock, target) if sock else None


def send_message_route(sock: str, target: Target) -> AgentRoute:
    return AgentRoute("address", f"uds:{sock}", (sock, str(target.agent_pid), target.session_id or ""),
                      tool="SendMessage")


class ClaudeUdsAccept(ClaudeUds):
    name = "claude-uds-accept"
    settings = {"crossSessionInbound": "accept"}


class ClaudeUdsChild(ClaudeUds):
    name = "claude-uds-child"
    scenario_na = {"S12": "no separate server: the relay is a stdio MCP child of Claude"}

    def relay_socket(self, work_dir: Path) -> Path:
        return run_socket(work_dir, "-relay")

    def run_sockets(self, work_dir: Path) -> list[Path]:
        return [self.relay_socket(work_dir)]

    def launch_mods(self, agent: AgentName, work_dir: Path, home_dir: Path) -> LaunchMods:
        config = home_dir / "relay-mcp.json"
        log = work_dir.parent.parent / "relay.log"
        content = json.dumps(relay_mcp_config(self.relay_socket(work_dir), log, python3()), indent=2)
        return LaunchMods(host="tmux", extra_args=("--mcp-config", str(config)), files={str(config): content})

    def send(self, target: Target, text: str) -> SendReceipt:
        started = now()
        try:
            reply = unix_send.send(str(self.relay_socket(target.work_dir)), text.encode())
        except OSError as e:
            return receipt(started, False, f"relay: {type(e).__name__}: {e}")
        return receipt(started, reply.startswith("forwarded"), f"relay: {reply}")

    def sender_argv(self, target: Target) -> list[str] | None:
        return sender("unix_send.py", "--socket", str(self.relay_socket(target.work_dir)))

    def agent_route(self, target: Target, sender_agent: AgentName) -> AgentRoute | None:
        return None
