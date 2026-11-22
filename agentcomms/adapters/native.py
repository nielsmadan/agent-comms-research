import re
import shutil
import time
from pathlib import Path
from typing import Literal

from agentcomms.model import AgentName, Backend, SendReceipt, Target
from agentcomms.paths import REPO_ROOT, SOCKET_DIR

SENDERS = REPO_ROOT / "agentcomms" / "senders"
CHANNEL_SERVER = REPO_ROOT / "agentcomms" / "channel" / "server.ts"
CROSS_SESSION = re.compile(r"\A\s*<cross-session-message\b[^>]*>\n?(.*?)\n?</cross-session-message>\s*\Z", re.S)
PEER_FRAME = re.compile(r"\A\s*Another Claude session[^\n]*sent a message:\n(.*?)\n\nThis came from another Claude "
                        r"session\b.*\Z", re.S)
CHANNEL = re.compile(r'\A\s*<channel source="[^"]*"[^>]*>\n?(.*?)\n?</channel>\s*\Z', re.S)


def unwrap_cross_session(recorded: str) -> str:
    framed = PEER_FRAME.match(recorded)
    body = framed.group(1) if framed else recorded
    m = CROSS_SESSION.match(body)
    return m.group(1).replace("<\\/cross-session-message", "</cross-session-message") if m else body


def unwrap_channel(recorded: str) -> str:
    m = CHANNEL.match(recorded)
    return m.group(1) if m else recorded


def run_id_of(work_dir: Path) -> str:
    return work_dir.parent.parent.name


def run_socket(work_dir: Path, suffix: str = "") -> Path:
    return SOCKET_DIR / f"{run_id_of(work_dir)}{suffix}.sock"


def sender(script: str, *args: str) -> list[str]:
    return ["python3", "-I", str(SENDERS / script), *args]


def python3() -> str:
    found = shutil.which("python3")
    return str(Path(found).resolve()) if found else "/usr/bin/python3"


def now() -> tuple[float, float]:
    return time.time(), time.monotonic()


UNKNOWN = "verdict from the transcript"


def receipt(started: tuple[float, float], accepted: bool, detail: str = "",
            spawned: tuple[int, ...] = ()) -> SendReceipt:
    return SendReceipt(accepted, started[0], started[1], detail=detail, spawned=spawned)


class NativeAdapter:
    name: str = ""
    agents: frozenset[AgentName] = frozenset()
    kind: Literal["native", "terminal", "bridge"] = "native"
    claims_cross_machine: str | None = None
    backend: Backend = "none"
    scenario_na: dict[str, str] = {}

    def __init__(self, host=None):
        self.host = host

    def scenario_not_applicable(self, agent: AgentName, scenario: str) -> str | None:
        return self.scenario_na.get(scenario)

    @classmethod
    def backend_for(cls, agent: AgentName) -> Backend:
        return cls.backend

    def unwrap(self, recorded: str) -> str:
        return recorded

    def restart_backend(self, target: Target) -> str | None:
        return None

    def run_sockets(self, work_dir: Path) -> list[Path]:
        return []
