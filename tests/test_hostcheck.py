import json

from agentcomms.hostcheck import analysis, runner
from agentcomms.hostcheck.analysis import PASTE_END, PASTE_START, Read


def reads(*chunks: bytes) -> list[Read]:
    return [Read(float(i), c) for i, c in enumerate(chunks)]


def test_parse_log_splits_meta_from_reads_and_skips_garbage():
    text = "\n".join([json.dumps({"ready": True, "rows": 50, "cols": 200}),
                      json.dumps({"t": 1.5, "hex": "68690d"}), "not json", ""])
    meta, got = analysis.parse_log(text)
    assert meta == {"ready": True, "rows": 50, "cols": 200}
    assert got == [Read(1.5, b"hi\r")]


def test_exact_typed_message_with_enter():
    result = analysis.analyze_case("plain", "hello", reads(b"hello", b"\r"))
    assert (result.fidelity, result.markers, result.submit, result.sizes) == ("exact", "absent", "0d", (5, 1))


def test_wrapped_paste_is_exact_and_marks_wrapped():
    result = analysis.analyze_case("plain", "a\nb", reads(PASTE_START + b"a\nb" + PASTE_END + b"\r"))
    assert (result.fidelity, result.markers) == ("exact", "wrapped")


def test_lf_arriving_as_cr_is_newline_translated():
    result = analysis.analyze_case("multiline", "a\nb", reads(PASTE_START + b"a\rb" + PASTE_END, b"\r"))
    assert (result.fidelity, result.detail) == ("newline-translated", "LF arrives as CR")


def test_changed_bytes_report_the_first_difference():
    result = analysis.analyze_case("unicode", "héllo", reads(b"h?llo", b"\r"))
    assert result.fidelity == "differs"
    assert result.detail.startswith("offset 1:")


def test_no_bytes_is_missing():
    assert analysis.analyze_case("plain", "x", []).fidelity == "missing"


def test_unbalanced_markers_are_partial():
    result = analysis.analyze_case("plain", "x", reads(PASTE_START + b"x", b"\r"))
    assert result.markers == "partial(1/0)"


def test_marker_split_across_reads_is_detected():
    marker_cut = reads(PASTE_START[:3], PASTE_START[3:] + b"x" + PASTE_END + b"\r")
    assert analysis.analyze_case("plain", "x", marker_cut).marker_split is True
    whole = reads(PASTE_START, b"x" + PASTE_END + b"\r")
    assert analysis.analyze_case("plain", "x", whole).marker_split is False


def test_burst_in_order_with_paste_regions():
    sent = ["m1", "m2", "m3"]
    got = reads(*(PASTE_START + s.encode() + PASTE_END + b"\r" for s in sent))
    result = analysis.analyze_burst(sent, got)
    assert (result.in_order, result.received, result.paste_regions) == (True, 3, 3)


def test_burst_merged_or_reordered_is_not_in_order():
    merged = analysis.analyze_burst(["m1", "m2"], reads(b"m1m2\r"))
    swapped = analysis.analyze_burst(["m1", "m2"], reads(b"m2\rm1\r"))
    assert (merged.in_order, merged.received) == (False, 1)
    assert (swapped.in_order, swapped.received) == (False, 2)


def test_summary_text_and_table_row():
    cases = [analysis.analyze_case(name, text, reads(text.encode(), b"\r")) for name, text in analysis.CASES.items()]
    burst = analysis.analyze_burst(analysis.BURST, reads(*(s.encode() + b"\r" for s in analysis.BURST)))
    summary = analysis.summarize(cases, burst)
    assert summary.fidelity == "7/7 exact"
    assert summary.markers == "absent"
    assert summary.burst == "5/5 in order"
    table = analysis.render_table([("tmux", "tmux-keys", summary)])
    assert "| tmux | tmux-keys | 7/7 exact | absent | 0d |" in table


def test_summary_lists_problem_cases():
    bad = analysis.analyze_case("multiline", "a\nb", reads(b"a\rb", b"\r"))
    summary = analysis.summarize([bad], analysis.analyze_burst(["x"], reads(b"x\r")))
    assert summary.fidelity == "0/1 exact; multiline newline-translated: LF arrives as CR"
    assert summary.failing == {"multiline": "newline-translated: LF arrives as CR"}


def test_cases_cover_the_s4_payload_classes():
    assert {"multiline", "quotes", "tab", "unicode", "long"} <= set(analysis.CASES)
    assert len(analysis.CASES["long"]) > 10_000


def row(host, adapter, fidelity="7/7 exact", notes=None):
    summary = {"fidelity": fidelity, "markers": "absent", "chunking": "c", "burst": "5/5", "submit": "0d",
               "failing": {}}
    return {"host": host, "adapter": adapter, "blocked": None, "summary": summary, "notes": notes or []}


def test_a_subset_run_replaces_only_its_rows_and_keeps_the_rest_in_order():
    old = [row("tmux", "tmux-keys"), row("zmx", "zmx-send"), row("iterm2", "iterm2-text", "old")]
    merged = runner.merge_rows(old, [row("iterm2", "iterm2-text", "new", ["focus_stolen=yes"])])
    assert [(r["host"], r["adapter"], r["summary"]["fidelity"]) for r in merged] == [
        ("tmux", "tmux-keys", "7/7 exact"), ("zmx", "zmx-send", "7/7 exact"), ("iterm2", "iterm2-text", "new")]
    text = runner.render_rows(merged)
    assert "| tmux | tmux-keys | 7/7 exact |" in text and "- iterm2 / iterm2-text: focus_stolen=yes" in text
