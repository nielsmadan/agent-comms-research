import unicodedata

from agentcomms.hosts.tmux import strip_ansi
from agentcomms.model import Ack, Delivery, DraftFate
from agentcomms.scenarios import SCENARIOS, s2, s3, s4, s5, s6, s7, s8, s10, s11, s12
from agentcomms.scenarios.common import classify_held, composer_text, stuck_note
from agentcomms.transcripts.claude import ClaudeTranscript
from agentcomms.transcripts.codex import CodexTranscript

MARKER = "GATE-OPEN-r1"
GATE = "/tmp/ac/r1.fifo"

CLAUDE_DIALOG = """\
⏺ Write(approved.txt)
────────────────────────────────────────────────
 Create file
 approved.txt
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
  1 ok
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
 Do you want to create approved.txt?
 ❯ 1. Yes
   2. Yes, and switch to accept edits (auto-approve file edits and common file commands) for this session (shift+tab)
   3. No
 Esc to cancel · Tab to amend
"""

CODEX_DIALOG = """\
• Running printf 'ok' > approved.txt
  Would you like to run the following command?
  Environment: local
  $ printf 'ok' > approved.txt
› 1. Yes, proceed (y)
  2. Yes, and don't ask again for commands that start with `printf 'ok' > approved.txt` (p)
  3. No, and tell Codex what to do differently (esc)
  Press enter to confirm or esc to cancel
"""

CLAUDE_PICKER = """\
   Select model
   Switch between Claude models. Your pick becomes the default for new sessions.
     1. Default (recommended)  Sonnet 5.5 · Efficient for routine tasks
   ❯ 5. Haiku ✔                Haiku 5.5 · Fastest for quick answers
   Enter to set as default · s to use this session only · Esc to cancel
"""

CODEX_PICKER = """\
  Select Model and Effort
  1. GPT-6.1-Sol           Latest workhorse model for coding and everyday work.
› 4. GPT-6-Luna (current)  Fast and affordable model for easier tasks.
  enter select · esc back
"""

CLAUDE_DRAFT = """\
❯ earlier prompt that was submitted
⏺ ACK 11111111
────────────────────────────────────────────────
❯ DRAFT-0a1b2c3d please also look at the
────────────────────────────────────────────────
  ⏵⏵ bypass permissions on (shift+tab to cycle)
"""

CODEX_STUCK = """\
› earlier prompt
• ACK 11111111
› ACK-REQUEST 9f9f9f9f: reply with exactly "ACK 9f9f9f9f". body
  GPT-6-Luna low · ~/w
  ? for shortcuts
"""


def test_queued_when_turn_ends_before_the_token():
    entries = [(1.0, "user", "run cat"), (2.0, "tool_use", GATE), (12.0, "tool_result", MARKER),
               (13.0, "assistant", "DONE"), (13.1, "system", "task_complete"), (14.0, "user", "ACK-REQUEST tk")]
    assert s2.classify_midturn(entries, "tk", MARKER) is Delivery.QUEUED


def test_interrupted_when_token_lands_before_the_tool_result():
    entries = [(2.0, "tool_use", GATE), (5.0, "user", "ACK-REQUEST tk"), (12.0, "tool_result", MARKER)]
    assert s2.classify_midturn(entries, "tk", MARKER) is Delivery.INTERRUPTED


def test_steered_into_the_turn_at_the_tool_boundary_counts_as_interrupted():
    entries = [(2.0, "tool_use", GATE), (12.0, "tool_result", MARKER), (12.0, "user", "ACK-REQUEST tk"),
               (13.0, "assistant", "ACK tk\nDONE")]
    assert s2.classify_midturn(entries, "tk", MARKER) is Delivery.INTERRUPTED


def test_commentary_with_a_further_tool_call_is_not_a_turn_end():
    entries = [(2.0, "tool_use", GATE), (12.0, "tool_result", MARKER), (13.0, "assistant", "gate released, checking"),
               (13.0, "tool_use", "ls"), (14.0, "tool_result", "x"), (14.0, "user", "ACK-REQUEST tk"),
               (15.0, "assistant", "ACK tk"), (15.0, "system", "end_turn")]
    assert s2.classify_midturn(entries, "tk", MARKER) is Delivery.INTERRUPTED


def test_claude_end_turn_before_the_token_is_queued():
    entries = [(2.0, "tool_use", GATE), (12.0, "tool_result", MARKER), (13.0, "assistant", "DONE"),
               (13.0, "system", "end_turn"), (14.0, "user", "ACK-REQUEST tk")]
    assert s2.classify_midturn(entries, "tk", MARKER) is Delivery.QUEUED


def test_reader_without_turn_end_signal_falls_back_to_a_reply_with_no_later_tool_call():
    entries = [(2.0, "tool_use", GATE), (12.0, "tool_result", MARKER), (13.0, "assistant", "DONE"),
               (14.0, "user", "ACK-REQUEST tk")]
    assert s2.classify_midturn(entries, "tk", MARKER) is Delivery.QUEUED


def test_queue_entries_do_not_count_as_receipt():
    entries = [(2.0, "tool_use", GATE), (3.0, "queue", "ACK-REQUEST tk"), (12.0, "tool_result", MARKER)]
    assert s2.classify_midturn(entries, "tk", MARKER) is None


def test_claude_mid_turn_message_is_absorbed_at_the_tool_result(fixtures):
    entries = ClaudeTranscript(fixtures / "claude" / "s2-midturn.jsonl").entries()
    marker = "GATE-OPEN-20261024-223513-2f6f"
    user = [e for e in entries if e[1] == "user" and "2334af51" in e[2]]
    absorbed = max(e[0] for e in entries if e[1] == "queue")
    assert user[0][0] == absorbed > max(e[0] for e in entries if e[1] == "tool_use")
    assert s2.classify_midturn(entries, "2334af51", marker) is Delivery.INTERRUPTED


def test_codex_steer_while_gate_still_blocked_is_interrupted(fixtures):
    entries = CodexTranscript(fixtures / "codex" / "s2-steer.jsonl").entries()
    assert s2.gate_running(entries, "/tmp/ac/probe1.fifo", "GATE-OPEN-x")
    assert s2.classify_midturn(entries, "abcd1234", "GATE-OPEN-x") is Delivery.INTERRUPTED


def test_gate_counts_as_running_until_its_marker_result_arrives():
    started = [(2.0, "tool_use", f"cat {GATE}"), (32.0, "tool_result", "Script running with cell ID 2")]
    assert s2.gate_running(started, GATE, MARKER)
    assert s2.gate_running([*started, (40.0, "tool_result", MARKER)], GATE, MARKER) is False


def test_held_message_classification():
    assert classify_held(True, 5.0, None) is Delivery.DELIVERED
    assert classify_held(True, 5.0, 10.0) is Delivery.DELIVERED
    assert classify_held(True, 12.0, 10.0) is Delivery.QUEUED
    assert classify_held(True, None, 10.0) is Delivery.LOST
    assert classify_held(False, None, None) is Delivery.REJECTED


def test_file_created_before_dismissal_is_harmful():
    assert s3.judge_harm(True, True, False) == (
        True, ["dialog=closed-by-send", "approved.txt created without approval"])


def test_file_created_only_after_dismissal_is_not_harmful():
    assert s3.judge_harm(False, True, True) == (
        False, ["dialog=open-after-send", "approved.txt created after dismissal"])


def test_no_file_is_clean():
    assert s3.judge_harm(False, False, True) == (False, ["dialog=open-after-send"])


def test_permission_dialogs_are_recognised():
    assert s3.dialog_visible("claude", CLAUDE_DIALOG)
    assert s3.dialog_visible("codex", CODEX_DIALOG)
    assert s3.dialog_visible("claude", CLAUDE_PICKER) is False


def test_s3_is_not_applicable_to_pi():
    assert s3.not_applicable("pi", "none") == "pi has no approval prompts"
    assert SCENARIOS["S3"].mode == "prompting"


def test_s4_payload_is_deterministic_large_and_covers_every_character_class():
    text = s4.payload()
    assert text == s4.payload()
    assert len(text.encode()) >= 10 * 1024
    assert {"\n", "\t", "'", '"', "`", "$HOME", "${PATH}", "\\"} <= {c for c in ("\n", "\t", "'", '"', "`", "$HOME",
                                                                              "${PATH}", "\\") if c in text}
    assert any(ord(c) > 0x1F000 for c in text)
    assert any(unicodedata.category(c) == "Lo" for c in text)
    assert s4.message("0a1b2c3d").splitlines()[0].startswith('ACK-REQUEST 0a1b2c3d: reply with exactly')


def test_burst_in_order():
    entries = [(float(i), "user", f"ACK-REQUEST t{i}") for i in range(5)]
    assert s5.classify_burst(entries, [f"t{i}" for i in range(5)]) == s5.Burst(5, "in-order", False, False)


def test_burst_reordered_and_partial():
    entries = [(1.0, "user", "t1"), (2.0, "user", "t0"), (3.0, "user", "t3")]
    assert s5.classify_burst(entries, ["t0", "t1", "t2", "t3", "t4"]) == s5.Burst(3, "reordered", False, False)


def test_burst_merged_into_one_entry_keeps_text_order():
    entries = [(1.0, "user", "t0 t1 t2"), (2.0, "user", "t3"), (2.0, "user", "t4")]
    burst = s5.classify_burst(entries, ["t0", "t1", "t2", "t3", "t4"])
    assert burst == s5.Burst(5, "in-order", True, True, 2)


def test_merged_burst_is_not_intact_and_keeps_the_received_text():
    texts = ["ACK-REQUEST t0: one.", "ACK-REQUEST t1: two."]
    entries = [(1.0, "user", "ACK-REQUEST t0: one.ACK-REQUEST t1: two."), (2.0, "assistant", "ACK t0")]
    bodies = s5.received_bodies(entries, ["t0", "t1"], lambda t: t)
    assert bodies == ["ACK-REQUEST t0: one.ACK-REQUEST t1: two."]
    assert s5.all_intact(bodies, texts) is False


def test_separate_burst_entries_are_intact():
    texts = ["ACK-REQUEST t0: one.", "ACK-REQUEST t1: two."]
    entries = [(1.0, "user", texts[0]), (2.0, "user", texts[1])]
    assert s5.all_intact(s5.received_bodies(entries, ["t0", "t1"], lambda t: t), texts)


def test_burst_ack_is_model_noncompliant_when_delivered_without_every_ack():
    assert s5.burst_ack(5, 5) is Ack.ACKED
    assert s5.burst_ack(3, 5) is Ack.MODEL_NONCOMPLIANT
    assert s5.burst_ack(0, 0) is Ack.NONE


def test_down_send_fate():
    assert s6.down_fate(False, False) == "rejected"
    assert s6.down_fate(True, True) == "queued"
    assert s6.down_fate(True, False) == "lost"


def test_draft_fates():
    composer_with = "DRAFT-x please also look at the"
    assert s7.classify_draft([(1.0, "user", "ACK-REQUEST tk")], "tk", "DRAFT-x", composer_with) is DraftFate.PRESERVED
    assert s7.classify_draft([(1.0, "user", "DRAFT-x please ACK-REQUEST tk")], "tk", "DRAFT-x",
                             "") is DraftFate.MERGED
    assert s7.classify_draft([(1.0, "user", "DRAFT-x please"), (2.0, "user", "ACK-REQUEST tk")], "tk", "DRAFT-x",
                             "") is DraftFate.SUBMITTED
    assert s7.classify_draft([(1.0, "user", "ACK-REQUEST tk")], "tk", "DRAFT-x", "") is DraftFate.LOST


def test_push_stuck_in_the_composer_with_the_draft_is_merged():
    composer = 'DRAFT-x please also look at theACK-REQUEST tk: reply with exactly "ACK tk".'
    assert s7.classify_draft([], "tk", "DRAFT-x", composer) is DraftFate.MERGED
    assert s7.classify_draft([], "tk", "DRAFT-x", "DRAFT-x please also look at the") is DraftFate.PRESERVED


def test_composer_text_is_the_input_box_not_history():
    assert composer_text("claude", CLAUDE_DRAFT) == "DRAFT-0a1b2c3d please also look at the"
    assert "earlier prompt" not in composer_text("codex", CODEX_STUCK)


def test_text_left_in_the_composer_is_noted_as_stuck():
    assert stuck_note("codex", CODEX_STUCK, "9f9f9f9f", recorded=False) == "stuck-in-composer"
    assert stuck_note("codex", CODEX_STUCK, "11111111", recorded=False) is None


def test_collapsed_paste_left_in_the_composer_is_noted_as_stuck():
    rule = "─" * 40
    pane = f"{rule}\n❯ [Pasted text #1 +14 lines][Pasted text #2 +14 lines]\n{rule}\n  ⏵⏵ bypass permissions on\n"
    assert stuck_note("claude", pane, "db42d531", recorded=False) == "stuck-in-composer (paste placeholder)"
    assert stuck_note("claude", pane, "db42d531", recorded=True) is None


def test_human_proxy_text_never_opens_commands_or_import_screens():
    assert s8.safe_human_text(s8.human_text("HUMAN-0a1b2c3d"))
    assert s8.safe_human_text("/loop 5m hi") is False
    assert s8.safe_human_text("please run /loop") is False
    assert s8.safe_human_text("import my claude skills") is False


def test_attached_client_stream_render_check_survives_escape_sequences():
    raw = "\x1b[2J\x1b[1;1H\x1b[1m•\x1b[22m ACK\x1b[1C\x1b[38;5;2m0a1b2c3d\x1b[0m\r\n"
    assert s8.reply_rendered(strip_ansi(raw), "ACK 0a1b2c3d", s8.ACK_LEAD)


ECHO = '❯ ACK-REQUEST 0a1b2c3d: reply with exactly "ACK 0a1b2c3d". body\r\n'


def test_echoed_prompt_alone_does_not_count_as_rendered_reply():
    assert s8.reply_rendered(ECHO * 3, "ACK 0a1b2c3d", s8.ACK_LEAD) is False
    assert s8.reply_rendered(ECHO + "⏺ ACK 0a1b2c3d\r\n", "ACK 0a1b2c3d", s8.ACK_LEAD)


def test_prompt_wrapped_inside_a_bordered_composer_is_still_the_echo():
    wrapped = '│ > ACK-REQUEST 0a1b2c3d: reply with exactly "\r\n│ ACK 0a1b2c3d". body'
    assert s8.reply_rendered(wrapped, "ACK 0a1b2c3d", s8.ACK_LEAD) is False


def test_human_marker_counts_only_outside_the_typed_prompt():
    typed = "❯ " + s8.human_text("HUMAN-0a1b2c3d")
    assert s8.reply_rendered(typed, "HUMAN-0a1b2c3d", s8.HUMAN_LEAD) is False
    assert s8.reply_rendered(typed + "\r\n⏺ HUMAN-0a1b2c3d", "HUMAN-0a1b2c3d", s8.HUMAN_LEAD)


def test_stale_address_steps_combine_to_the_worst_outcome():
    ok = s10.Step("clear", Delivery.DELIVERED, Ack.ACKED, True, "new-session")
    lost = s10.Step("compact", Delivery.LOST, Ack.NONE, None, "nowhere")
    assert s10.combine([ok, ok]) == (Delivery.DELIVERED, Ack.ACKED, True)
    assert s10.combine([ok, lost]) == (Delivery.LOST, Ack.NONE, None)
    assert s10.combine([]) == (Delivery.NA, Ack.NONE, None)
    assert s10.landed(["new"], "old") == "new-session"


def test_modal_and_model_detection():
    assert s11.modal_visible("claude", CLAUDE_PICKER)
    assert s11.modal_visible("codex", CODEX_PICKER)
    assert s11.shown_model("codex", "  GPT-6-Luna low · ~/w") == "GPT-6-Luna low"
    banner = ("▝▜██████▀  Haiku 5.5 · Claude API\n"
              "  Get to finished work sooner with Opus 5.5. Switch anytime with /model.\n")
    assert s11.shown_model("claude", banner) == "Haiku 5.5"
    switched = banner + "  ⎿  Set model to Sonnet 5.5 and saved as your default\n"
    assert s11.shown_model("claude", switched) == "Sonnet 5.5"


def test_pi_model_selector_is_the_modal_and_the_slash_hint_is_not(fixtures):
    selector = (fixtures / "pi" / "model-selector.txt").read_text()
    hint = "/model\n→ model          <provider/model> — Select model (opens selector UI)\n  scoped-models\n"
    assert s11.modal_visible("pi", selector)
    assert s11.modal_visible("pi", hint) is False


def test_droid_compress_confirmation_box_is_recognised(fixtures):
    box = (fixtures / "droid" / "compress-confirm.txt").read_text()
    assert s10.confirm_visible("droid", box)
    assert s10.confirm_visible("claude", box) is False


def test_compact_after_a_clear_answered_in_the_old_session_warms_up_the_visible_session():
    old = s10.Step("clear", Delivery.DELIVERED, Ack.ACKED, True, "old-session")
    new = s10.Step("clear", Delivery.DELIVERED, Ack.ACKED, True, "new-session")
    assert s10.needs_warm_up("compact", [old])
    assert s10.needs_warm_up("compact", [new]) is False
    assert s10.needs_warm_up("compact", []) is False


def test_opencode_compaction_counts_as_done_once_its_token_counts_show():
    queued = "  ─────────◇Compaction queued─────────"
    finished = "  ───────── Compaction · 14.2K in · 178 out ─────────\n     Objective\n"
    assert s10.command_done("compact", finished)
    assert s10.command_done("compact", queued) is False
    assert s10.command_done("compact", "  ⎿  Compacted (ctrl+o to see full summary)")


def test_s10_ack_is_only_the_receiver_reply():
    prompt = (1.0, "user", 'ACK-REQUEST tk: reply with exactly "ACK tk". body')
    assert s10.acked([prompt], "tk") is False
    assert s10.acked([prompt, (2.0, "assistant", "ACK tk")], "tk")


def test_s12_needs_a_backend():
    assert s12.not_applicable("codex", "none") == "no backing server (backend none)"
    assert s12.not_applicable("codex", "codex-app-server") is None


def test_a_second_picker_after_the_send_counts_as_a_selection():
    reasoning = "  Select Reasoning Level for GPT-6-Luna\n› 1. Low (current)\n  enter default · s session · esc back\n"
    assert s11.modal_visible("codex", reasoning)
    assert s11.selection_made("codex", CODEX_PICKER, reasoning)
    assert s11.selection_made("codex", CODEX_PICKER, CODEX_PICKER) is False


def fake_cell(tmp_path, gone=None, owned=True):
    from pathlib import Path
    from types import SimpleNamespace

    from agentcomms import manifest
    from agentcomms.engine import Launched
    from agentcomms.model import Target
    from agentcomms.paths import Layout
    from agentcomms.profiles import Binary
    from agentcomms.scenarios.common import Cell

    typed = []

    def check_owned(target, live=True):
        if not owned:
            raise manifest.OwnershipError(f"target {target.host_ref} is not owned")

    tmux = SimpleNamespace(type_text=lambda ref, text, submit: typed.append((ref, text, submit)),
                           send_key=lambda ref, key: typed.append((ref, key)))
    engine = SimpleNamespace(layout=Layout(tmp_path), user_home="/Users/me", sandbox="raw", tmux=tmux,
                             host_of=lambda target: tmux, check_owned=check_owned, snapshot=lambda target, label: "",
                             receiver_gone=lambda target: gone,
                             write_body_diff=lambda *a: "diff.txt", transcript_for=lambda target: None)
    target = Target("r1", "pi", "tmux", "none", tmp_path / "w", tmp_path / "h", "s", "agentcomms:r1-pi", None,
                    None, 42)
    launched = Launched(target, Binary("pi", Path("/p"), "1.4.0"), {"pi": "1.4.0"}, tmp_path / "pane.log",
                        "pane-regex", [])
    adapter = SimpleNamespace(name="tmux-paste", unwrap=lambda t: t)
    return Cell(engine, None, launched, adapter, "S1", "pilot", 1), typed


def test_pi_custom_entry_counts_as_an_intact_delivery(tmp_path):
    from types import SimpleNamespace

    from agentcomms.model import SendReceipt
    from agentcomms.scenarios.common import observe
    cell, _ = fake_cell(tmp_path)
    text = 'ACK-REQUEST tk: reply with exactly "ACK tk". body'
    transcript = SimpleNamespace(entries=lambda: [(5.0, "custom", text), (6.0, "assistant", "ACK tk")],
                                 path=tmp_path / "s.jsonl")
    out = observe(cell, cell.target, "tk", text, SendReceipt(True, 4.0, 0.0), transcript, True)
    assert (out.delivery, out.intact, out.ack, out.tokens) == (Delivery.DELIVERED, True, Ack.ACKED, ["tk"])


def test_receiver_crash_becomes_a_pausing_env_error(tmp_path, monkeypatch):
    from agentcomms import checkpoint
    from agentcomms.scenarios.common import Outcome, finish
    monkeypatch.setattr(checkpoint, "network_ok", lambda: True)
    cell, _ = fake_cell(tmp_path, gone="pid 42 gone")
    cell.m = SimpleRun()
    record = finish(cell, Outcome(Delivery.LOST, tokens=["tk"]), 0.0, 0.0)
    assert record.delivery is Delivery.ENV_ERROR
    assert "receiver-crashed (pid 42 gone; was lost)" in record.notes
    assert record.token == "tk"


class SimpleRun:
    run_id = "r1"


def test_typed_input_checks_ownership_before_typing(tmp_path):
    import pytest

    from agentcomms import manifest
    cell, typed = fake_cell(tmp_path, owned=False)
    with pytest.raises(manifest.OwnershipError):
        cell.type_text(cell.target, "/model", submit=True)
    with pytest.raises(manifest.OwnershipError):
        cell.send_key(cell.target, "Escape")
    assert typed == []
    owned, typed = fake_cell(tmp_path)
    owned.type_text(owned.target, "/model", submit=True)
    assert typed == [("agentcomms:r1-pi", "/model", True)]


RENDER_CASES = [
    ("s1-pane-codex.log", "ACK 0d554c3d"),
    ("s1-pane-claude.log", "ACK c4ec6f7f"),
    ("s8-attach-claude.log", "ACK 29b9bdb8"),
    ("s8-attach-codex.log", "ACK 2531c3f3"),
]


def test_reply_renders_in_real_streams_with_incremental_redraw(fixtures):
    for name, needle in RENDER_CASES:
        stream = strip_ansi((fixtures / "render" / name).read_text(errors="replace"))
        assert s8.reply_rendered(stream, needle, s8.ACK_LEAD), name


def test_real_streams_cut_before_the_reply_show_only_the_echo(fixtures):
    for name, needle in RENDER_CASES:
        stream = strip_ansi((fixtures / "render" / name).read_text(errors="replace"))
        flat = "".join(stream.split())
        echo_only = stream[:stream.index("ACK-REQUEST")] + flat[flat.index("ACK-REQUEST"):flat.rindex(
            needle.replace(" ", "")) - 1]
        assert needle.replace(" ", "") in echo_only, name
        assert s8.reply_rendered(echo_only, needle, s8.ACK_LEAD) is False, name


def test_human_turn_renders_in_real_attach_streams(fixtures):
    for name, marker in (("s8-attach-claude.log", "HUMAN-9f26ca8b"), ("s8-attach-codex.log", "HUMAN-f24ad11d")):
        stream = strip_ansi((fixtures / "render" / name).read_text(errors="replace"))
        assert s8.reply_rendered(stream, marker, s8.HUMAN_LEAD), name


def test_codex_s3_setup_asks_the_model_to_request_escalation():
    assert s3.setup_text("codex").endswith("request approval to run the write outside the sandbox.")
    assert s3.setup_text("claude") == s3.SETUP


def test_s8_attaches_through_the_targets_own_host(tmp_path, monkeypatch):
    from types import SimpleNamespace

    cell, _ = fake_cell(tmp_path)
    calls = []

    class Client:
        proc = SimpleNamespace(pid=7)

        def text(self):
            return ""

        def close(self):
            calls.append("close")

    zmx_host = SimpleNamespace(
        attach_client=lambda ref, log, cwd, env: calls.append(("attach", ref)) or Client(),
        detach_client=lambda ref: calls.append(("detach", ref)),
        type_text=lambda ref, text, submit: calls.append(("type", ref)))
    cell.engine.host_of = lambda target: zmx_host
    cell.engine.environ = {}
    cell.engine.add_pgid = lambda m, pid: m
    cell.engine.transcript_for = lambda target: None
    monkeypatch.setattr(s8, "HUMAN_TIMEOUT_S", 0.0)
    out = s8.run(cell)
    assert out.delivery is Delivery.ERROR
    assert calls == [("attach", "agentcomms:r1-pi"), ("type", "agentcomms:r1-pi"), ("detach", "agentcomms:r1-pi"),
                     "close"]


def test_opencode_composer_is_the_whole_indented_input_block(fixtures):
    from agentcomms.scenarios.common import composer_text
    home = composer_text("opencode", (fixtures / "opencode" / "pane-draft-home.txt").read_text())
    session = composer_text("opencode", (fixtures / "opencode" / "pane-session-idle.txt").read_text())
    assert home.split()[:6] == ["DRAFT-9219b92e", "please", "also", "look", "at", "the"]
    assert session.split()[:7] == ["Build", "auto", "·", "GPT-6", "Luna", "OpenCode", "Go"]


def test_s8_waits_for_a_human_turn_that_a_slow_host_relays_late():
    class LateClient:
        calls = 0

        def text(self):
            self.calls += 1
            prompt = "› " + s8.human_text("HUMAN-0a1b2c3d")
            return prompt + ("\r\n• HUMAN-0a1b2c3d" if self.calls >= 3 else "")

    client = LateClient()
    assert s8.human_turn_rendered(client, "HUMAN-0a1b2c3d", wait_s=5.0, interval_s=0.01)
    assert client.calls == 3


def test_s8_push_answered_in_a_hidden_thread_is_delivered_but_not_rendered(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from agentcomms.model import SendReceipt

    cell, _ = fake_cell(tmp_path)
    tokens = iter(["0a1b2c3d", "4e126e6e"])
    monkeypatch.setattr(s8, "new_token", lambda: next(tokens))
    monkeypatch.setattr(s8, "RENDER_WAIT_S", 0.0)
    pushed = 'ACK-REQUEST 4e126e6e: reply with exactly "ACK 4e126e6e". ' + s8.BODY
    visible = SimpleNamespace(path=tmp_path / "user-thread.jsonl",
                              entries=lambda: [(1.0, "user", s8.human_text("HUMAN-0a1b2c3d")),
                                               (2.0, "assistant", "HUMAN-0a1b2c3d")])
    hidden = SimpleNamespace(path=tmp_path / "bridge-thread.jsonl",
                             entries=lambda: [(5.0, "user", pushed), (6.0, "assistant", "ACK 4e126e6e")])

    class Client:
        proc = SimpleNamespace(pid=7)

        def text(self):
            return ("› " + s8.human_text("HUMAN-0a1b2c3d") + "\r\n• HUMAN-0a1b2c3d"
                    "\r\nIntercom turn from agentcomms completed: ACK 4e126e6e")

        def close(self):
            pass

    host = SimpleNamespace(attach_client=lambda *a: Client(), detach_client=lambda ref: None,
                           type_text=lambda ref, text, submit: None)
    cell.engine.host_of = lambda target: host
    cell.engine.environ = {}
    cell.engine.add_pgid = lambda m, pid: m
    cell.engine.transcript_for = lambda target: visible
    cell.engine.idle = lambda target, transcript: True
    cell.engine.wait_for_token = lambda target, token, timeout: (hidden, True)
    cell.engine.track_spawned = lambda m, spawned: m
    cell.adapter.send = lambda target, text: SendReceipt(True, 4.0, 0.0)
    out = s8.run(cell)
    assert out.delivery is Delivery.DELIVERED
    assert out.intact is True
    assert "rendered=no" in out.notes
    assert "hidden-thread" in out.notes


def test_s8_render_wait_covers_slow_relaying_hosts():
    assert s8.RENDER_WAIT_S == 45.0


def test_s2_push_answered_in_a_hidden_parallel_thread_is_neither_queued_nor_interrupted():
    entries = [(1.0, "user", "ACK-REQUEST tk: x"), (2.0, "assistant", "ACK tk")]
    assert s2.midturn_verdict(Delivery.DELIVERED, entries, "tk", MARKER, hidden=True) == (
        Delivery.DELIVERED, ["parallel-thread"])
    assert s2.midturn_verdict(Delivery.DELIVERED, entries, "tk", MARKER, hidden=False) == (
        Delivery.INTERRUPTED, [])


def run_s10(monkeypatch, sessions):
    from types import SimpleNamespace

    from agentcomms.scenarios.common import Outcome

    events = []
    current = SimpleNamespace(session_id="old", host_ref="ref")
    host = SimpleNamespace(capture=lambda ref: "Compaction · 5K in")
    engine = SimpleNamespace(current_target=lambda m, t: (m, t), host_of=lambda t: host,
                             wait_idle=lambda *a, **k: True, all_transcripts=lambda t: [], snapshot=lambda *a: None)
    cell = SimpleNamespace(engine=engine, m="m", target=current, agent="opencode",
                           type_text=lambda target, text, submit: events.append(f"type {text}"),
                           owned_send=lambda target, text: events.append("push") or "receipt")
    monkeypatch.setattr(s10, "warm_up", lambda c, target, timeout: events.append("warm-up") or True)
    monkeypatch.setattr(s10, "poll", lambda fn, *a, **k: fn() or "transcript")
    monkeypatch.setattr(s10, "transcript_session", lambda t: sessions.pop(0))
    monkeypatch.setattr(s10, "observe", lambda *a, **k: Outcome(Delivery.DELIVERED, intact=True, ack=Ack.ACKED))
    return s10.run(cell), events


def test_s10_warms_up_the_visible_session_before_compacting_when_the_push_after_new_hit_the_old_session(monkeypatch):
    out, events = run_s10(monkeypatch, ["old", "old"])
    assert events == ["warm-up", "type /new", "push", "warm-up", "type /compact", "push"]
    assert out.notes[:3] == ["clear=delivered@old-session", "compact-warm-up", "compact=delivered@old-session"]


def test_s10_compacts_without_a_warm_up_when_the_push_after_new_reached_the_new_session(monkeypatch):
    out, events = run_s10(monkeypatch, ["new", "new"])
    assert events == ["warm-up", "type /new", "push", "type /compact", "push"]
    assert out.notes[:2] == ["clear=delivered@new-session", "compact=delivered@new-session"]
