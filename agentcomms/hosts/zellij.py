import contextlib
import json
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

ZELLIJ_BIN = REPO_ROOT / "vendor" / "bin" / "zellij"
PANE = "terminal_0"
SESSION_UP_S = 20.0
CONFIG_KDL = "show_startup_tips false\nshow_release_notes false\npane_frames false\ndefault_layout \"bare\"\n" \
             "session_serialization false\n"
LAYOUT_KDL = "layout {\n    pane\n}\n"


class ZellijError(HostError):
    pass


def split_ref(host_ref: str) -> tuple[Path, str]:
    prefix, _, rest = host_ref.partition(":")
    state, _, name = rest.rpartition(":")
    if prefix != "zellij" or not state or not name:
        raise ZellijError(f"{host_ref!r} is not a zellij ref")
    return Path(state), name


def make_ref(state_dir: Path, name: str) -> str:
    return f"zellij:{state_dir}:{name}"


def zellij_env(state_dir: Path) -> dict[str, str]:
    return {"HOME": str(state_dir / "home"), "ZELLIJ_CONFIG_DIR": str(state_dir / "config"),
            "ZELLIJ_SOCKET_DIR": str(state_dir / "s"), "PATH": "/usr/bin:/bin", "TERM": "xterm-256color",
            "TMPDIR": str(state_dir / "tmp")}


def create_argv(binary: Path, name: str, argv: list[str]) -> list[str]:
    return [str(binary), "attach", "--create-background", name, "--", *argv]


def attach_argv(binary: Path, name: str) -> list[str]:
    return [str(binary), "attach", name]


def action_argv(binary: Path, name: str, *action: str) -> list[str]:
    return [str(binary), "--session", name, "action", *action]


def write_chars_argv(binary: Path, name: str, text: str) -> list[str]:
    return action_argv(binary, name, "write-chars", "--pane-id", PANE, "--", text)


def write_bytes_argv(binary: Path, name: str, data: bytes) -> list[str]:
    return action_argv(binary, name, "write", "--pane-id", PANE, *(str(b) for b in data))


def paste_argv(binary: Path, name: str, text: str) -> list[str]:
    return action_argv(binary, name, "paste", "--pane-id", PANE, "--", text)


def dump_argv(binary: Path, name: str) -> list[str]:
    return action_argv(binary, name, "dump-screen", "--pane-id", PANE)


def subscribe_argv(binary: Path, name: str) -> list[str]:
    return [str(binary), "--session", name, "subscribe", "--pane-id", PANE]


def kill_argv(binary: Path, name: str) -> list[str]:
    return [str(binary), "kill-session", name]


def delete_argv(binary: Path, name: str) -> list[str]:
    return [str(binary), "delete-session", "--force", name]


def terminal_pane(list_panes_json: str) -> dict | None:
    try:
        panes = json.loads(list_panes_json)
    except json.JSONDecodeError:
        return None
    return next((p for p in panes if not p.get("is_plugin") and p.get("id") == 0), None)


def server_pid(rows: list[procs.ProcRow], state_dir: Path, name: str) -> int | None:
    suffix = f"--server {state_dir}/s/contract_version_1/{name}"
    return next((r.pid for r in rows if r.args.endswith(suffix)), None)


class ZellijHost:
    kind: HostKind = "zellij"
    term = "xterm-256color"

    def __init__(self, binary: Path = ZELLIJ_BIN, width: int = 200, height: int = 50):
        self.binary = binary
        self.width = width
        self.height = height

    def run(self, state_dir: Path, argv: list[str], check: bool = True) -> str:
        proc = subprocess.run(argv, capture_output=True, text=True, env=zellij_env(state_dir), cwd=state_dir,
                              timeout=30)
        if check and proc.returncode != 0:
            raise ZellijError(f"zellij {' '.join(argv[1:4])} failed: {proc.stderr.strip()[:200]}")
        return proc.stdout

    def prepare(self, state_dir: Path) -> None:
        for sub in ("home", "s", "tmp"):
            (state_dir / sub).mkdir(parents=True, exist_ok=True)
        layouts = state_dir / "config" / "layouts"
        layouts.mkdir(parents=True, exist_ok=True)
        (state_dir / "config" / "config.kdl").write_text(CONFIG_KDL)
        (layouts / "bare.kdl").write_text(LAYOUT_KDL)

    def start(self, name: str, argv: list[str], env: dict[str, str], cwd: Path, secret_file: Path | None = None,
              state_dir: Path | None = None) -> str:
        if state_dir is None:
            raise ZellijError("zellij needs a state dir")
        self.prepare(state_dir)
        wrapped = private_env_argv(argv, env, secret_file) if secret_file else env_wrapped(argv, env)
        subprocess.run(create_argv(self.binary, name, wrapped), capture_output=True, env=zellij_env(state_dir),
                       cwd=cwd, check=True)
        ref = make_ref(state_dir, name)
        try:
            deadline = time.monotonic() + SESSION_UP_S
            while not self.pane_listed(ref):
                if time.monotonic() > deadline:
                    raise ZellijError(f"zellij session {name} did not appear")
                time.sleep(0.3)
            client = spawn_in_pty(attach_argv(self.binary, name), cwd, zellij_env(state_dir), self.height,
                                  self.width, state_dir / "attach.log")
            try:
                time.sleep(2.0)
            finally:
                client.close()
        except BaseException:
            with contextlib.suppress(HostError):
                self.stop(ref)
            raise
        time.sleep(0.5)
        return ref

    def panes(self, host_ref: str) -> str:
        state, name = split_ref(host_ref)
        return self.run(state, action_argv(self.binary, name, "list-panes", "--all", "--json"), check=False)

    def pane_listed(self, host_ref: str) -> bool:
        return terminal_pane(self.panes(host_ref)) is not None

    def pane_pid(self, host_ref: str) -> int:
        state, name = split_ref(host_ref)
        pid = server_pid(procs.ps_rows(), state, name)
        if pid is None:
            raise ZellijError(f"no zellij server for {name}")
        return pid

    def alive(self, host_ref: str) -> bool:
        pane = terminal_pane(self.panes(host_ref))
        return pane is not None and not pane["exited"]

    def send_literal(self, host_ref: str, text: str) -> None:
        state, name = split_ref(host_ref)
        self.run(state, write_chars_argv(self.binary, name, text))

    def send_paste(self, host_ref: str, text: str) -> None:
        state, name = split_ref(host_ref)
        self.run(state, paste_argv(self.binary, name, text))

    def send_key(self, host_ref: str, key: str) -> None:
        state, name = split_ref(host_ref)
        self.run(state, write_bytes_argv(self.binary, name, key_bytes(key)))

    def type_text(self, host_ref: str, text: str, submit: bool) -> None:
        for piece in chunks(text, TYPE_CHUNK):
            self.send_literal(host_ref, piece)
            time.sleep(TYPE_DELAY_S)
        if submit:
            time.sleep(SUBMIT_SETTLE_S)
            self.send_key(host_ref, "Enter")

    def capture(self, host_ref: str) -> str:
        state, name = split_ref(host_ref)
        return self.run(state, dump_argv(self.binary, name))

    def start_recording(self, host_ref: str, path: Path) -> int:
        state, name = split_ref(host_ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        out = path.open("ab")
        proc = subprocess.Popen(subscribe_argv(self.binary, name), stdout=out, stderr=subprocess.DEVNULL,
                         env=zellij_env(state), cwd=path.parent, start_new_session=True)
        out.close()
        return proc.pid

    def attach_client(self, host_ref: str, log: Path, cwd: Path, env: dict[str, str]) -> AttachedClient:
        state, name = split_ref(host_ref)
        return spawn_in_pty(attach_argv(self.binary, name), cwd, zellij_env(state), self.height, self.width, log)

    def detach_client(self, host_ref: str) -> None:
        return None

    def attach_command(self, host_ref: str) -> str:
        state, name = split_ref(host_ref)
        env = " ".join(f"{k}={shlex.quote(v)}" for k, v in sorted(zellij_env(state).items())
                       if k.startswith(("ZELLIJ", "HOME")))
        return f"{env} {shlex.join(attach_argv(self.binary, name))}"

    def stop(self, host_ref: str) -> None:
        state, name = split_ref(host_ref)
        try:
            self.run(state, kill_argv(self.binary, name), check=False)
            self.run(state, delete_argv(self.binary, name), check=False)
            survived = self.pane_listed(host_ref)
        except (OSError, subprocess.SubprocessError) as e:
            raise ZellijError(f"zellij kill-session {name}: {type(e).__name__}: {e}") from e
        if survived:
            raise ZellijError(f"zellij session {name} still has a pane after kill-session")


def state_dir_for(run_id: str, root: Path) -> Path:
    return root / f"{run_id}-zj"
