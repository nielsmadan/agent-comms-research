import contextlib
import shlex
import subprocess
import time
from pathlib import Path

from agentcomms import procs
from agentcomms.hosts.errors import HostError
from agentcomms.hosts.keys import key_bytes
from agentcomms.hosts.pty_client import spawn_in_pty
from agentcomms.hosts.tmux import (
    SUBMIT_SETTLE_S,
    TYPE_CHUNK,
    TYPE_DELAY_S,
    AttachedClient,
    chunks,
    env_wrapped,
    private_env_argv,
)
from agentcomms.model import HostKind
from agentcomms.paths import REPO_ROOT

ZMX_BIN = REPO_ROOT / "vendor" / "bin" / "zmx"
SESSION_UP_S = 15.0


class ZmxError(HostError):
    pass


def split_ref(host_ref: str) -> tuple[Path, str]:
    prefix, _, rest = host_ref.partition(":")
    state, _, name = rest.rpartition(":")
    if prefix != "zmx" or not state or not name:
        raise ZmxError(f"{host_ref!r} is not a zmx ref")
    return Path(state), name


def make_ref(state_dir: Path, name: str) -> str:
    return f"zmx:{state_dir}:{name}"


def zmx_env(state_dir: Path) -> dict[str, str]:
    return {"ZMX_DIR": str(state_dir), "HOME": str(state_dir / "home"), "XDG_STATE_HOME": str(state_dir / "state"),
            "PATH": "/usr/bin:/bin", "TERM": "xterm-256color",
            "TMPDIR": str(state_dir / "tmp")}


def attach_argv(binary: Path, name: str, argv: list[str]) -> list[str]:
    return [str(binary), "attach", name, *argv]


def send_argv(binary: Path, name: str, text: str) -> list[str]:
    return [str(binary), "send", name, text]


def history_argv(binary: Path, name: str) -> list[str]:
    return [str(binary), "history", name]


def tail_argv(binary: Path, name: str) -> list[str]:
    return [str(binary), "tail", name]


def kill_argv(binary: Path, name: str) -> list[str]:
    return [str(binary), "kill", name, "--force"]


def parse_ls(output: str) -> dict[str, dict[str, str]]:
    rows = {}
    for line in output.splitlines():
        fields = dict(f.split("=", 1) for f in line.strip().split("\t") if "=" in f)
        if "name" in fields:
            rows[fields["name"]] = fields
    return rows


class ZmxHost:
    kind: HostKind = "zmx"
    term = "xterm-256color"

    def __init__(self, binary: Path = ZMX_BIN, width: int = 200, height: int = 50):
        self.binary = binary
        self.width = width
        self.height = height

    def run(self, state_dir: Path, argv: list[str], check: bool = True) -> str:
        proc = subprocess.run(argv, capture_output=True, text=True, env=zmx_env(state_dir), cwd=state_dir,
                              timeout=30)
        if check and proc.returncode != 0:
            raise ZmxError(f"zmx {argv[1]} failed: {proc.stderr.strip()}")
        return proc.stdout

    def sessions(self, state_dir: Path) -> dict[str, dict[str, str]]:
        if not state_dir.exists():
            return {}
        return parse_ls(self.run(state_dir, [str(self.binary), "ls"], check=False))

    def start(self, name: str, argv: list[str], env: dict[str, str], cwd: Path, secret_file: Path | None = None,
              state_dir: Path | None = None) -> str:
        if state_dir is None:
            raise ZmxError("zmx needs a state dir")
        for sub in ("home", "state", "tmp"):
            (state_dir / sub).mkdir(parents=True, exist_ok=True)
        wrapped = private_env_argv(argv, env, secret_file) if secret_file else env_wrapped(argv, env)
        client = spawn_in_pty(attach_argv(self.binary, name, wrapped), cwd, zmx_env(state_dir), self.height,
                              self.width, state_dir / "attach.log")
        ref = make_ref(state_dir, name)
        try:
            deadline = time.monotonic() + SESSION_UP_S
            while name not in self.sessions(state_dir):
                if time.monotonic() > deadline:
                    raise ZmxError(f"zmx session {name} did not appear")
                time.sleep(0.2)
            time.sleep(0.5)
        except BaseException:
            with contextlib.suppress(HostError):
                self.stop(ref)
            raise
        finally:
            client.close()
        return ref

    def pane_pid(self, host_ref: str) -> int:
        state, name = split_ref(host_ref)
        child = int(self.sessions(state)[name]["pid"])
        row = next(r for r in procs.ps_rows() if r.pid == child)
        return row.ppid

    def alive(self, host_ref: str) -> bool:
        state, name = split_ref(host_ref)
        return name in self.sessions(state)

    def send_literal(self, host_ref: str, text: str) -> None:
        state, name = split_ref(host_ref)
        self.run(state, send_argv(self.binary, name, text))

    def send_key(self, host_ref: str, key: str) -> None:
        self.send_literal(host_ref, key_bytes(key).decode("latin-1"))

    def type_text(self, host_ref: str, text: str, submit: bool) -> None:
        for piece in chunks(text, TYPE_CHUNK):
            self.send_literal(host_ref, piece)
            time.sleep(TYPE_DELAY_S)
        if submit:
            time.sleep(SUBMIT_SETTLE_S)
            self.send_key(host_ref, "Enter")

    def capture(self, host_ref: str) -> str:
        state, name = split_ref(host_ref)
        return self.run(state, history_argv(self.binary, name))

    def start_recording(self, host_ref: str, path: Path) -> int:
        state, name = split_ref(host_ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        out = path.open("ab")
        proc = subprocess.Popen(tail_argv(self.binary, name), stdout=out, stderr=subprocess.DEVNULL, env=zmx_env(state),
                         cwd=path.parent, start_new_session=True)
        out.close()
        return proc.pid

    def attach_client(self, host_ref: str, log: Path, cwd: Path, env: dict[str, str]) -> AttachedClient:
        state, name = split_ref(host_ref)
        return spawn_in_pty(attach_argv(self.binary, name, []), cwd, zmx_env(state), self.height, self.width, log)

    def detach_client(self, host_ref: str) -> None:
        return None

    def attach_command(self, host_ref: str) -> str:
        state, name = split_ref(host_ref)
        return f"ZMX_DIR={shlex.quote(str(state))} {shlex.join(attach_argv(self.binary, name, []))}"

    def stop(self, host_ref: str) -> None:
        state, name = split_ref(host_ref)
        try:
            self.run(state, kill_argv(self.binary, name), check=False)
            survived = name in self.sessions(state)
        except (OSError, subprocess.SubprocessError) as e:
            raise ZmxError(f"zmx kill {name}: {type(e).__name__}: {e}") from e
        if survived:
            raise ZmxError(f"zmx session {name} still listed after kill")


def state_dir_for(run_id: str, root: Path) -> Path:
    return root / f"{run_id}-zmx"

