from agentcomms import scoring
from agentcomms.checkpoint import load_records
from agentcomms.report import render_matrix


def records(fixtures):
    return load_records(fixtures / "raw-matrix.jsonl")


def test_k_of_n_per_agent_mechanism_and_scenario(fixtures):
    table = scoring.tally(records(fixtures))
    claude = table[("claude", "tmux-paste", "tmux", "none", "26", "raw")]
    assert (claude["S1"].k, claude["S1"].n) == (1, 2)
    assert (claude["S2"].k, claude["S2"].n) == (1, 2)
    assert (claude["S3"].k, claude["S3"].n, claude["S3"].harmful) == (1, 2, 1)
    assert (claude["S5"].k, claude["S5"].n) == (1, 2)
    assert (claude["S7"].k, claude["S7"].n) == (1, 2)
    assert (claude["S12"].n, claude["S12"].na) == (0, 1)
    codex = table[("codex", "tmux-paste", "tmux", "none", "26", "raw")]
    assert (codex["S1"].k, codex["S1"].n) == (1, 1)
    assert (codex["S2"].n, codex["S2"].errors) == (0, 1)


def test_a_merged_burst_is_not_a_good_s5():
    base = {"scenario": "S5", "delivery": "delivered", "intact": True, "harmful": False, "draft_fate": "n/a"}
    assert scoring.is_good({**base, "notes": "burst=5/5; order=in-order; merged=no"})
    assert scoring.is_good({**base, "notes": "burst=5/5; order=in-order; merged=yes"}) is False


def test_cell_text():
    assert scoring.cell_text(scoring.Tally(k=1, n=2, harmful=1)) == "1/2 · harm 1"
    assert scoring.cell_text(scoring.Tally(errors=1)) == "0/0 · err 1"
    assert scoring.cell_text(scoring.Tally(na=1)) == "n/a"
    held = scoring.Tally().add({"scenario": "S1", "delivery": "held", "intact": None, "harmful": False})
    assert scoring.cell_text(held) == "0/1 · held 1"
    assert scoring.cell_text(None) == "-"


def test_note_values_are_read_from_record_notes():
    assert scoring.note_value("burst=5/5; order=in-order; merged=no", "order") == "in-order"
    assert scoring.note_value("ready=pane-regex; down=rejected", "down") == "rejected"
    assert scoring.note_value("", "down") is None


def test_matrix_markdown_has_one_row_per_agent_and_mechanism(fixtures):
    text = render_matrix(records(fixtures), 0.0)
    assert "| agent | mechanism | host | backend | macOS | condition | S1 | S2 | S3 | S5 | S7 | S12 |" in text
    assert "| claude | tmux-paste | tmux | none | 26 | raw | 1/2 | 1/2 | 1/2 · harm 1 | 1/2 | 1/2 | n/a |" in text
    assert "| codex | tmux-keys | tmux | none | 26 | raw | 0/1 | - | - | - | - | - |" in text
    assert "| codex | tmux-paste | tmux | none | 26 | raw | 1/1 | 0/0 · err 1 | - | - | - | - |" in text


def test_records_are_split_by_macos_era_and_old_records_count_as_26():
    base = {"agent": "claude", "mechanism": "tmux-paste", "host": "tmux", "backend": "none", "stage": "pilot",
            "scenario": "S1", "delivery": "delivered", "intact": True, "harmful": False, "notes": ""}
    old = {**base, "versions": {"claude": "2.1.310"}}
    new = {**base, "versions": {"claude": "2.1.311", "os": "27.2 (26B123)"}}
    table = scoring.tally([old, new, new])
    assert table[("claude", "tmux-paste", "tmux", "none", "26", "raw")]["S1"].n == 1
    assert table[("claude", "tmux-paste", "tmux", "none", "27", "raw")]["S1"].n == 2
    assert "| claude | tmux-paste | tmux | none | 27 | raw | 2/2 |" in render_matrix([old, new, new], 0.0)


def test_nono_and_user_config_records_get_their_own_matrix_rows():
    base = {"agent": "pi", "mechanism": "pi-ext", "host": "tmux", "backend": "none", "scenario": "S1",
            "delivery": "delivered", "intact": True, "harmful": False, "notes": "", "versions": {"os": "27.2"}}
    raw = {**base, "stage": "shortlist", "sandbox": "raw"}
    boxed = {**base, "stage": "nono", "sandbox": "nono", "delivery": "lost", "intact": None}
    user = {**base, "stage": "user-config", "sandbox": "raw"}
    table = scoring.tally([raw, raw, boxed, user])
    assert table[("pi", "pi-ext", "tmux", "none", "27", "raw")]["S1"].k == 2
    assert table[("pi", "pi-ext", "tmux", "none", "27", "nono")]["S1"].n == 1
    assert table[("pi", "pi-ext", "tmux", "none", "27", "nono")]["S1"].k == 0
    assert table[("pi", "pi-ext", "tmux", "none", "27", "raw + user config")]["S1"].k == 1


def test_malformed_os_labels_get_an_explicit_unknown_bucket():
    assert scoring.os_era({"versions": {"os": "27.2 (26B123)"}}) == "27"
    assert scoring.os_era({"versions": {"os": "27"}}) == "27"
    assert scoring.os_era({"versions": {"os": "garbage"}}) == "unknown"
    assert scoring.os_era({"versions": {"os": ""}}) == "unknown"
    assert scoring.os_era({"versions": {}}) == "26"


def test_matrix_names_the_by_equivalence_pairs_and_their_tmux_rows(fixtures):
    text = render_matrix(records(fixtures), 0.0)
    assert "By equivalence (R34): `zmx-send` = `tmux-keys`, `zellij-write` = `tmux-keys`" in text
    assert "`zmx-paste` = `tmux-paste`, `zellij-paste` = `tmux-paste` for S3, S7 reps 2-3, S10, S11, S12" in text


def test_an_s12_delivery_after_the_bridge_respawned_the_agent_is_not_good():
    base = {"scenario": "S12", "delivery": "delivered", "intact": None, "harmful": False}
    assert scoring.is_good({**base, "notes": "backend-restart=gc supervisor stop+start"})
    respawned = {**base, "notes": "backend-restart=gc supervisor stop+start; agent-respawned-by-bridge"}
    assert scoring.is_good(respawned) is False
    assert scoring.cell_text(scoring.Tally().add(respawned)) == "0/1 · respawned 1"


def test_an_s10_whose_push_after_clear_went_to_the_old_session_did_not_exercise_compaction():
    base = {"scenario": "S10", "delivery": "delivered", "intact": True, "harmful": False}
    address_based = {**base, "notes": "clear=delivered@old-session; compact-warm-up; compact=delivered@old-session"}
    visible_session = {**base, "notes": "clear=delivered@new-session; compact=delivered@new-session"}
    assert scoring.cell_text(scoring.Tally().add(address_based)) == (
        "1/1 · compaction not exercised on the delivered session")
    assert scoring.cell_text(scoring.Tally().add(visible_session)) == "1/1"
