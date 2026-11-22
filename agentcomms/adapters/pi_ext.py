from pathlib import Path

from agentcomms.adapters.native import UNKNOWN, NativeAdapter, now, receipt, run_socket, sender
from agentcomms.model import AgentName, LaunchMods, SendReceipt, Target
from agentcomms.paths import REPO_ROOT
from agentcomms.senders import unix_send

EXTENSION = REPO_ROOT / "agentcomms" / "pi_ext" / "agentcomms-inbox.ts"
VENDOR = REPO_ROOT / "vendor"


def vendored(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"{path} missing; install it as vendor/REVIEW.md describes")
    return path


class PiExt(NativeAdapter):
    name = "pi-ext"
    agents: frozenset[AgentName] = frozenset({"pi"})

    def inbox_socket(self, work_dir: Path) -> Path:
        return run_socket(work_dir, "-pi")

    def run_sockets(self, work_dir: Path) -> list[Path]:
        return [self.inbox_socket(work_dir)]

    def launch_mods(self, agent: AgentName, work_dir: Path, home_dir: Path) -> LaunchMods:
        return LaunchMods(host="tmux", extra_args=("-e", str(EXTENSION)),
                          env={"AGENTCOMMS_PI_SOCKET": str(self.inbox_socket(work_dir))})

    def send(self, target: Target, text: str) -> SendReceipt:
        started = now()
        try:
            reply = unix_send.send(str(self.inbox_socket(target.work_dir)), text.encode())
        except OSError as e:
            return receipt(started, False, f"pi-ext: {type(e).__name__}: {e}")
        if not reply:
            return receipt(started, True, f"pi-ext: written, no reply within {unix_send.REPLY_TIMEOUT_S}s; {UNKNOWN}")
        return receipt(started, reply.startswith("queued"), f"pi-ext: {reply}")

    def sender_argv(self, target: Target) -> list[str] | None:
        return sender("unix_send.py", "--socket", str(self.inbox_socket(target.work_dir)))
