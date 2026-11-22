import json
import shutil
from pathlib import Path

from agentcomms.adapters.native import CHANNEL_SERVER, NativeAdapter, now, receipt, run_socket, sender, unwrap_channel
from agentcomms.model import AgentName, LaunchMods, SendReceipt, Target
from agentcomms.senders import unix_send

SERVER_NAME = "agentcomms"
CHANNEL_FLAG = "--dangerously-load-development-channels"


def bun() -> str:
    found = shutil.which("bun")
    return str(Path(found).resolve()) if found else "bun"


def channel_mcp_config(channel_socket: Path, log: Path, bun_path: str) -> dict:
    return {"mcpServers": {SERVER_NAME: {
        "command": bun_path, "args": ["run", str(CHANNEL_SERVER)],
        "env": {"AGENTCOMMS_CHANNEL_SOCKET": str(channel_socket), "AGENTCOMMS_CHANNEL_LOG": str(log)}}}}


class ClaudeChannel(NativeAdapter):
    name = "claude-channel"
    agents: frozenset[AgentName] = frozenset({"claude"})
    scenario_na = {"S12": "no separate server: the channel server is a stdio MCP child of Claude"}

    def channel_socket(self, work_dir: Path) -> Path:
        return run_socket(work_dir, "-ch")

    def run_sockets(self, work_dir: Path) -> list[Path]:
        return [self.channel_socket(work_dir)]

    def launch_mods(self, agent: AgentName, work_dir: Path, home_dir: Path) -> LaunchMods:
        config = home_dir / "channel-mcp.json"
        log = work_dir.parent.parent / "channel.log"
        content = json.dumps(channel_mcp_config(self.channel_socket(work_dir), log, bun()), indent=2)
        return LaunchMods(host="tmux", extra_args=("--mcp-config", str(config), CHANNEL_FLAG, f"server:{SERVER_NAME}"),
                          files={str(config): content})

    def send(self, target: Target, text: str) -> SendReceipt:
        started = now()
        try:
            reply = unix_send.send(str(self.channel_socket(target.work_dir)), text.encode())
        except OSError as e:
            return receipt(started, False, f"channel: {type(e).__name__}: {e}")
        return receipt(started, True, f"channel: {reply or 'sent'}")

    def unwrap(self, recorded: str) -> str:
        return unwrap_channel(recorded)

    def sender_argv(self, target: Target) -> list[str] | None:
        return sender("unix_send.py", "--socket", str(self.channel_socket(target.work_dir)))
