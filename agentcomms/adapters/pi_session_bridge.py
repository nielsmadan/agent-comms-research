import uuid
from pathlib import Path

from agentcomms.adapters.native import NativeAdapter, now, receipt, run_id_of, sender
from agentcomms.adapters.pi_ext import VENDOR, vendored
from agentcomms.model import AgentName, LaunchMods, SendReceipt, Target
from agentcomms.paths import SOCKET_DIR
from agentcomms.senders import pi_bridge

PACKAGE = VENDOR / "pi-session-bridge" / "node_modules" / "@vanillagreen" / "pi-session-bridge"
EXTENSION = PACKAGE / "extensions" / "session-bridge.ts"


def bridge_dir(work_dir: Path) -> Path:
    return SOCKET_DIR / f"{run_id_of(work_dir)}-pb"


def bridge_socket(work_dir: Path, pid: int) -> Path:
    return bridge_dir(work_dir) / f"pi-{pid}.sock"


class PiSessionBridge(NativeAdapter):
    name = "pi-session-bridge"
    agents: frozenset[AgentName] = frozenset({"pi"})
    command = "prompt"

    def launch_mods(self, agent: AgentName, work_dir: Path, home_dir: Path) -> LaunchMods:
        return LaunchMods(host="tmux", extra_args=("-e", str(vendored(EXTENSION))),
                          env={"PI_BRIDGE_DIR": str(bridge_dir(work_dir))})

    def ready_sockets(self, target: Target) -> list[Path]:
        return [bridge_socket(target.work_dir, target.agent_pid)] if target.agent_pid else []

    def send(self, target: Target, text: str) -> SendReceipt:
        started = now()
        if not target.agent_pid:
            return receipt(started, False, "pi-session-bridge: target has no agent pid")
        try:
            reply = pi_bridge.send(str(bridge_socket(target.work_dir, target.agent_pid)), self.command, text,
                                   f"agentcomms-{uuid.uuid4().hex[:8]}")
        except (OSError, TimeoutError, ValueError) as e:
            return receipt(started, False, f"pi-session-bridge: {type(e).__name__}: {e}")
        return receipt(started, bool(reply.get("success")), f"pi-session-bridge: {pi_bridge.summary(reply)}")

    def sender_argv(self, target: Target) -> list[str] | None:
        if not target.agent_pid:
            return None
        return sender("pi_bridge.py", "--socket", str(bridge_socket(target.work_dir, target.agent_pid)),
                      "--command", self.command)
