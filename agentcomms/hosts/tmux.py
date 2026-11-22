import contextlib
import fcntl
import os
import pty
import re
import shlex
import struct
import subprocess
import termios
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from agentcomms.hosts.errors import HostError
from agentcomms.model import HostKind
from agentcomms.paths import SOCKET_DIR, TMUX_SOCKET

TMUX_TIMEOUT_S = 30.0


class TmuxError(HostError):
    pass


def harness_socket(socket: str) -> bool:
    return socket == TMUX_SOCKET or (socket.startswith(f"{TMUX_SOCKET}-") and socket.replace("-", "").isalnum())


def split_ref(host_ref: str) -> tuple[str, str]:
    socket, sep, name = host_ref.partition(":")
    if not (sep and name and harness_socket(socket)):
        raise TmuxError(f"{host_ref!r} is not an agentcomms tmux ref")
    return socket, name


def session_name(host_ref: str) -> str:
    return split_ref(host_ref)[1]


def ref_socket(host_ref: str) -> str:
    return split_ref(host_ref)[0]


def socket_args(socket: str) -> list[str]:
    if not harness_socket(socket):
        raise TmuxError(f"{socket!r} is not an agentcomms tmux socket")
    return ["-L", socket] if socket == TMUX_SOCKET else ["-S", str(SOCKET_DIR / socket)]


def split_trailing_semicolons(text: str) -> tuple[str, int]:
    body = text.rstrip(";")
    return body, len(text) - len(body)


TYPE_CHUNK = 6
TYPE_DELAY_S = 0.03
SUBMIT_SETTLE_S = 0.4
ANSI = re.compile(r"\x1b\[[0-9;?<>=]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][0-9A-Za-z]|\x1b[=>78]")
CURSOR_FORWARD = re.compile(r"\x1b\[(\d*)C")


def strip_ansi(raw: str) -> str:
    spaced = CURSOR_FORWARD.sub(lambda m: " " * int(m.group(1) or 1), raw)
    return ANSI.sub("", spaced)


def chunks(text: str, size: int = TYPE_CHUNK) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]


@dataclass
class AttachedClient:
    proc: subprocess.Popen
    master: int
    log: Path
    reader: threading.Thread

    def text(self) -> str:
        return strip_ansi(self.log.read_text(errors="replace")) if self.log.exists() else ""

    def close(self) -> None:
        with contextlib.suppress(ProcessLookupError):
            self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        self.reader.join(timeout=2)
        with contextlib.suppress(OSError):
            os.close(self.master)


def copy_stream(fd: int, path: Path) -> None:
    with path.open("ab") as out:
        while True:
            try:
                data = os.read(fd, 65536)
            except OSError:
                return
            if not data:
                return
            out.write(data)
            out.flush()


SECRET_ENV = frozenset({"OPENCODE_PASSWORD"})
SOURCE_AND_EXEC = '. "$0" && exec "$@"'


def split_secret_env(env: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    return ({k: v for k, v in env.items() if k not in SECRET_ENV},
            {k: v for k, v in env.items() if k in SECRET_ENV})


def secret_env_text(secret: dict[str, str]) -> str:
    return "".join(f"export {k}={shlex.quote(v)}\n" for k, v in sorted(secret.items()))


def write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(text)


def env_wrapped(argv: list[str], env: dict[str, str], secret_file: Path | None = None) -> list[str]:
    public, secret = split_secret_env(env)
    if secret and secret_file is None:
        raise ValueError(f"{', '.join(sorted(secret))} must go through a private env file, not argv")
    inner = ["/bin/sh", "-c", SOURCE_AND_EXEC, str(secret_file), *argv] if secret else argv
    return ["/usr/bin/env", "-i", *(f"{k}={v}" for k, v in sorted(public.items())), *inner]


def private_env_argv(argv: list[str], env: dict[str, str], secret_file: Path) -> list[str]:
    secret = split_secret_env(env)[1]
    if secret:
        write_private(secret_file, secret_env_text(secret))
    return env_wrapped(argv, env, secret_file)


class TmuxHost:
    kind: HostKind = "tmux"
    term = "tmux-256color"

    def __init__(self, conf: Path, socket: str = TMUX_SOCKET, width: int = 200, height: int = 50):
        self.conf = conf
        self.socket = socket
        self.width = width
        self.height = height

    def base(self, socket: str | None = None) -> list[str]:
        return ["tmux", *socket_args(socket or self.socket), "-f", str(self.conf)]

    def run(self, *args: str, check: bool = True, input_text: str | None = None, socket: str | None = None) -> str:
        proc = subprocess.run([*self.base(socket), *args], capture_output=True, text=True, input=input_text,
                              timeout=TMUX_TIMEOUT_S)
        if check and proc.returncode != 0:
            raise TmuxError(f"tmux {args[0]} failed: {proc.stderr.strip()}")
        return proc.stdout

    def on(self, host_ref: str, *args: str, check: bool = True, input_text: str | None = None) -> str:
        return self.run(*args, check=check, input_text=input_text, socket=ref_socket(host_ref))

    def target(self, host_ref: str) -> str:
        return f"={session_name(host_ref)}:"

    def start(self, name: str, argv: list[str], env: dict[str, str], cwd: Path,
              secret_file: Path | None = None, state_dir: Path | None = None) -> str:
        wrapped = private_env_argv(argv, env, secret_file) if secret_file else env_wrapped(argv, env)
        self.run("new-session", "-d", "-s", name, "-x", str(self.width), "-y", str(self.height),
                 "-c", str(cwd), "--", *wrapped)
        return f"{self.socket}:{name}"

    def pane_pid(self, host_ref: str) -> int:
        return int(self.on(host_ref, "display-message", "-p", "-t", self.target(host_ref), "#{pane_pid}").strip())

    def alive(self, host_ref: str) -> bool:
        proc = subprocess.run([*self.base(ref_socket(host_ref)), "has-session", "-t", f"={session_name(host_ref)}"],
                              capture_output=True, text=True, timeout=TMUX_TIMEOUT_S)
        return proc.returncode == 0

    def send_literal(self, host_ref: str, text: str) -> None:
        body, semicolons = split_trailing_semicolons(text)
        if body:
            self.on(host_ref, "send-keys", "-t", self.target(host_ref), "-l", "--", body)
        if semicolons:
            self.on(host_ref, "send-keys", "-t", self.target(host_ref), "-H", *["3b"] * semicolons)

    def send_key(self, host_ref: str, key: str) -> None:
        self.on(host_ref, "send-keys", "-t", self.target(host_ref), key)

    def type_text(self, host_ref: str, text: str, submit: bool) -> None:
        for piece in chunks(text):
            self.send_literal(host_ref, piece)
            time.sleep(TYPE_DELAY_S)
        if submit:
            time.sleep(SUBMIT_SETTLE_S)
            self.send_key(host_ref, "Enter")

    def attach_client(self, host_ref: str, log: Path, cwd: Path, env: dict[str, str]) -> AttachedClient:
        log.parent.mkdir(parents=True, exist_ok=True)
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", self.height, self.width, 0, 0))
        try:
            proc = subprocess.Popen([*self.base(ref_socket(host_ref)), "attach", "-t", f"={session_name(host_ref)}"],
                                    stdin=slave, stdout=slave, stderr=slave, cwd=cwd, env=env,
                                    start_new_session=True)
        finally:
            os.close(slave)
        reader = threading.Thread(target=copy_stream, args=(master, log), daemon=True)
        reader.start()
        return AttachedClient(proc, master, log, reader)

    def detach_client(self, host_ref: str) -> None:
        self.on(host_ref, "detach-client", "-s", f"={session_name(host_ref)}", check=False)

    def capture(self, host_ref: str) -> str:
        return self.on(host_ref, "capture-pane", "-p", "-J", "-t", self.target(host_ref))

    def load_buffer(self, buffer: str, text: str, host_ref: str | None = None) -> None:
        self.run("load-buffer", "-b", buffer, "-", input_text=text, socket=ref_socket(host_ref) if host_ref else None)

    def paste_buffer(self, host_ref: str, buffer: str) -> None:
        self.on(host_ref, "paste-buffer", "-p", "-d", "-b", buffer, "-t", self.target(host_ref))

    def start_recording(self, host_ref: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.on(host_ref, "pipe-pane", "-o", "-t", self.target(host_ref), f"cat >> {shlex.quote(str(path))}")

    def attach_command(self, host_ref: str) -> str:
        return shlex.join([*self.base(ref_socket(host_ref)), "attach", "-t", session_name(host_ref)])

    def stop(self, host_ref: str) -> None:
        self.on(host_ref, "kill-session", "-t", f"={session_name(host_ref)}", check=False)
