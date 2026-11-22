from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol

AgentName = Literal["claude", "codex", "pi", "opencode", "droid"]
HostKind = Literal["tmux", "iterm2", "zmx", "zellij"]
Backend = Literal["none", "codex-daemon", "codex-app-server", "opencode-server", "opencode-service"]

class Delivery(StrEnum):
    DELIVERED = "delivered"        # receiver recorded the message
    QUEUED = "queued"              # held, then recorded/acted after the turn/prompt/modal ended
    INTERRUPTED = "interrupted"    # current turn aborted or steered by the message
    REJECTED = "rejected"          # sender got an explicit failure (loud)
    LOST = "lost"                  # sender reported success, receiver never recorded it (silent)
    HELD = "held"                  # sender accepted; receiver parked it visibly for a human Deny/Deliver
    NA = "n/a"
    ERROR = "error"                # harness failure or failed precondition
    ENV_ERROR = "env_error"        # sleep, network, quota, auth — requeued

class DraftFate(StrEnum):
    PRESERVED = "preserved"; SUBMITTED = "submitted"; MERGED = "merged"; LOST = "lost"; NA = "n/a"

class Ack(StrEnum):
    ACKED = "acked"; MODEL_NONCOMPLIANT = "model_noncompliant"; NONE = "none"

@dataclass(frozen=True)
class LaunchMods:
    host: HostKind
    backend: Backend = "none"
    extra_args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)   # path relative to work dir or "$HOME/…" (isolated home) -> content
    backend_argv: tuple[str, ...] | None = None
    launcher: tuple[str, ...] = ()        # bridge command that runs the agent from a PATH shim (e.g. `hcom claude`)
    path_prepend: tuple[str, ...] = ()    # extra PATH dirs for the agent and its tools (bridge CLIs)
    args_in_shim: bool = False            # the launcher gets no agent args; the PATH shim adds them

@dataclass(frozen=True)
class Target:
    run_id: str
    agent: AgentName
    host: HostKind
    backend: Backend
    work_dir: Path
    home_dir: Path
    session_id: str | None
    host_ref: str          # tmux "<socket>:<name>", iTerm2 "iterm2:<session id>", "zmx|zellij:<state dir>:<name>"
    backend_ref: str | None  # socket path or URL
    transcript: Path | None
    agent_pid: int | None

@dataclass(frozen=True)
class SendReceipt:
    accepted: bool
    sent_at: float          # time.time()
    sent_mono: float        # time.monotonic()
    retries: int = 0
    detail: str = ""
    spawned: tuple[int, ...] = ()   # pids the send left running (deferred senders); the caller tracks them
    waited_s: float = 0.0           # fixed waiting inside send (retry checks), excluded from send_s

class Host(Protocol):
    kind: HostKind
    def start(self, name: str, argv: list[str], env: dict[str, str], cwd: Path) -> str: ...  # returns host_ref
    def type_text(self, host_ref: str, text: str, submit: bool) -> None: ...                 # human-proxy typing (S7/S8)
    def capture(self, host_ref: str) -> str: ...
    def start_recording(self, host_ref: str, path: Path) -> None: ...
    def attach_command(self, host_ref: str) -> str: ...
    def stop(self, host_ref: str) -> None: ...

class Adapter(Protocol):
    name: str               # e.g. "tmux-paste", "tmux-paste-retry", "claude-uds-accept", "codex-queue"
    agents: frozenset[AgentName]
    kind: Literal["native", "terminal", "bridge"]
    claims_cross_machine: str | None   # quoted claim + source, or None
    def launch_mods(self, agent: AgentName, work_dir: Path, home_dir: Path) -> LaunchMods: ...
    def send(self, target: Target, text: str) -> SendReceipt: ...      # must return promptly (< 2 s); no blocking retry loops except the -retry variant
    def unwrap(self, recorded: str) -> str: ...                        # recorded receiver text -> original body
    def sender_argv(self, target: Target) -> list[str] | None: ...     # argv another agent can run; message body on stdin; None if no agent-usable sender
    def restart_backend(self, target: Target) -> str | None: ...       # kill and restart the backing server; None if there is none
    def run_sockets(self, work_dir: Path) -> list[Path]: ...           # sockets the launch creates (cleanup removes them)

class Transcript(Protocol):
    def entries(self) -> list[tuple[float, str, str]]: ...   # (ts, kind, text); received: user/peer/custom/hook, else assistant/tool_use/tool_result/system/queue/held/api_error
    def find_token(self, token: str) -> list[tuple[float, str, str]]: ...
    def is_idle(self) -> bool | None: ...                     # None = unknown from transcript

@dataclass
class Manifest:                 # runs/<run_id>/manifest.json, written on every change
    run_id: str
    pgids: list[int]
    targets: list[Target]
    sockets: list[Path]
    backends: list[str]
    identities: dict[int, str] = field(default_factory=dict)   # pid -> start time + executable hash
