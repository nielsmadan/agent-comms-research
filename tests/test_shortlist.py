import pytest

from agentcomms import shortlist

PINS = {"claude": "2.1.312", "codex": "0.165.0", "pi": "1.4.0", "opencode": "2.2.0", "droid": "0.251.0"}
GOOD_S2 = {"delivery": "queued", "intact": True}
GOOD_S7 = {"delivery": "delivered", "draft_fate": "preserved"}
BAD_S7 = {"delivery": "delivered", "draft_fate": "merged"}


def rec(agent, mech, scenario, stage="extensive", **fields):
    base = {"run_id": "r", "stage": stage, "agent": agent, "mechanism": mech, "scenario": scenario,
            "delivery": "delivered", "intact": True, "draft_fate": "n/a", "harmful": False, "notes": "",
            "versions": {agent: PINS[agent]}}
    return base | fields


def safety_records(agent, mech, s3):
    return ([rec(agent, mech, "S2", **GOOD_S2) for _ in range(3)]
            + [rec(agent, mech, "S7", **BAD_S7) for _ in range(3)] + [rec(agent, mech, "S3", **s3)])


def scored(records):
    merged = shortlist.with_equivalence(shortlist.counted_records(records))
    return merged, {p: shortlist.score(m) for p, m in merged.items()}


def test_an_unmeasured_s3_counts_against_the_fixed_denominator_of_seven():
    records = (safety_records("droid", "measured", {"delivery": "delivered", "harmful": True})
               + safety_records("droid", "unmeasured", {"delivery": "n/a", "intact": None}))
    _, by_pair = scored(records)
    assert shortlist.SAFETY_DENOMINATOR == 7
    assert (by_pair[("droid", "measured")].safety_k, by_pair[("droid", "measured")].safety) == (3, 3 / 7)
    assert (by_pair[("droid", "unmeasured")].safety_k, by_pair[("droid", "unmeasured")].safety) == (3, 3 / 7)
    assert shortlist.rank(by_pair, "droid") == [("droid", "unmeasured"), ("droid", "measured")]


def test_the_ranking_table_shows_the_na_count_beside_the_safety_score():
    records = (safety_records("droid", "measured", {"delivery": "delivered", "harmful": True})
               + safety_records("droid", "unmeasured", {"delivery": "n/a", "intact": None}))
    merged, by_pair = scored(records)
    rows = {line.split("|")[2].strip(): line for line in shortlist.render_ranking(merged, by_pair).splitlines()
            if line.startswith("| ") and line.split("|")[2].strip() in ("measured", "unmeasured")}
    assert "| 3/7 · n/a 1 |" in rows["unmeasured"]
    assert "| 3/7 |" in rows["measured"]


def test_a_mechanism_that_never_ran_a_safety_scenario_is_scored_out_of_seven_not_dropped():
    records = [rec("pi", "a", "S2", **GOOD_S2) for _ in range(3)]
    _, by_pair = scored(records)
    assert by_pair[("pi", "a")].safety == 3 / 7


def test_top_keeps_ties_at_the_boundary_and_labels_them():
    records = []
    for mech, good in (("a", 3), ("b", 3), ("c", 3), ("d", 2)):
        records += [rec("claude", mech, "S2", **(GOOD_S2 if i < good else {"delivery": "lost"})) for i in range(3)]
    _, by_pair = scored(records)
    picked = shortlist.top(shortlist.rank(by_pair, "claude"), by_pair)
    assert [p[1] for p in picked] == ["a", "b", "c"]
    assert shortlist.top_text(picked, by_pair) == "a, b, c (tied 3/3)"


def test_safety_denominator_does_not_change_the_total_k_over_n():
    records = safety_records("droid", "unmeasured", {"delivery": "n/a", "intact": None})
    _, by_pair = scored(records)
    assert shortlist.fraction(by_pair[("droid", "unmeasured")]) == "3/6"


def s9(agent_a, agent_b, fwd, back, passed, versions, stage="extensive"):
    notes = f"pair={agent_a}>{agent_b}; fwd={fwd}; back={back}; roundtrip={'yes' if passed else 'no'}"
    return rec(agent_a, fwd, "S9", stage=stage, notes=notes, versions=versions,
               delivery="delivered")


def test_only_pinned_version_s9_passes_add_a_route():
    records = [s9("pi", "claude", "intercom-accept", "intercom-accept", True, {"pi": "1.4.0", "claude": "2.1.311"}),
               s9("pi", "codex", "intercom", "intercom", True, {"pi": "1.4.0", "codex": "0.164.0"}),
               s9("pi", "pi", "intercom", "intercom", True, {"pi": "1.4.0"}),
               s9("claude", "codex", "hcom", "hcom", True, {"claude": "2.1.312", "codex": "0.165.0"})]
    evidence = shortlist.s9_evidence(records, PINS)
    survivors = {("pi", "intercom-accept"), ("pi", "intercom"), ("claude", "hcom"), ("codex", "hcom")}
    assert dict(shortlist.s9_added(evidence, survivors, set())) == {
        "pi": ["intercom"], "claude": ["hcom"], "codex": ["hcom"]}


def test_a_pinned_pass_on_a_route_that_was_never_screened_adds_it():
    records = [s9("pi", "claude", "intercom-accept", "intercom-accept", True, {"pi": "1.4.0", "claude": "2.1.312"})]
    evidence = shortlist.s9_evidence(records, PINS)
    assert dict(shortlist.s9_added(evidence, set(), set(), {("claude", "intercom-accept")})) == {
        "pi": ["intercom-accept"]}


def test_a_screened_non_survivor_is_not_added_by_a_pinned_s9_pass():
    records = [s9("claude", "claude", "claude-uds", "claude-uds", True, {"claude": "2.1.312"})]
    evidence = shortlist.s9_evidence(records, PINS)
    assert dict(shortlist.s9_added(evidence, set(), set(), {("claude", "claude-uds")})) == {}


def test_a_pinned_failure_keeps_a_route_out_even_with_a_pinned_pass():
    records = [s9("pi", "claude", "intercom-accept", "intercom-accept", True, {"pi": "1.4.0", "claude": "2.1.312"}),
               s9("codex", "claude", "intercom-accept", "intercom-accept", False,
                  {"codex": "0.165.0", "claude": "2.1.312"})]
    evidence = shortlist.s9_evidence(records, PINS)
    added = shortlist.s9_added(evidence, {("claude", "intercom-accept")}, set(), {("claude", "intercom-accept")})
    assert dict(added) == {"pi": ["intercom-accept"]}


def test_routes_already_shortlisted_by_ranking_are_not_listed_again():
    records = [s9("claude", "codex", "hcom", "hcom", True, {"claude": "2.1.312", "codex": "0.165.0"})]
    evidence = shortlist.s9_evidence(records, PINS)
    screened = {("codex", "hcom"), ("claude", "hcom")}
    assert dict(shortlist.s9_added(evidence, {("codex", "hcom")}, {("codex", "hcom")}, screened)) == {}


SCREEN = """\
| agent | mechanism | host | backend | S1 | S4 | S7 | S8 | survivor |
|---|---|---|---|---|---|---|---|---|
| claude | hcom | tmux | none | **delivered** | **intact** | **preserved** | **rendered=yes** | yes |
| claude | claude-uds | tmux | none | held | held | held | held (stuck) | no |
| droid | n/a-pair | tmux | none | n/a | n/a | n/a | n/a | n/a |
"""


def test_survivors_are_the_yes_rows_and_screened_pairs_the_yes_and_no_rows_of_the_screen_table():
    assert shortlist.survivors(SCREEN) == {("claude", "hcom")}
    assert shortlist.screened(SCREEN) == {("claude", "hcom"), ("claude", "claude-uds")}


def test_splice_replaces_only_the_generated_blocks():
    text = "intro\n<!-- generated:table -->\nold\n<!-- /generated:table -->\nprose\n"
    out = shortlist.splice(text, {"table": "new | row"})
    assert out == "intro\n<!-- generated:table -->\nnew | row\n<!-- /generated:table -->\nprose\n"
    with pytest.raises(ValueError, match="generated:ranking"):
        shortlist.splice(text, {"ranking": "x"})


def test_generate_ranks_only_screen_survivors():
    screen = SCREEN.replace("| claude | claude-uds |", "| claude | tmux-paste |").replace("| no |", "| yes |")
    records = [rec("claude", "hcom", "S2", **GOOD_S2), rec("claude", "tmux-paste", "S2", **GOOD_S2),
               rec("claude", "other", "S2", **GOOD_S2)]
    sections = shortlist.generate(records, screen, PINS)
    assert "| 1 | hcom |" in sections["ranking"]
    assert "other" not in sections["ranking"]


def s9_route(a, b, fwd, back, roundtrip, **fields):
    return rec(a, f"{fwd}+{back}", "S9", notes=f"pair={a}>{b}; fwd={fwd}; back={back}; roundtrip={roundtrip}",
               versions={a: PINS[a], b: PINS[b]}, **fields)


def test_s9_column_ignores_nono_and_user_config_round_trips():
    records = [s9_route("claude", "pi", "pi-ext", "claude-uds-accept", "yes"),
               s9_route("claude", "pi", "pi-ext", "claude-uds-accept", "no", stage="nono", sandbox="nono"),
               s9_route("claude", "pi", "pi-ext", "claude-uds-accept", "no", stage="user-config")]
    evidence = shortlist.s9_evidence(records, PINS)
    assert evidence[("pi", "pi-ext")]["pass"] == ["claude>pi"]
    assert evidence[("pi", "pi-ext")]["fail"] == []


def test_condition_tables_count_reps_across_stages_and_name_the_not_good_causes():
    records = ([rec("codex", "q", "S7", stage="screen", **GOOD_S7)]
               + [rec("codex", "q", "S7", stage="extensive", **BAD_S7) for _ in range(2)]
               + [rec("codex", "q", "S7", stage="shortlist", **GOOD_S7) for _ in range(2)]
               + [rec("codex", "q", "S7", stage="nono", sandbox="nono", delivery="lost")])
    table = shortlist.condition_table(records, [("codex", "q")], ("S1", "S7"), shortlist.reps_records, "shortlist")
    assert "| Codex | q | - | 3/5 | 3/5 | S7 draft merged x2 |" in table
    nono = shortlist.condition_table(records, [("codex", "q")], ("S7",), shortlist.stage_records("nono"), "nono")
    assert "| Codex | q | 0/1 | 0/1 | S7 lost |" in nono


def test_condition_tables_show_the_outward_contact_caveat_beside_good_cells():
    note = ("ready=pane-regex; user-config: disabled plugin x; outward-contact: mcp context7 started (switch "
            "ineffective in 2.2.0); jina likely; transcript=runs/r/db; send_s=0.01")
    records = [rec("opencode", "q", "S1", stage="user-config", notes=note)]
    keep = shortlist.stage_records("user-config")
    table = shortlist.condition_table(records, [("opencode", "q")], ("S1", "S7"), keep, "user-config")
    assert table.splitlines()[-1] == ("| OpenCode | q | 1/1 | - | 1/1 | S1 outward-contact: mcp context7 started "
                                      "(switch ineffective in 2.2.0); jina likely |")


def test_scale_table_counts_each_receiver_across_batches():
    def msg(label, latency, delivery="delivered"):
        return rec("pi", "pi-ext", "SCALE", stage="shortlist", delivery=delivery, ack="acked", latency_s=latency,
                   run_id=f"run-{label}", notes=f"ready=pane-regex; scale-receiver={label}; round=1/3")
    table = shortlist.scale_table([msg("pi#1", 0.004), msg("pi#1", 0.002), msg("pi#2", None, "lost")])
    assert "| pi#1 | pi-ext | 2/2 | 2/2 | 0.002 / 0.003 / 0.004 s (n=2) |" in table
    assert "| pi#2 | pi-ext | 0/1 | 1/1 | - |" in table


def test_splice_fills_an_empty_block_and_skips_a_missing_optional_one():
    text = "a\n<!-- generated:reps -->\n<!-- /generated:reps -->\nb\n"
    out = shortlist.splice(text, {"reps": "| x |", "nono": "| y |"})
    assert out == "a\n<!-- generated:reps -->\n| x |\n<!-- /generated:reps -->\nb\n"


def test_a_mechanism_that_ran_in_a_condition_keeps_its_row_after_leaving_the_top_two():
    records = [rec("codex", "q", "S7", stage="shortlist", **GOOD_S7),
               rec("codex", "old", "S5", stage="shortlist", delivery="error",
                   notes="precondition: burst-window (window 1.34s); reclassified-R47 (was delivered)"),
               rec("codex", "never", "S7", stage="extensive", **GOOD_S7)]
    table = shortlist.condition_table(records, [("codex", "q")], ("S5", "S7"), shortlist.reps_records, "shortlist")
    rows = table.splitlines()[2:]
    assert rows == ["| Codex | q | - | 1/1 | 1/1 | - |",
                    "| Codex | old (ran while shortlisted; no longer top 2) | 0/0 · err 1 | - | 0/0 "
                    "| S5 error: precondition: burst-window |"]
