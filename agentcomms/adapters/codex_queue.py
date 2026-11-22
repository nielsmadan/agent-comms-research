import subprocess
from pathlib import Path

from agentcomms import backends
from agentcomms.adapters.codex_remote import CodexBackendAdapter, codex_binary, owned_thread
from agentcomms.adapters.native import now, receipt, sender
from agentcomms.model import AgentName, Backend, LaunchMods, SendReceipt, Target


class CodexQueue(CodexBackendAdapter):
    name = "codex-queue"
    backend: Backend = "codex-daemon"

    def backend_socket(self, target: Target) -> Path:
        return backends.codex_daemon_socket(target.home_dir)

    def launch_mods(self, agent: AgentName, work_dir: Path, home_dir: Path) -> LaunchMods:
        return LaunchMods(host="tmux", backend=self.backend,
                          backend_argv=(codex_binary(), "app-server", "daemon", "start"))

    def send(self, target: Target, text: str) -> SendReceipt:
        started = now()
        try:
            thread = owned_thread(self.backend_socket(target), target)
            out = subprocess.run(self.argv_for(target, thread), input=text, capture_output=True, text=True,
                                 timeout=30)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as e:
            return receipt(started, False, f"{type(e).__name__}: {e}")
        detail = (out.stdout.strip() or out.stderr.strip())[:200]
        return receipt(started, out.returncode == 0, detail)

    def argv_for(self, target: Target, thread: str) -> list[str]:
        return sender("codex_queue.py", "--codex", codex_binary(), "--codex-home", str(target.home_dir),
                      "--thread", thread)

    def sender_argv(self, target: Target) -> list[str] | None:
        return self.argv_for(target, target.session_id) if target.session_id else None


class CodexQueueEmbedded(CodexQueue):
    name = "codex-queue-embedded"

    def launch_mods(self, agent: AgentName, work_dir: Path, home_dir: Path) -> LaunchMods:
        mods = super().launch_mods(agent, work_dir, home_dir)
        return LaunchMods(host=mods.host, backend=mods.backend, backend_argv=mods.backend_argv,
                          extra_args=("-c", "check_for_update_on_startup=false"))
