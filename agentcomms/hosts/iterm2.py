import asyncio
import concurrent.futures
import contextlib
import fcntl
import os
import re
import shlex
import subprocess
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentcomms.hosts.errors import HolderBlocked, HostError
from agentcomms.hosts.keys import key_bytes
from agentcomms.hosts.tmux import (
    SUBMIT_SETTLE_S,
    TYPE_CHUNK,
    TYPE_DELAY_S,
    chunks,
    env_wrapped,
    private_env_argv,
)
from agentcomms.model import HostKind
from agentcomms.paths import SOCKET_DIR

ITERM_APP = Path("/Applications/Development/iTerm.app")
CALL_TIMEOUT_S = 30.0
REF_PREFIX = "iterm2:"
HOLDER_VAR = "user.agentcomms_holder"
PLACEHOLDER_VAR = "user.agentcomms_placeholder"
HOLDER_COMMAND = "/bin/sleep 31536000"
FRONT_ASN = re.compile(r"ASN:\S+")
ITERM_BUNDLE = "com.googlecode.iterm2"
HOLDER_WAIT_S = 600.0
HOLDER_POLL_S = 2.0
FOCUS_SETTLE_S = 0.4
LATE_TAB_WAIT_S = 30.0
HOLDER_LOCK = SOCKET_DIR / "iterm-holder.lock"
HOLDER_BLOCKED = "iterm-holder-blocked: iTerm2 frontmost"
HOLDER_LOCK_BLOCKED = "iterm-holder-blocked: another process holds the holder-creation lock"


class ItermError(HostError):
    pass


class ItermUnavailable(ItermError):
    pass


def session_id(host_ref: str) -> str:
    if not host_ref.startswith(REF_PREFIX):
        raise ItermError(f"{host_ref!r} is not an iTerm2 ref")
    return host_ref[len(REF_PREFIX):]


def command_line(argv: list[str]) -> str:
    return shlex.join(argv)


def screen_text(lines: list[str]) -> str:
    return "\n".join(line.rstrip() for line in lines).rstrip("\n") + "\n"


class ItermLoop:
    def __init__(self, app_path: Path = ITERM_APP):
        self.app_path = app_path
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.connection: Any = None
        self.tasks: dict[str, asyncio.Task] = {}

    def call(self, make: Callable[[Any], Awaitable[Any]], timeout: float = CALL_TIMEOUT_S) -> Any:
        async def run():
            if self.connection is None:
                self.connection = await self.connect()
            return await make(self.connection)
        future = asyncio.run_coroutine_threadsafe(run(), self.loop)
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise

    async def connect(self) -> Any:
        import iterm2
        from iterm2.auth import AuthenticationException
        os.environ["IT2_APP_PATH"] = str(self.app_path)
        try:
            return await iterm2.Connection.async_create()
        except AuthenticationException as e:
            raise ItermUnavailable(f"iTerm2 refused the cookie request: {e}") from e
        except Exception as e:
            raise ItermUnavailable(f"cannot connect to the iTerm2 API: {type(e).__name__}: {e}") from e

    def close(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)


_LOOP: ItermLoop | None = None
_LOOP_LOCK = threading.Lock()


def shared_loop() -> ItermLoop:
    global _LOOP
    with _LOOP_LOCK:
        if _LOOP is None:
            _LOOP = ItermLoop()
        return _LOOP


async def find_session(connection: Any, sid: str) -> Any:
    import iterm2
    app = await iterm2.async_get_app(connection)
    return app.get_session_by_id(sid)


async def record_screen(connection: Any, sid: str, path: Path) -> None:
    session = await find_session(connection, sid)
    last = ""
    async with session.get_screen_streamer() as streamer:
        while True:
            contents = await streamer.async_get()
            text = screen_text([contents.line(i).string for i in range(contents.number_of_lines)])
            if text != last:
                last = text
                with path.open("a") as out:
                    out.write(f"--- {time.time():.3f}\n{text}")


@dataclass(frozen=True)
class Focus:
    app: str
    window: str | None
    iterm_front: bool = False

    def describe(self) -> str:
        return f"{self.app}/{self.window or '-'}"


def focus_stolen(before: Focus, after: Focus) -> bool:
    if before.app != after.app:
        return True
    return before.iterm_front and before.window != after.window


def lsappinfo(*args: str) -> str:
    proc = subprocess.run(["lsappinfo", *args], capture_output=True, text=True, timeout=10)
    return proc.stdout.strip()


def front_app() -> str:
    m = FRONT_ASN.search(lsappinfo("front"))
    return m.group(0) if m else ""


def is_iterm(asn: str) -> bool:
    return bool(asn) and ITERM_BUNDLE in lsappinfo("info", "-only", "bundleid", asn).lower()


def restore_front_app(asn: str) -> None:
    bundle = re.search(r'"?(/[^"\n]+\.app)', lsappinfo("info", "-only", "bundlepath", asn))
    if bundle:
        subprocess.run(["open", bundle.group(1)], capture_output=True, timeout=10)


async def current_focus(app: Any) -> Focus:
    with contextlib.suppress(Exception):
        await app.async_refresh()
    window = app.current_terminal_window
    asn = front_app()
    return Focus(asn, window.window_id if window else None, is_iterm(asn))


async def restore_focus(before: Focus) -> None:
    # Only the previously frontmost non-iTerm2 app is re-activated; no iTerm2 window is ever activated.
    if before.app and not before.iterm_front and front_app() != before.app:
        restore_front_app(before.app)


async def check_focus(app: Any, before: Focus, settle_s: float | None = None) -> tuple[Focus, bool]:
    await asyncio.sleep(FOCUS_SETTLE_S if settle_s is None else settle_s)
    after = await current_focus(app)
    stolen = focus_stolen(before, after)
    if stolen:
        await restore_focus(before)
    return after, stolen


def focus_notes(before: Focus, after: Focus, stolen: bool) -> list[str]:
    return [f"iterm-focus {before.describe()} -> {after.describe()}", *(["focus_stolen=yes"] if stolen else [])]


async def find_holder(windows: list[Any]) -> Any:
    for window in windows:
        with contextlib.suppress(Exception):
            if await window.async_get_variable(HOLDER_VAR) == "1":
                return window
    return None


@contextlib.asynccontextmanager
async def holder_lock(wait_s: float):
    HOLDER_LOCK.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(HOLDER_LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        end = time.monotonic() + wait_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= end:
                    raise HolderBlocked(HOLDER_LOCK_BLOCKED) from None
                await asyncio.sleep(1.0)
        yield
    finally:
        os.close(fd)


async def new_holder_window(connection: Any) -> Any:
    import iterm2
    from iterm2.profile import LocalWriteOnlyProfile
    profile = LocalWriteOnlyProfile()
    profile.set_use_custom_command("Yes")
    profile.set_command(HOLDER_COMMAND)
    profile.set_name("agentcomms holder")
    holder = await iterm2.Window.async_create(connection, profile_customizations=profile)
    if holder is None:
        raise ItermError("the holder window ended right away")
    try:
        await holder.async_set_variable(HOLDER_VAR, "1")
        await holder.current_tab.current_session.async_set_variable(PLACEHOLDER_VAR, "1")
    except Exception:
        with contextlib.suppress(Exception):
            await holder.async_close(force=True)
        raise
    return holder


async def ensure_holder(connection: Any, app: Any, notes: list[str], wait_s: float | None = None,
                        poll_s: float | None = None) -> Any:
    holder = await find_holder(list(app.terminal_windows))
    if holder is not None:
        return holder
    wait_s = HOLDER_WAIT_S if wait_s is None else wait_s
    poll_s = HOLDER_POLL_S if poll_s is None else poll_s
    end = time.monotonic() + wait_s
    async with holder_lock(wait_s):
        while True:
            before = await current_focus(app)
            holder = await find_holder(list(app.terminal_windows))
            if holder is not None:
                return holder
            if not before.iterm_front:
                break
            if time.monotonic() >= end:
                raise HolderBlocked(HOLDER_BLOCKED)
            await asyncio.sleep(poll_s)
        holder = await new_holder_window(connection)
        after, stolen = await check_focus(app, before)
    notes += ["iterm-holder-created", *focus_notes(before, after, stolen)]
    return holder


async def release_sessions(connection: Any, session_ids: list[str]) -> tuple[list[str], bool]:
    import iterm2
    app = await iterm2.async_get_app(connection)
    before = await current_focus(app)
    closed = []
    for sid in session_ids:
        session = app.get_session_by_id(sid)
        if session is None:
            continue
        with contextlib.suppress(Exception):
            if await session.async_get_variable(PLACEHOLDER_VAR) == "1":
                continue
        await session.async_close(force=True)
        closed.append(sid)
    _, stolen = await check_focus(app, before)
    return closed, stolen


async def holder_is_empty(holder: Any) -> bool:
    for tab in holder.tabs:
        for session in tab.sessions:
            with contextlib.suppress(Exception):
                if await session.async_get_variable(PLACEHOLDER_VAR) == "1":
                    continue
            return False
    return True


async def close_holder(connection: Any) -> list[str]:
    import iterm2
    app = await iterm2.async_get_app(connection)
    holder = await find_holder(list(app.terminal_windows))
    if holder is None:
        return ["no iTerm2 holder window"]
    if not await holder_is_empty(holder):
        return [f"iTerm2 holder {holder.window_id} still has cell tabs; left open"]
    before = await current_focus(app)
    await holder.async_close(force=True)
    after, stolen = await check_focus(app, before)
    return [f"closed iTerm2 holder {holder.window_id}", *focus_notes(before, after, stolen)]


async def prepare_holder(connection: Any, wait_s: float | None = None) -> list[str]:
    import iterm2
    app = await iterm2.async_get_app(connection)
    existed = await find_holder(list(app.terminal_windows)) is not None
    notes: list[str] = []
    holder = await ensure_holder(connection, app, notes, wait_s)
    return [f"iTerm2 holder {holder.window_id} {'already open' if existed else 'created'}", *notes]


def holder_wait_timeout(wait_s: float | None) -> float:
    return (HOLDER_WAIT_S if wait_s is None else wait_s) + CALL_TIMEOUT_S


def prepare_holder_sync(wait_s: float | None = None, loop: ItermLoop | None = None) -> list[str]:
    return (loop or shared_loop()).call(lambda c: prepare_holder(c, wait_s), holder_wait_timeout(wait_s))


def close_holder_sync(loop: ItermLoop | None = None) -> list[str]:
    return (loop or shared_loop()).call(close_holder)


async def close_late_tab(creating: asyncio.Future) -> None:
    with contextlib.suppress(Exception):
        tab = await asyncio.wait_for(creating, LATE_TAB_WAIT_S)
        if tab is not None:
            await tab.current_session.async_close(force=True)


class ItermHost:
    kind: HostKind = "iterm2"
    term = "xterm-256color"

    def __init__(self, loop: ItermLoop | None = None, width: int = 200, height: int = 50):
        self.loop = loop or shared_loop()
        self.width = width
        self.height = height
        self.notes: list[str] = []

    def take_notes(self) -> list[str]:
        notes, self.notes = self.notes, []
        return notes

    def start(self, name: str, argv: list[str], env: dict[str, str], cwd: Path, secret_file: Path | None = None,
              state_dir: Path | None = None) -> str:
        wrapped = private_env_argv(argv, env, secret_file) if secret_file else env_wrapped(argv, env)
        command = command_line(wrapped)

        async def create(connection: Any) -> tuple[str, list[str]]:
            import iterm2
            from iterm2.profile import InitialWorkingDirectory, LocalWriteOnlyProfile
            from iterm2.util import Size
            app = await iterm2.async_get_app(connection)
            notes: list[str] = []
            holder = await ensure_holder(connection, app, notes)
            before = await current_focus(app)
            profile = LocalWriteOnlyProfile()
            profile.set_use_custom_command("Yes")
            profile.set_command(command)
            profile.set_initial_directory_mode(InitialWorkingDirectory.INITIAL_WORKING_DIRECTORY_CUSTOM)
            profile.set_custom_directory(str(cwd))
            profile.set_name(name)
            creating = asyncio.ensure_future(holder.async_create_tab(profile_customizations=profile, select=False))
            try:
                tab = await asyncio.shield(creating)
            except asyncio.CancelledError:
                await close_late_tab(creating)
                raise
            if tab is None:
                raise ItermError("the iTerm2 session ended right away")
            session = tab.current_session
            try:
                with contextlib.suppress(Exception):
                    await session.async_set_grid_size(Size(self.width, self.height))
                after, stolen = await check_focus(app, before)
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    await session.async_close(force=True)
                raise
            return session.session_id, notes + focus_notes(before, after, stolen)
        sid, notes = self.loop.call(create, holder_wait_timeout(None))
        self.notes += notes
        return f"{REF_PREFIX}{sid}"

    def pane_pid(self, host_ref: str) -> int:
        sid = session_id(host_ref)

        async def read(connection: Any) -> int:
            session = await find_session(connection, sid)
            if session is None:
                raise ItermError(f"iTerm2 session {sid} is gone")
            return int(await session.async_get_variable("pid"))
        return self.loop.call(read)

    def alive(self, host_ref: str) -> bool:
        sid = session_id(host_ref)

        async def check(connection: Any) -> bool:
            return await find_session(connection, sid) is not None
        return bool(self.loop.call(check))

    def send_literal(self, host_ref: str, text: str) -> None:
        sid = session_id(host_ref)

        async def send(connection: Any) -> None:
            session = await find_session(connection, sid)
            if session is None:
                raise ItermError(f"iTerm2 session {sid} is gone")
            await session.async_send_text(text)
        self.loop.call(send)

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
        sid = session_id(host_ref)

        async def read(connection: Any) -> str:
            session = await find_session(connection, sid)
            if session is None:
                raise ItermError(f"iTerm2 session {sid} is gone")
            contents = await session.async_get_screen_contents()
            return screen_text([contents.line(i).string for i in range(contents.number_of_lines)])
        return self.loop.call(read)

    def start_recording(self, host_ref: str, path: Path) -> None:
        sid = session_id(host_ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        task = asyncio.run_coroutine_threadsafe(self.record(sid, path), self.loop.loop)
        self.loop.tasks[sid] = task

    async def record(self, sid: str, path: Path) -> None:
        with contextlib.suppress(Exception):
            await record_screen(self.loop.connection, sid, path)

    def attach_command(self, host_ref: str) -> str:
        return f"iTerm2 window for session {session_id(host_ref)} (already attached)"

    def stop(self, host_ref: str) -> None:
        sid = session_id(host_ref)
        task = self.loop.tasks.pop(sid, None)
        if task is not None:
            task.cancel()
        with contextlib.suppress(Exception):
            _, stolen = release_sessions_sync([sid], self.loop)
            if stolen:
                self.notes.append("focus_stolen=yes")


def release_sessions_sync(session_ids: list[str], loop: ItermLoop | None = None) -> tuple[list[str], bool]:
    loop = loop or shared_loop()
    return loop.call(lambda connection: release_sessions(connection, session_ids))
