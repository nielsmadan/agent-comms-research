from pathlib import Path

import pytest

from agentcomms import procs
from agentcomms.adapters import ADAPTERS, adapter_host, make_adapter
from agentcomms.hosts import iterm2, state_dir_for, zellij, zmx
from agentcomms.hosts.keys import key_bytes

BIN = Path("/v/bin/tool")
STATE = Path("/tmp/ac/r1-zmx")


def test_key_bytes_named_and_literal():
    assert (key_bytes("Enter"), key_bytes("Escape"), key_bytes("Down"), key_bytes("y")) == (
        b"\r", b"\x1b", b"\x1b[B", b"y")
    with pytest.raises(KeyError):
        key_bytes("F13")


def test_zmx_ref_roundtrip_and_rejects_foreign_refs():
    ref = zmx.make_ref(STATE, "r1-claude")
    assert ref == "zmx:/tmp/ac/r1-zmx:r1-claude"
    assert zmx.split_ref(ref) == (STATE, "r1-claude")
    with pytest.raises(zmx.ZmxError):
        zmx.split_ref("agentcomms:r1-claude")


def test_zmx_command_builders():
    assert zmx.attach_argv(BIN, "n", ["env", "-i", "A=1", "agent"]) == [str(BIN), "attach", "n", "env", "-i", "A=1",
                                                                       "agent"]
    assert zmx.send_argv(BIN, "n", "hi;") == [str(BIN), "send", "n", "hi;"]
    assert zmx.history_argv(BIN, "n") == [str(BIN), "history", "n"]
    assert zmx.tail_argv(BIN, "n") == [str(BIN), "tail", "n"]
    assert zmx.kill_argv(BIN, "n") == [str(BIN), "kill", "n", "--force"]


def test_zmx_env_isolates_socket_log_and_home_dirs():
    env = zmx.zmx_env(STATE)
    assert env["ZMX_DIR"] == str(STATE)
    assert env["XDG_STATE_HOME"] == str(STATE / "state")
    assert env["HOME"] == str(STATE / "home")


def test_zmx_parse_ls_rows():
    out = "  name=a\tpid=12\tclients=0\tcwd=file://h/tmp\n  name=b\tpid=13\tclients=1\tcmd=sh -c 'x y'\n"
    rows = zmx.parse_ls(out)
    assert rows["a"]["pid"] == "12"
    assert rows["b"]["cmd"] == "sh -c 'x y'"


def test_zellij_command_builders():
    assert zellij.create_argv(BIN, "n", ["agent", "-x"]) == [str(BIN), "attach", "--create-background", "n", "--",
                                                              "agent", "-x"]
    assert zellij.write_chars_argv(BIN, "n", "hi") == [str(BIN), "--session", "n", "action", "write-chars",
                                                       "--pane-id", "terminal_0", "--", "hi"]
    assert zellij.write_bytes_argv(BIN, "n", b"\x1b[B") == [str(BIN), "--session", "n", "action", "write",
                                                            "--pane-id", "terminal_0", "27", "91", "66"]
    assert zellij.paste_argv(BIN, "n", "a\nb")[-4:] == ["--pane-id", "terminal_0", "--", "a\nb"]
    assert zellij.write_chars_argv(BIN, "n", "- item")[-2:] == ["--", "- item"]
    assert zellij.dump_argv(BIN, "n")[-3:] == ["dump-screen", "--pane-id", "terminal_0"]


def test_zellij_env_keeps_everything_under_the_state_dir():
    state = Path("/tmp/ac/r1-zj")
    env = zellij.zellij_env(state)
    assert env["HOME"] == "/tmp/ac/r1-zj/home"
    assert env["ZELLIJ_CONFIG_DIR"] == "/tmp/ac/r1-zj/config"
    assert env["ZELLIJ_SOCKET_DIR"] == "/tmp/ac/r1-zj/s"


def test_zellij_terminal_pane_ignores_plugin_panes_and_reports_exit():
    listing = '[{"id": 0, "is_plugin": true, "exited": false}, {"id": 0, "is_plugin": false, "exited": true}]'
    pane = zellij.terminal_pane(listing)
    assert pane is not None and pane["exited"] is True
    assert zellij.terminal_pane("not json") is None


def test_zellij_server_pid_matches_the_session_socket():
    rows = [procs.ProcRow(7, 1, 7, f"{BIN} --server /tmp/ac/r1-zj/s/contract_version_1/other"),
            procs.ProcRow(9, 1, 7, f"{BIN} --server /tmp/ac/r1-zj/s/contract_version_1/r1-claude")]
    assert zellij.server_pid(rows, Path("/tmp/ac/r1-zj"), "r1-claude") == 9


def test_state_dirs_are_per_run_and_short():
    root = Path("/tmp/ac")
    assert state_dir_for("zmx", "20261027-132447-ab2e", root) == root / "20261027-132447-ab2e-zmx"
    assert state_dir_for("zellij", "20261027-132447-ab2e", root) == root / "20261027-132447-ab2e-zj"
    assert state_dir_for("tmux", "r", root) is None
    longest = root / "20261027-132447-ab2e-zj" / "s" / "contract_version_1" / "20261027-132447-ab2e-hc-zellij"
    assert len(str(longest)) < 104


def test_iterm_helpers():
    assert iterm2.session_id("iterm2:ABC") == "ABC"
    with pytest.raises(iterm2.ItermError):
        iterm2.session_id("zmx:/x:y")
    assert iterm2.command_line(["/usr/bin/env", "-i", "A=b c", "agent"]) == "/usr/bin/env -i 'A=b c' agent"
    assert iterm2.screen_text(["a  ", "b", "", ""]) == "a\nb\n"


def test_each_non_tmux_host_has_a_typed_and_a_paste_terminal_adapter():
    by_host = {}
    for name in ADAPTERS:
        by_host.setdefault(adapter_host(name), []).append(name)
    assert by_host["zmx"] == ["zmx-send", "zmx-paste"]
    assert by_host["zellij"] == ["zellij-write", "zellij-paste"]
    assert by_host["iterm2"] == ["iterm2-text", "iterm2-paste"]
    assert {"tmux-keys", "tmux-paste", "tmux-paste-retry", "tmux-buffer"} <= set(by_host["tmux"])


def test_make_adapter_picks_the_host_of_its_kind():
    asked = []

    def host_for(kind):
        asked.append(kind)
        return object()

    make_adapter("zellij-paste", host_for)
    make_adapter("tmux-buffer", host_for)
    assert asked == ["zellij", "tmux"]


def rows(*specs: tuple[int, int, int]) -> list[procs.ProcRow]:
    return [procs.ProcRow(pid, ppid, pgid, "x") for pid, ppid, pgid in specs]


def test_owned_group_is_the_roots_group_when_only_its_tree_is_in_it():
    assert procs.owned_group(rows((9, 1, 7), (11, 9, 11)), 9) == 7


def test_owned_group_falls_back_to_the_root_pid_when_the_group_is_shared():
    assert procs.owned_group(rows((9, 1, 7), (5, 1, 7)), 9) == 9


def test_owned_group_for_a_group_leader_is_its_own_pid():
    assert procs.owned_group(rows((9, 1, 9), (11, 9, 11)), 9) == 9


def test_zmx_and_zellij_attach_a_client_to_the_existing_session_in_the_host_env(monkeypatch, tmp_path):
    spawned = []

    def spawn(argv, cwd, env, rows, cols, log):
        spawned.append((argv, env, rows, cols, log))
        return "client"

    monkeypatch.setattr(zmx, "spawn_in_pty", spawn)
    monkeypatch.setattr(zellij, "spawn_in_pty", spawn)
    log = tmp_path / "attach-claude.log"
    zj_state = Path("/tmp/ac/r1-zj")
    assert zmx.ZmxHost(BIN).attach_client(zmx.make_ref(STATE, "r1-claude"), log, tmp_path, {}) == "client"
    assert zellij.ZellijHost(BIN).attach_client(zellij.make_ref(zj_state, "r1-claude"), log, tmp_path, {}) == "client"
    assert spawned == [([str(BIN), "attach", "r1-claude"], zmx.zmx_env(STATE), 50, 200, log),
                       ([str(BIN), "attach", "r1-claude"], zellij.zellij_env(zj_state), 50, 200, log)]
