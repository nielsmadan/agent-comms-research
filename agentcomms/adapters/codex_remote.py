import subprocess
import time
from pathlib import Path

from agentcomms import backends, profiles
from agentcomms.adapters.bridge import AgentRoute
from agentcomms.adapters.native import UNKNOWN, NativeAdapter, now, receipt, run_socket, sender
from agentcomms.model import AgentName, Backend, LaunchMods, SendReceipt, Target
from agentcomms.paths import DEFERRED_LOG
from agentcomms.senders import codex_remote
from agentcomms.transcripts.codex import CodexTranscript

CROSS_MACHINE = ("codex --help: --remote <ADDR> \"Connect the TUI to a remote app server endpoint. Accepted forms: "
                 "ws://host:port, wss://host:port, unix://, or unix://PATH\"; app-server --listen ws://IP:PORT with "
                 "--ws-auth capability-token|signed-bearer-token (codex 0.164.0)")


SEND_TIMEOUT_S = 1.5
STEER_WAIT_S = 1.0


class ThreadError(RuntimeError):
    pass


def run_dir_of(target: Target) -> Path:
    return target.work_dir.parent.parent


def deferred_spool(target: Target, thread: str) -> Path:
    return run_dir_of(target) / "deferred" / thread


def codex_binary() -> str:
    return str(profiles.pinned_path("codex"))


def loaded_threads(sock: Path) -> list[str]:
    client = codex_remote.Client(str(sock), timeout_s=SEND_TIMEOUT_S)
    try:
        client.initialize()
        return client.call(lambda i: codex_remote.rpc_request(i, "thread/loaded/list", {})).get("data") or []
    finally:
        client.close()


def owned_thread(sock: Path, target: Target) -> str:
    threads = loaded_threads(sock)
    if len(threads) == 1:
        return threads[0]
    rollout = CodexTranscript.locate(target.home_dir, target.work_dir, target.session_id)
    sid = rollout.session_id() if rollout else None
    if sid and (not threads or sid in threads):
        return sid
    raise ThreadError(f"expected one harness thread on {sock}, found {len(threads)} loaded, rollout {sid}")


class CodexBackendAdapter(NativeAdapter):
    agents: frozenset[AgentName] = frozenset({"codex"})
    claims_cross_machine = CROSS_MACHINE

    def backend_socket(self, target: Target) -> Path:
        raise NotImplementedError

    def restart_backend(self, target: Target) -> str | None:
        _, detail = backends.restart(run_dir_of(target))
        return detail

    def argv_for(self, target: Target, thread: str) -> list[str]:
        raise NotImplementedError

    def agent_route(self, target: Target, sender_agent: AgentName) -> AgentRoute | None:
        try:
            thread = target.session_id or owned_thread(self.backend_socket(target), target)
        except (OSError, RuntimeError, TimeoutError, ValueError):
            return None
        return AgentRoute("address", f"thread {thread}", (thread,), command=self.argv_for(target, thread))


class CodexRemote(CodexBackendAdapter):
    backend: Backend = "codex-app-server"
    mode = "start"

    def socket_for(self, work_dir: Path) -> Path:
        return run_socket(work_dir)

    def backend_socket(self, target: Target) -> Path:
        return Path(target.backend_ref) if target.backend_ref else self.socket_for(target.work_dir)

    def launch_mods(self, agent: AgentName, work_dir: Path, home_dir: Path) -> LaunchMods:
        url = f"unix://{self.socket_for(work_dir)}"
        return LaunchMods(host="tmux", backend=self.backend, extra_args=("--remote", url),
                          backend_argv=(codex_binary(), "app-server", "--listen", url))

    def send(self, target: Target, text: str) -> SendReceipt:
        started = now()
        sock = self.backend_socket(target)
        try:
            thread = owned_thread(sock, target)
            spool = deferred_spool(target, thread)
            client = codex_remote.Client(str(sock), timeout_s=SEND_TIMEOUT_S)
            try:
                client.initialize()
                busy = client.busy_turn(thread)
                if self.mode == "start" and (busy or codex_remote.pending(spool)):
                    spawned = self.defer(target, thread, spool, text)
                    why = f"turn {busy} running" if busy else "earlier deferred messages pending"
                    return receipt(started, True, f"deferred: {why}; drainer delivers in order", spawned)
                detail = codex_remote.deliver(client, thread, text, self.mode, STEER_WAIT_S)
            finally:
                client.close()
        except codex_remote.WrittenTimeout as e:
            return receipt(started, True, f"{e}; {UNKNOWN}")
        except (OSError, RuntimeError, TimeoutError, ValueError) as e:
            return receipt(started, False, f"{type(e).__name__}: {e}")
        return receipt(started, True, detail)

    def defer(self, target: Target, thread: str, spool: Path, text: str) -> tuple[int, ...]:
        codex_remote.enqueue(spool, text, time.time_ns())
        if codex_remote.drainer_running(spool):
            return ()
        with open(run_dir_of(target) / DEFERRED_LOG, "ab") as log:
            proc = subprocess.Popen([*self.argv_for(target, thread), "--drain", str(spool)],
                                    stdin=subprocess.DEVNULL, stdout=log, stderr=log, cwd=target.work_dir,
                                    start_new_session=True)
        return (proc.pid,)

    def argv_for(self, target: Target, thread: str) -> list[str]:
        return sender("codex_remote.py", "--socket", str(self.backend_socket(target)), "--thread", thread,
                      "--mode", self.mode)

    def sender_argv(self, target: Target) -> list[str] | None:
        return self.argv_for(target, target.session_id) if target.session_id else None


class CodexRemoteStart(CodexRemote):
    name = "codex-remote-start"
    mode = "start"


class CodexRemoteSteer(CodexRemote):
    name = "codex-remote-steer"
    mode = "steer"
