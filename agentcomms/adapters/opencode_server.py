import json
import secrets
import socket
import time
from pathlib import Path

from agentcomms import backends, profiles
from agentcomms.adapters.native import UNKNOWN, NativeAdapter, now, receipt, sender
from agentcomms.model import AgentName, Backend, LaunchMods, SendReceipt, Target
from agentcomms.senders import opencode_http

PASSWORD_FILE = "server-password"


STARTING_WAIT_S = 30.0
STARTING_POLL_S = 0.5


class OpenCodeSessionError(RuntimeError):
    pass


def still_starting(status: int, reply: dict) -> bool:
    return status == 503 and reply.get("code") == "service_starting"


def bound_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((backends.LOOPBACK, 0))
        return s.getsockname()[1]


def free_port(draw=bound_port, reserved: frozenset[int] = frozenset({backends.OPENCODE_DEFAULT_SERVICE_PORT})) -> int:
    return next(port for port in iter(draw, None) if port not in reserved)


def opencode_binary() -> str:
    return str(profiles.pinned_path("opencode"))


def password_file(home_dir: Path) -> Path:
    return home_dir / PASSWORD_FILE


def service_config(port: int, password: str) -> dict:
    return {"hostname": backends.LOOPBACK, "port": port, "password": password}


def run_dir_of(target: Target) -> Path:
    return target.work_dir.parent.parent


class OpenCodeServer(NativeAdapter):
    name = "opencode-server-steer"
    agents: frozenset[AgentName] = frozenset({"opencode"})
    backend: Backend = "opencode-server"
    route = "prompt"
    delivery = "steer"

    def launch_mods(self, agent: AgentName, work_dir: Path, home_dir: Path) -> LaunchMods:
        port, password = free_port(), secrets.token_urlsafe(24)
        url = f"http://{backends.LOOPBACK}:{port}"
        return LaunchMods(host="tmux", backend=self.backend, extra_args=("--server", url),
                          env={"OPENCODE_PASSWORD": password}, files={str(password_file(home_dir)): password},
                          backend_argv=tuple(profiles.launch_argv([opencode_binary(), "serve", "--hostname",
                                                                   backends.LOOPBACK, "--port", str(port)])))

    def prepare_backend(self, endpoint: str, session_id: str, work_dir: Path, home_dir: Path,
                        starting_wait_s: float = STARTING_WAIT_S) -> str:
        body = opencode_http.create_session_body(session_id, str(work_dir), profiles.MODELS["opencode"][0])
        password = password_file(home_dir).read_text().strip()
        deadline = time.monotonic() + starting_wait_s
        while True:
            try:
                status, reply = opencode_http.request(endpoint, "/api/session", body, password, timeout_s=10.0)
            except opencode_http.TRANSPORT_ERRORS as e:
                raise OpenCodeSessionError(f"creating {session_id} on {endpoint}: {type(e).__name__}: {e}") from e
            if not (still_starting(status, reply) and time.monotonic() < deadline):
                break
            time.sleep(STARTING_POLL_S)
        if not 200 <= status < 300:
            raise OpenCodeSessionError(f"creating {session_id} on {endpoint}: http {status} {json.dumps(reply)[:200]}")
        return session_id

    def send(self, target: Target, text: str) -> SendReceipt:
        started = now()
        if not target.backend_ref or not target.session_id:
            return receipt(started, False, "opencode: target has no server url or session id")
        try:
            status, reply = opencode_http.post(target.backend_ref, self.route, target.session_id, text, self.delivery,
                                               password_file(target.home_dir).read_text().strip())
        except TimeoutError as e:
            return receipt(started, True, f"opencode: request written, no reply: {e}; {UNKNOWN}")
        except opencode_http.TRANSPORT_ERRORS as e:
            return receipt(started, False, f"opencode: {type(e).__name__}: {e}")
        return receipt(started, 200 <= status < 300, f"opencode {self.route}: {opencode_http.outcome(status, reply)}")

    def restart_backend(self, target: Target) -> str | None:
        _, detail = backends.restart(run_dir_of(target))
        return detail

    def sender_argv(self, target: Target) -> list[str] | None:
        if not target.backend_ref or not target.session_id:
            return None
        return sender("opencode_http.py", "--url", target.backend_ref, "--session", target.session_id,
                      "--password-file", str(password_file(target.home_dir)), "--route", self.route,
                      "--delivery", self.delivery)


class OpenCodeServerQueue(OpenCodeServer):
    name = "opencode-server-queue"
    delivery = "queue"


class OpenCodeServerSynthetic(OpenCodeServer):
    name = "opencode-server-synthetic"
    route = "synthetic"


class OpenCodeService(OpenCodeServer):
    name = "opencode-service-steer"
    backend: Backend = "opencode-service"

    def launch_mods(self, agent: AgentName, work_dir: Path, home_dir: Path) -> LaunchMods:
        port, password = free_port(), secrets.token_urlsafe(24)
        config = home_dir / "config" / "opencode" / "service.json"
        return LaunchMods(host="tmux", backend=self.backend,
                          files={str(password_file(home_dir)): password,
                                 str(config): json.dumps(service_config(port, password), indent=2)},
                          backend_argv=tuple(profiles.launch_argv([opencode_binary(), "service", "start"])))
