import json
import subprocess
from pathlib import Path

from agentcomms import isolation, manifest, procs, profiles, scoring
from agentcomms.adapters import ADAPTERS
from agentcomms.adapters.agent_deck import AgentDeck, ad_env, send_wrapper, session_entry
from agentcomms.adapters.bridge import AgentRoute
from agentcomms.adapters.claude_uds import ClaudeUdsAccept, ClaudeUdsChild
from agentcomms.adapters.csd import agent_shim, tmux_shim, without_flag
from agentcomms.adapters.gc_nudge import (
    city_socket,
    city_toml,
    registry_toml,
    session_name,
    supervisor_toml,
    unwrap_reminder,
)
from agentcomms.adapters.hcom import Hcom, cli_env, hcom_env, instance_for, unwrap_hcom
from agentcomms.adapters.intercom import (
    Intercom,
    IntercomAccept,
    codex_mcp_flags,
    pi_agent_dir,
    session_for,
    unwrap_intercom,
)
from agentcomms.cli import s9_split
from agentcomms.engine import bridge_launch, with_path
from agentcomms.model import Delivery, LaunchMods, Target
from agentcomms.paths import SOCKET_DIR
from agentcomms.procs import ProcRow
from agentcomms.scenarios.common import held_for
from agentcomms.scenarios.s9 import Pair, attribution, b_message, classify, instruction, is_reply, markers, route_for
from agentcomms.transcripts.claude import ClaudeTranscript, parse_record
from agentcomms.transcripts.codex import CodexTranscript

FIXTURES = Path(__file__).parent / "fixtures" / "s9"
RUN = "20261027-163503-da9c"
BODY = 'ACK-REQUEST 1d9d1d74: reply with exactly "ACK 1d9d1d74". relay test'


def work(tmp_path: Path, slot: str) -> Path:
    return tmp_path / "runs" / RUN / "work" / slot


def target(tmp_path: Path, agent: str, slot: str | None = None, pid: int | None = 4242) -> Target:
    run = tmp_path / "runs" / RUN
    return Target(run_id=RUN, agent=agent, host="tmux", backend="none", work_dir=run / "work" / (slot or agent),
                  home_dir=run / "home" / (slot or agent), session_id="sid-1", host_ref="agentcomms:x",
                  backend_ref=None, transcript=None, agent_pid=pid)


def test_bridges_are_registered_as_bridge_adapters():
    names = {"hcom", "intercom", "intercom-accept", "csd", "agent-deck", "agent-deck-composer-fallback", "gc-nudge"}
    assert names <= set(ADAPTERS)
    assert {ADAPTERS[n].kind for n in names} == {"bridge"}


def test_hcom_launch_runs_the_agent_through_hcom_with_run_state(tmp_path, fake_vendored):
    mods = Hcom().launch_mods("codex", work(tmp_path, "codex"), tmp_path)
    assert mods.launcher[1:] == ("codex",)
    assert mods.launcher[0].endswith("vendor/hcom/bin/hcom")
    assert mods.env == {"HCOM_DIR": str(tmp_path / "runs" / RUN / "hcom"),
                        "HCOM_TEST_ROOT": str(tmp_path / "runs" / RUN)}
    assert cli_env(work(tmp_path, "pi"))["HOME"] == hcom_env(work(tmp_path, "pi"))["HCOM_DIR"]


def test_hcom_unwrap_strips_both_arrow_styles_and_hints():
    assert unwrap_hcom(f"<hcom>[new message #3] bigboss → kare: {BODY}</hcom>") == BODY
    assert unwrap_hcom(f"<hcom>[new message #3] bigboss -> kula: {BODY}</hcom>") == BODY
    assert unwrap_hcom(f"[inform #6] kimo → pogo: {BODY} | [respond in JSON]") == BODY


def test_hcom_instance_is_found_by_work_dir():
    entries = [{"name": "kare", "directory": "/r/work/claude"}, {"name": "zola", "directory": "/r/work/codex/"}]
    assert instance_for(entries, Path("/r/work/codex"))["name"] == "zola"


def test_bridge_launch_appends_agent_args_or_moves_them_into_the_shim():
    tui = ["/bin/claude", "--session-id", "s", "--model", "haiku"]
    hcom = LaunchMods(host="tmux", launcher=("hcom", "claude"))
    assert bridge_launch(hcom, tui, ["/bin/claude"]) == (["hcom", "claude", "--session-id", "s", "--model", "haiku"],
                                                         ["/bin/claude"])
    cci = LaunchMods(host="tmux", launcher=("node", "cci.mjs", "--tui"), args_in_shim=True)
    assert bridge_launch(cci, tui, ["/bin/claude"]) == (["node", "cci.mjs", "--tui"], tui)
    assert profiles.shim_script(["/bin/claude", "--model", "haiku"]) == \
        '#!/bin/sh\nexec /bin/claude --model haiku "$@"\n'
    assert with_path({"PATH": "/usr/bin"}, ("/shim",)) == {"PATH": "/shim:/usr/bin"}


def test_claude_reader_reads_hook_context_as_a_received_entry():
    record = {"type": "attachment", "timestamp": "2026-10-27T15:21:15.639Z",
              "attachment": {"type": "hook_additional_context", "content": ["<hcom>hi</hcom>"]}}
    assert parse_record(record)[0][1:] == ("hook", "<hcom>hi</hcom>")
    shown = {"type": "attachment", "attachment": {"type": "hook_system_message", "content": "shown to the user"}}
    assert parse_record(shown)[0][1:] == ("system", "shown to the user")


def test_codex_reader_reads_developer_hook_context_as_hook():
    entries = CodexTranscript(FIXTURES / "hcom-codex-b.jsonl").entries()
    assert next(k for _, k, t in entries if "1d9d1d74" in t) == "hook"


def test_intercom_unwraps_pi_coi_and_native_frames():
    pi = f"**📨 From pi-a** (/r/work/pi-a)\n\nTo reply, use: intercom_send({{ to: \"pi-a\" }})\n\n{BODY}"
    coi = f"Intercom message for codex.\nFrom: pi (id)\nMessage id: m\n\n{BODY}\n\n\n"
    native = ('Another Claude session sent a message:\n<cross-session-message from="uds:/s" from-name="c">\n'
              f"[Intercom message from pi (id)]\n{BODY}\n\n\nAct if needed. To acknowledge, use SendMessage.\n"
              "</cross-session-message>\n\nThis came from another Claude session — not typed by your user.")
    assert unwrap_intercom(pi) == BODY
    assert unwrap_intercom(coi) == BODY
    assert unwrap_intercom(native) == BODY


def test_intercom_launches_keep_sockets_short_and_state_in_the_run(tmp_path, fake_vendored, fake_pinned):
    pi = Intercom().launch_mods("pi", work(tmp_path, "pi"), tmp_path)
    assert pi.env["PI_CODING_AGENT_DIR"] == str(SOCKET_DIR / f"{RUN}-pih-pi")
    assert len(str(pi_agent_dir(work(tmp_path, "pi")) / "intercom" / "remote-gateway.sock")) < 104
    claude = IntercomAccept().launch_mods("claude", work(tmp_path, "claude"), tmp_path)
    assert claude.args_in_shim and claude.launcher[2:5] == ("--tui", "--transport", "native")
    assert claude.extra_args == ("--settings", '{"crossSessionInbound": "accept"}')
    assert claude.env["PI_CODING_AGENT_DIR"] == str(SOCKET_DIR / f"{RUN}-ic")
    codex = Intercom().launch_mods("codex", work(tmp_path, "codex"), tmp_path)
    assert codex.backend == "codex-app-server"
    assert f'mcp_servers.codex-intercom.env.PI_CODING_AGENT_DIR="{SOCKET_DIR / f"{RUN}-ic"}"' in \
        codex_mcp_flags("/node", work(tmp_path, "codex"))


def test_intercom_session_is_found_by_cwd():
    assert session_for([{"name": "a", "cwd": "/w/a"}, {"name": "b", "cwd": "/w/b"}], Path("/w/b"))["name"] == "b"


def test_csd_shims_route_tmux_to_the_harness_server_and_drop_the_assigned_session_id():
    assert without_flag(["sops", "claude", "--session-id", "x", "--model", "haiku"], "--session-id") == \
        ["sops", "claude", "--model", "haiku"]
    assert " -L agentcomms -f /repo/tmux.conf \"$@\"" in tmux_shim(Path("/repo/tmux.conf"))
    assert agent_shim(["/usr/bin/env", "-i", "A=1", "claude"]).endswith('exec /usr/bin/env -i A=1 claude "$@"\n')


def test_agent_deck_runs_with_an_isolated_home_and_the_tool_home(tmp_path):
    env = ad_env(work(tmp_path, "codex"), {"CODEX_HOME": "/h/codex", "OPENCODE_PASSWORD": "x"})
    assert env["HOME"] == str(tmp_path / "runs" / RUN / "ad-home")
    assert env["CODEX_HOME"] == "/h/codex"
    assert env["XDG_CONFIG_HOME"].startswith(env["HOME"])
    wrapper = send_wrapper(work(tmp_path, "codex"), "title", {}, ("--codex-composer-fallback",))
    assert "session send title --message-file - --json --codex-composer-fallback" in wrapper
    listing = json.dumps({"sessions": [{"title": "t", "tmux_session": "agentdeck_t_1"}]})
    assert session_entry(listing, "t")["tmux_session"] == "agentdeck_t_1"


def test_gc_city_uses_its_own_tmux_server_file_beads_and_its_own_supervisor_port(tmp_path):
    toml = city_toml(work(tmp_path, "claude"), Path("/shim"), "2.1.311")
    assert city_socket(work(tmp_path, "claude")) == f"agentcomms-{RUN}-claude"
    assert f'socket = "agentcomms-{RUN}-claude"' in toml and 'provider = "file"' in toml and 'command = "/shim"' in toml
    assert 'mode = "always"' in toml
    assert registry_toml(work(tmp_path, "claude")).startswith("[[cities]]\npath = ")
    assert supervisor_toml(41234) == '[supervisor]\nport = 41234\nbind = "127.0.0.1"\n'
    listing = json.dumps([{"alias": "recv-da9c", "session_name": "recv-da9c"}])
    assert session_name(listing, "recv-da9c") == "recv-da9c"
    framed = ("<system-reminder>\nYou have a deferred reminder that was queued until a safe boundary:\n\n"
              f"- [session] {BODY}\n\nHandle them after this turn.\n</system-reminder>\n")
    assert unwrap_reminder(framed) == BODY
    assert unwrap_reminder(framed.replace("<", "&lt;").replace(">", "&gt;")) == BODY


def test_claude_peers_reach_each_other_with_send_message(tmp_path):
    home = tmp_path / "runs" / RUN / "home" / "claude"
    (home / "sessions").mkdir(parents=True)
    (home / "sessions" / "4242.json").write_text(json.dumps({"messagingSocketPath": "/tmp/cc-socks/4242.sock"}))
    route = route_for(ClaudeUdsAccept(), target(tmp_path, "claude"), "claude")
    assert (route.tool, route.address) == ("SendMessage", "uds:/tmp/cc-socks/4242.sock")
    child = route_for(ClaudeUdsChild(), target(tmp_path, "claude"), "claude")
    assert child.tool is None and child.command[-2:] == ["--socket", f"/tmp/ac/{RUN}-relay.sock"]


def test_s9_instructions_use_a_body_file_for_commands_and_quote_tool_text(tmp_path):
    command = AgentRoute("name", "mode", ("mode",), command=["hcom", "send", "@mode"])
    assert instruction(command, tmp_path / "to-b.txt", "x") == \
        f"run this shell command exactly once: hcom send @mode < {tmp_path / 'to-b.txt'}"
    tool = AgentRoute("address", "uds:/s", (), tool="SendMessage")
    assert instruction(tool, tmp_path / "f", "ACK 1") == \
        'use your SendMessage tool exactly once to send the text between « and » unchanged to "uds:/s": «ACK 1»'
    message = b_message("1d9d1d74", command, tmp_path / "reply.txt")
    assert message.startswith('ACK-REQUEST 1d9d1d74: reply with exactly "ACK 1d9d1d74".')
    assert message.endswith(f"hcom send @mode < {tmp_path / 'reply.txt'}.")


def test_s9_round_trip_classified_from_real_transcripts():
    a = ClaudeTranscript(FIXTURES / "hcom-claude-a.jsonl").entries()
    b = CodexTranscript(FIXTURES / "hcom-codex-b.jsonl").entries()
    verdict = classify(a, b, "1d9d1d74", markers(Path("to-b.txt"), "1d9d1d74"),
                       markers(Path("reply-1d9d1d74.txt"), "ACK 1d9d1d74"))
    assert (verdict.delivery, verdict.roundtrip, verdict.a_sent, verdict.b_replied) == (Delivery.DELIVERED, True,
                                                                                         True, True)
    assert verdict.a_reply[1] == "hook"
    assert attribution(verdict.b_seen[2], unwrap_hcom(verdict.b_seen[2]), ("zola",)) == "mechanism"


def test_s9_without_a_reply_is_delivered_but_not_a_round_trip():
    b = [(1.0, "user", f"framed: {BODY}"), (2.0, "assistant", "ACK 1d9d1d74")]
    verdict = classify([(0.5, "tool_use", "send < to-b.txt")], b, "1d9d1d74", ("to-b.txt",), ("reply",))
    assert (verdict.delivery, verdict.roundtrip, verdict.b_replied) == (Delivery.DELIVERED, False, False)


def test_s9_held_lost_and_unsent_forward_legs():
    held = classify([(0.5, "tool_use", "to-b.txt")], [(2.0, "held", "Held peer message — preview")], "t1",
                    ("to-b.txt",), ("r",), sent_at=1.0)
    assert held.delivery == Delivery.HELD
    lost = classify([(0.5, "tool_use", "to-b.txt")], [], "t1", ("to-b.txt",), ("r",))
    assert lost.delivery == Delivery.LOST
    unsent = classify([(0.5, "assistant", "I could not find the tool")], [], "t1", ("to-b.txt",), ("r",))
    assert unsent.delivery == Delivery.ERROR


def test_s9_reply_detection_ignores_the_echoed_request():
    assert is_reply("<hcom>mode → zola: ACK 1d9d1d74</hcom>", "1d9d1d74")
    assert not is_reply(BODY, "1d9d1d74")


def test_s9_attribution_separates_mechanism_frames_from_message_text():
    assert attribution(f"[new message] zola → mode: {BODY}", BODY, ("zola",)) == "mechanism"
    assert attribution(f"{BODY} reply to sid-a", f"{BODY} reply to sid-a", ("sid-a",)) == "message"
    assert attribution(BODY, BODY, ("zola",)) == "none"


def test_s9_pairs_label_slots_and_split_runs_only_for_unshared_state():
    same = Pair("claude", "claude", "csd", "csd")
    assert (same.mechanism, same.labels()) == ("csd", ("claude-a", "claude-b"))
    assert Pair("claude", "codex", "codex-queue", "claude-uds-accept").mechanism == "codex-queue+claude-uds-accept"
    assert s9_split("pi", "pi", shared_run=False)
    assert s9_split("pi", "pi", shared_run=True) is False
    assert s9_split("pi", "codex", shared_run=False) is False


def test_s9_scores_only_round_trips():
    base = {"scenario": "S9", "delivery": "delivered", "harmful": False}
    assert scoring.is_good(base | {"notes": "pair=a>b; roundtrip=yes"})
    assert not scoring.is_good(base | {"notes": "pair=a>b; roundtrip=no"})


def test_a_held_entry_after_the_send_counts_even_without_the_token():
    assert held_for([(5.0, "held", "preview without token")], "t1", sent_at=4.0)
    assert held_for([(3.0, "held", "old t1 message")], "t1", sent_at=4.0)


def test_cleanup_removes_run_links_into_the_run(tmp_path):
    run_dir = tmp_path / "runs" / RUN
    (run_dir / "ic").mkdir(parents=True)
    sockets = tmp_path / "ac"
    sockets.mkdir()
    (sockets / f"{RUN}-ic").symlink_to(run_dir / "ic")
    (sockets / "other-ic").symlink_to(run_dir / "ic")
    (tmp_path / "elsewhere").mkdir()
    (sockets / f"{RUN}-pih-x").symlink_to(tmp_path / "elsewhere")
    removed = manifest.remove_run_socket_dirs(RUN, sockets, run_dir)
    assert removed == [f"removed link {sockets / f'{RUN}-ic'}"]
    assert (sockets / "other-ic").is_symlink()
    assert (sockets / f"{RUN}-pih-x").is_symlink()


def test_vendored_bridge_processes_are_cleanup_candidates(tmp_path):
    vendor = tmp_path / "vendor"
    rows = [ProcRow(10, 1, 10, f"{vendor.resolve()}/agent-deck/bin/agent-deck session send"),
            ProcRow(11, 1, 11, "/usr/bin/agent-deck")]
    assert procs.vendored(rows, vendor) == {10}


def test_bridge_delta_stops_on_any_watched_change_and_only_measures_growing_supervisor_logs():
    home = "/Users/u"
    before = {f"{home}/.gc/events.jsonl": (100, 1.0), f"{home}/.gc/supervisor.log": (50, 1.0),
              f"{home}/.gc/settings.json": (10, 1.0)}
    after = {f"{home}/.gc/events.jsonl": (160, 2.0), f"{home}/.gc/supervisor.log": (40, 2.0),
             f"{home}/.gc/settings.json": (10, 1.0), f"{home}/.gc/nudges/n.json": (5, 2.0)}
    delta = isolation.bridge_delta(before, after, home)
    assert delta.appends == [(f"{home}/.gc/events.jsonl", 60)]
    assert delta.stops == [f"{home}/.gc/nudges/n.json", f"{home}/.gc/supervisor.log"]


def test_agent_deck_offers_its_send_wrapper_once_written(tmp_path):
    t = target(tmp_path, "claude")
    script = tmp_path / "runs" / RUN / "ad-home" / "send-claude"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\n")
    assert AgentDeck().sender_argv(t) == [str(script)]


def test_bridges_that_paste_into_claude_unwrap_its_paste_reference():
    from agentcomms.adapters.agent_deck import AgentDeck
    from agentcomms.adapters.csd import Csd
    from agentcomms.adapters.gc_nudge import GcNudge
    body = 'ACK-REQUEST 3b2d0c8d: reply with exactly "ACK 3b2d0c8d". Payload\nL0001 line\n'
    pasted = f'<pasted_content id="041d">\n{body}\n</pasted_content id="041d">'
    reminder = ("<system-reminder>\nYou have a deferred reminder that was queued until a safe boundary:\n\n"
                f"- [session] {body}\n\nHandle them after this turn.\n</system-reminder>")
    assert Csd().unwrap(pasted) == body
    assert AgentDeck().unwrap(pasted) == body
    assert GcNudge().unwrap(f'<pasted_content id="a14d">\n{reminder}\n</pasted_content id="a14d">') == body
    assert GcNudge().unwrap(reminder) == body


def test_bridge_scenarios_that_do_not_apply_are_named_per_adapter():
    from agentcomms.adapters import ADAPTERS
    from agentcomms.scenarios import cell_not_applicable

    def na(adapter, agent, scenario, backend="none"):
        return cell_not_applicable(scenario, agent, backend, ADAPTERS[adapter](None))

    assert all(na(name, "claude", "S6").startswith("not measured: the bridge owns the session lifecycle")
               for name in ("csd", "agent-deck", "gc-nudge"))
    assert na("intercom-accept", "claude", "S3").startswith("cci launches Claude with --yolo")
    assert na("intercom", "codex", "S3", "codex-app-server") is None
    assert na("hcom", "pi", "S12").startswith("no backing daemon: hcom")
    assert na("gc-nudge", "droid", "S12") is None
    assert na("intercom", "pi", "S12") is None
    assert na("claude-channel", "claude", "S12").startswith("no separate server")
    assert na("tmux-paste", "pi", "S12") == "no backing server (backend none)"
    assert na("pi-ext", "pi", "S3") == "pi has no approval prompts"
    assert na("hcom", "claude", "S6") is None
    assert na("csd", "claude", "S3").startswith("csd launches Claude with --dangerously-skip-permissions")
    assert na("intercom", "codex", "S6").startswith("not measured: coi wraps the Codex TUI")
    assert na("intercom", "pi", "S6") is None
    assert na("gc-nudge", "codex", "S3").startswith("not measured: gc's startup beacon")


def test_bridge_daemon_restart_refuses_a_pid_the_run_does_not_track(tmp_path):
    import os

    import pytest

    from agentcomms.adapters.bridge import require_owned_daemon
    from agentcomms.backends import BackendError

    (tmp_path / "manifest.json").write_text('{"backends": [], "identities": {}}')
    with pytest.raises(BackendError, match="not a live tracked bridge daemon"):
        require_owned_daemon(tmp_path, os.getpid(), "intercom broker")
    with pytest.raises(BackendError, match="not a live tracked bridge daemon"):
        require_owned_daemon(tmp_path, None, "gc supervisor")


def test_stopping_a_bridge_daemon_child_reaps_it():
    from agentcomms.adapters.bridge import stop_pid
    proc = subprocess.Popen(["/bin/sleep", "30"], start_new_session=True)
    try:
        stop_pid(proc.pid, group=True, grace_s=2.0)
        assert procs.alive(proc.pid) is False
    finally:
        proc.kill()
