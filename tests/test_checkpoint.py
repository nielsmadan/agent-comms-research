from agentcomms.checkpoint import (
    ProgressWriter,
    TimeBudget,
    append_record,
    load_records,
    pending_cells,
    slept,
)
from agentcomms.report import render_progress


def cell(agent: str) -> dict:
    return {"stage": "pilot", "agent": agent, "mechanism": "tmux-paste", "host": "tmux", "backend": "none",
            "scenario": "S1", "rep": 1, "sandbox": "raw"}


def test_sleep_detector_flags_60s_divergence():
    assert slept(wall0=1000.0, mono0=50.0, wall1=1090.0, mono1=80.0) is True


def test_sleep_detector_accepts_matching_clocks():
    assert slept(wall0=1000.0, mono0=50.0, wall1=1030.5, mono1=80.0) is False


def test_resume_skips_recorded_cells_and_requeues_env_errors(fixtures):
    records = load_records(fixtures / "raw-sample.jsonl")
    cells = [cell("claude"), cell("codex"), cell("pi")]
    assert pending_cells(cells, records, resume=True) == [cell("codex"), cell("pi")]
    assert pending_cells(cells, records, resume=False) == cells


def test_append_record_writes_one_line_per_record(tmp_path):
    raw = tmp_path / "results" / "raw.jsonl"
    append_record(raw, {"a": 1})
    append_record(raw, {"b": "é"})
    assert load_records(raw) == [{"a": 1}, {"b": "é"}]


def test_time_budget_expires_at_limit():
    budget = TimeBudget(start_mono=100.0, minutes=110)
    assert budget.expired(100.0 + 110 * 60) is True
    assert budget.expired(100.0 + 109 * 60) is False


def test_progress_lists_done_cells_issues_and_next(fixtures):
    text = render_progress(load_records(fixtures / "raw-sample.jsonl"), ["auth link replaced"], [cell("pi")], 0.0)
    assert "| 20261024-101500-a1b2 | pilot | claude | tmux-paste | tmux | S1 | 1 | delivered | acked | 0.4 |" in text
    assert "- auth link replaced" in text
    assert "- pilot pi tmux-paste S1 rep 1" in text
    assert "Totals: delivered 1, env_error 1" in text


def test_progress_writer_rewrites_every_30_minutes(tmp_path, fixtures):
    writer = ProgressWriter(tmp_path / "progress.md", fixtures / "raw-sample.jsonl")
    assert writer.maybe_write(0.0, []) is True
    assert writer.maybe_write(29 * 60, []) is False
    assert writer.maybe_write(30 * 60, []) is True
    assert writer.maybe_write(30 * 60 + 1, [], force=True) is True


def test_progress_rewrite_keeps_the_hand_written_notes_section(tmp_path, fixtures):
    path = tmp_path / "progress.md"
    path.write_text("# Progress\n\nUpdated: x\n\n## Notes\n\n- screen estimate: 284 cells, ~3 h\n\n"
                    "## Done cells\n\nNone yet.\n")
    ProgressWriter(path, fixtures / "raw-sample.jsonl").maybe_write(0.0, [], force=True)
    text = path.read_text()
    assert "## Notes\n\n- screen estimate: 284 cells, ~3 h\n\n## Done cells" in text
    assert "| 20261024-101500-a1b2 | pilot | claude | tmux-paste |" in text
