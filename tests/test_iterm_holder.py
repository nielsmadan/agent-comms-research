import asyncio

import iterm2 as pkg
import pytest

from agentcomms.engine import failure_note
from agentcomms.hosts import iterm2
from agentcomms.hosts.errors import HolderBlocked
from agentcomms.hosts.iterm2 import HOLDER_VAR, PLACEHOLDER_VAR, Focus

USER_APP = "ASN:user"
ITERM_APP = "ASN:iterm"


class World:
    def __init__(self, front=USER_APP, current_window=None):
        self.front = front
        self.current_window = current_window
        self.log = []
        self.restored = []
        self.windows = []
        self.created_with_front = []


class FakeSession:
    def __init__(self, sid, variables=None):
        self.session_id = sid
        self.variables = variables or {}
        self.closed = False
        self.grid = None

    async def async_get_variable(self, name):
        return self.variables.get(name)

    async def async_set_variable(self, name, value):
        self.variables[name] = value

    async def async_close(self, force=False):
        self.closed = True

    async def async_set_grid_size(self, size):
        self.grid = size


class FakeTab:
    def __init__(self, sessions):
        self.sessions = sessions

    @property
    def current_session(self):
        return self.sessions[0]


class FakeWindow:
    def __init__(self, world, wid, sessions, holder=False):
        self.world = world
        self.window_id = wid
        self.tabs = [FakeTab([s]) for s in sessions]
        self.variables = {HOLDER_VAR: "1"} if holder else {}
        self.closed = False
        self.created_tabs = []
        self.steals_on_tab = False

    @property
    def current_tab(self):
        return self.tabs[0]

    async def async_get_variable(self, name):
        return self.variables.get(name)

    async def async_set_variable(self, name, value):
        self.variables[name] = value

    async def async_close(self, force=False):
        self.closed = True
        self.world.log.append(("close-window", self.window_id))

    async def async_create_tab(self, profile_customizations=None, select=True):
        self.created_tabs.append(select)
        session = FakeSession(f"cell{len(self.created_tabs)}")
        self.tabs.append(FakeTab([session]))
        if self.steals_on_tab:
            self.world.front = ITERM_APP
        return self.tabs[-1]


class FakeApp:
    def __init__(self, world):
        self.world = world
        self.refreshes = 0

    @property
    def terminal_windows(self):
        return [w for w in self.world.windows if not w.closed]

    @property
    def current_terminal_window(self):
        return next((w for w in self.world.windows if w.window_id == self.world.current_window), None)

    async def async_refresh(self):
        self.refreshes += 1
        for window in self.world.windows:
            window.tabs = [t for t in window.tabs if not any(s.closed for s in t.sessions)]

    def get_session_by_id(self, sid):
        return next((s for w in self.world.windows for t in w.tabs for s in t.sessions if s.session_id == sid), None)


class FakeLoop:
    def __init__(self, app):
        self.app = app
        self.tasks = {}

    def call(self, make, timeout=30.0):
        return asyncio.run(make(object()))


@pytest.fixture
def world(monkeypatch, tmp_path):
    w = World()
    app = FakeApp(w)

    async def get_app(_connection):
        await app.async_refresh()
        return app

    def front_app():
        w.log.append(("front", w.front))
        return w.front

    async def create_window(connection, profile_customizations=None):
        w.created_with_front.append(w.front)
        w.log.append(("create", w.front))
        window = FakeWindow(w, "holder-new", [FakeSession("ph")])
        w.windows.append(window)
        if w.steal_on_create:
            w.front = ITERM_APP
        return window

    w.steal_on_create = False
    w.app = app
    monkeypatch.setattr(pkg, "async_get_app", get_app)
    monkeypatch.setattr(pkg.Window, "async_create", create_window)
    monkeypatch.setattr(iterm2, "front_app", front_app)
    monkeypatch.setattr(iterm2, "is_iterm", lambda asn: asn == ITERM_APP)
    monkeypatch.setattr(iterm2, "restore_front_app", lambda asn: (w.restored.append(asn), setattr(w, "front", asn)))
    monkeypatch.setattr(iterm2, "FOCUS_SETTLE_S", 0.0)
    monkeypatch.setattr(iterm2, "HOLDER_POLL_S", 0.01)
    monkeypatch.setattr(iterm2, "HOLDER_LOCK", tmp_path / "holder.lock")
    return w


def host_for(world):
    return iterm2.ItermHost(loop=FakeLoop(world.app))


def start(host, tmp_path):
    return host.start("cell", ["/bin/true"], {"A": "b"}, tmp_path)


def existing_holder(world):
    holder = FakeWindow(world, "holder-1", [FakeSession("ph", {PLACEHOLDER_VAR: "1"})], holder=True)
    world.windows.append(holder)
    return holder


def run(coro):
    return asyncio.run(coro)


def test_find_holder_uses_the_variable_not_the_title():
    world = World()
    user = FakeWindow(world, "w1", [FakeSession("a")])
    holder = FakeWindow(world, "w2", [FakeSession("h", {PLACEHOLDER_VAR: "1"})], holder=True)
    assert run(iterm2.find_holder([user, holder])) is holder
    assert run(iterm2.find_holder([user])) is None


def test_window_change_only_counts_when_iterm_was_frontmost():
    elsewhere = Focus("ASN:brave", "w1", iterm_front=False)
    assert not iterm2.focus_stolen(elsewhere, Focus("ASN:brave", None, iterm_front=False))
    assert iterm2.focus_stolen(elsewhere, Focus("ASN:iterm", "w9", iterm_front=True))
    front = Focus("ASN:iterm", "w1", iterm_front=True)
    assert iterm2.focus_stolen(front, Focus("ASN:iterm", "w2", iterm_front=True))
    assert not iterm2.focus_stolen(front, front)


def test_start_creates_the_cell_tab_unselected_in_the_existing_holder(world, tmp_path):
    holder = existing_holder(world)
    host = host_for(world)
    ref = start(host, tmp_path)
    assert ref == "iterm2:cell1"
    assert holder.created_tabs == [False]
    assert world.created_with_front == []
    assert host.take_notes() == [f"iterm-focus {USER_APP}/- -> {USER_APP}/-"]
    assert world.app.refreshes >= 2


def test_start_restores_the_previous_app_and_notes_a_steal(world, tmp_path):
    holder = existing_holder(world)
    holder.steals_on_tab = True
    host = host_for(world)
    start(host, tmp_path)
    assert world.restored == [USER_APP]
    assert world.front == USER_APP
    assert "focus_stolen=yes" in host.take_notes()


def test_a_steal_while_iterm_is_frontmost_is_noted_but_no_iterm_window_is_activated(world, tmp_path):
    holder = existing_holder(world)
    user = FakeWindow(world, "user-1", [FakeSession("u")])
    world.windows.append(user)
    world.front, world.current_window = ITERM_APP, "user-1"

    async def activate():
        raise AssertionError("an iTerm2 window was activated")
    user.async_activate = holder.async_activate = activate
    host = host_for(world)
    original = holder.async_create_tab

    async def create_tab(**kwargs):
        world.current_window = "holder-1"
        return await original(**kwargs)
    holder.async_create_tab = create_tab
    start(host, tmp_path)
    assert world.restored == []
    assert "focus_stolen=yes" in host.take_notes()


def test_holder_is_created_only_after_the_front_check_and_the_focus_is_restored(world, tmp_path):
    world.steal_on_create = True
    host = host_for(world)
    start(host, tmp_path)
    assert world.created_with_front == [USER_APP]
    kinds = [k for k, _ in world.log]
    assert kinds[kinds.index("create") - 1] == "front"
    assert world.restored == [USER_APP]
    notes = host.take_notes()
    assert notes[0] == "iterm-holder-created"
    assert f"iterm-focus {USER_APP}/- -> {ITERM_APP}/-" in notes
    assert "focus_stolen=yes" in notes
    holder = world.windows[0]
    assert holder.variables[HOLDER_VAR] == "1" and holder.tabs[0].sessions[0].variables[PLACEHOLDER_VAR] == "1"


def test_holder_creation_waits_while_iterm_is_frontmost(world, tmp_path, monkeypatch):
    polls = iter([ITERM_APP, ITERM_APP, ITERM_APP, USER_APP])
    original = iterm2.current_focus

    async def current_focus(app):
        world.front = next(polls, USER_APP)
        return await original(app)
    monkeypatch.setattr(iterm2, "current_focus", current_focus)
    host = host_for(world)
    start(host, tmp_path)
    assert world.created_with_front == [USER_APP]
    assert len(world.windows) == 1


def test_holder_creation_times_out_without_creating_a_window(world, tmp_path, monkeypatch):
    world.front = ITERM_APP
    monkeypatch.setattr(iterm2, "HOLDER_WAIT_S", 0.05)
    host = host_for(world)
    with pytest.raises(HolderBlocked) as caught:
        start(host, tmp_path)
    assert failure_note(caught.value) == "iterm-holder-blocked: iTerm2 frontmost"
    assert world.created_with_front == [] and world.windows == []


def test_a_holder_made_by_another_process_while_waiting_is_reused(world, tmp_path, monkeypatch):
    world.front = ITERM_APP
    original = iterm2.current_focus
    calls = []

    async def current_focus(app):
        calls.append(1)
        if len(calls) == 2:
            existing_holder(world)
        return await original(app)
    monkeypatch.setattr(iterm2, "current_focus", current_focus)
    start(host_for(world), tmp_path)
    assert world.created_with_front == []


def test_release_closes_cell_tabs_but_leaves_the_holder_and_user_windows(world):
    holder = existing_holder(world)
    cell = FakeSession("c1")
    holder.tabs.append(FakeTab([cell]))
    user_session = FakeSession("u1")
    user = FakeWindow(world, "w1", [user_session])
    world.windows.append(user)
    closed, stolen = run(iterm2.release_sessions(None, ["c1", "ph", "u1-not-asked"]))
    assert (closed, stolen) == (["c1"], False)
    assert cell.closed and not holder.closed and not user.closed and not user_session.closed


def test_release_reports_a_focus_steal(world):
    holder = existing_holder(world)
    holder.tabs.append(FakeTab([FakeSession("c1")]))
    original = holder.tabs[-1].sessions[0].async_close

    async def close(force=False):
        world.front = ITERM_APP
        await original(force)
    holder.tabs[-1].sessions[0].async_close = close
    closed, stolen = run(iterm2.release_sessions(None, ["c1"]))
    assert (closed, stolen) == (["c1"], True) and world.restored == [USER_APP]


def test_close_holder_waits_for_the_last_cell_tab_and_sees_fresh_state(world):
    holder = existing_holder(world)
    cell = FakeSession("c1")
    holder.tabs.append(FakeTab([cell]))
    assert "still has cell tabs" in run(iterm2.close_holder(None))[0]
    assert not holder.closed
    run(iterm2.release_sessions(None, ["c1"]))
    report = run(iterm2.close_holder(None))
    assert holder.closed and report[0] == "closed iTerm2 holder holder-1"


def test_close_holder_never_closes_a_window_without_the_variable(world):
    world.windows.append(FakeWindow(world, "w1", [FakeSession("u1")]))
    assert run(iterm2.close_holder(None)) == ["no iTerm2 holder window"]
    assert not world.windows[0].closed


def test_prepare_holder_creates_once_then_reports_existing(world):
    first = run(iterm2.prepare_holder(None))
    assert first[0] == "iTerm2 holder holder-new created"
    assert run(iterm2.prepare_holder(None))[0] == "iTerm2 holder holder-new already open"
    assert len(world.windows) == 1
