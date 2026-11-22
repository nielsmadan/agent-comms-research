import json
import os
import shutil
import sqlite3
from pathlib import Path

from agentcomms import isolation
from agentcomms.transcripts import opencode
from agentcomms.transcripts.droid import DroidTranscript, cwd_slug, parse_record
from agentcomms.transcripts.opencode import OpenCodeTranscript, db_path, merge_entries, parse_queued
from agentcomms.transcripts.pi import PiTranscript, idle_from_records

PI_CWD = "/Users/me/wrksp/_scratch/agent-comms/runs/20261024-154919-6441/work/pi"
OPENCODE_CWD = "/Users/me/wrksp/_scratch/agent-comms/runs/20261024-154928-e5ee/work/opencode"
DROID_CWD = "/Users/me/wrksp/_scratch/agent-comms/runs/20261024-154942-15e7/work/droid"


def build_db(fixture: Path, home: Path) -> Path:
    spec = json.loads(fixture.read_text())
    path = db_path(home)
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as conn:
        for statement in spec["schema"]:
            conn.execute(statement)
        for table, rows in spec["rows"].items():
            for row in rows:
                cols = list(row)
                conn.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                             [row[c] for c in cols])
    return path


def test_pi_parser_extracts_pilot_entries(fixtures):
    t = PiTranscript(fixtures / "pi" / "s1-pilot.jsonl")
    assert [(k, text) for _, k, text in t.entries()] == [
        ("user", 'ACK-REQUEST 40412ec2: reply with exactly "ACK 40412ec2". This is an idle-wake test from the '
                 "agentcomms harness; no other action is needed."),
        ("assistant", "ACK 40412ec2"),
    ]
    assert t.is_idle() is True
    assert t.session_id() == "7fbd7f59-eff5-41cb-bfb1-4a330fd0ad70"


def test_pi_custom_entries_are_kind_custom(fixtures):
    t = PiTranscript(fixtures / "pi" / "custom.jsonl")
    assert [k for _, k, _ in t.find_token("c0ffee01")] == ["custom", "assistant"]
    assert [text for _, k, text in t.entries() if k == "custom"] == [
        '{"marker": "custom-entry-marker"}',
        'ACK-REQUEST c0ffee01: reply with exactly "ACK c0ffee01". custom-message',
    ]


def test_pi_session_lookup_matches_cwd_and_id(tmp_path, fixtures):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    wanted = sessions / "2026-10-24T20-49-19-767Z_7fbd7f59-eff5-41cb-bfb1-4a330fd0ad70.jsonl"
    shutil.copy(fixtures / "pi" / "s1-pilot.jsonl", wanted)
    shutil.copy(fixtures / "pi" / "custom.jsonl", sessions / "2026-10-24T20-50-20-160Z_d361f923.jsonl")
    assert PiTranscript.locate(sessions, Path(PI_CWD)).path == wanted
    assert PiTranscript.locate(sessions, Path(PI_CWD), "7fbd7f59-eff5-41cb-bfb1-4a330fd0ad70").path == wanted


def test_opencode_step_aborted_by_a_declined_permission_is_not_an_api_error():
    row = {"type": "assistant", "time_created": 1793168157525, "data": json.dumps({
        "content": [], "error": {"type": "aborted", "message": "Step interrupted"}})}
    rate = {"type": "assistant", "time_created": 1793168157525, "data": json.dumps({
        "content": [], "error": {"type": "api", "message": "429 rate limited"}})}
    assert [(k, t) for _, k, t in opencode.parse_message(row)] == [("system", "aborted: Step interrupted")]
    assert [(k, t) for _, k, t in opencode.parse_message(rate)] == [("api_error", "429 rate limited")]


def test_opencode_prompt_found_in_message_table(tmp_path, fixtures):
    build_db(fixtures / "opencode" / "s1-pilot.json", tmp_path)
    t = OpenCodeTranscript.locate(tmp_path, Path(OPENCODE_CWD))
    assert t.session_id() == "ses_e905308ccffeeXSjW1kXCCAOY0"
    hits = t.find_token("c87261aa")
    assert [k for _, k, _ in hits] == ["user", "assistant"]
    assert hits[1][2] == "ACK c87261aa"
    assert t.is_idle() is True


def test_every_opencode_session_of_the_work_dir_is_searchable_after_new(tmp_path, fixtures):
    path = build_db(fixtures / "opencode" / "s1-pilot.json", tmp_path)
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT * FROM session_v2").fetchone()
        cols = [d[0] for d in conn.execute("SELECT * FROM session_v2").description]
        old = dict(zip(cols, row, strict=True))
        newer = old | {"id": "ses_newer", "time_created": old["time_created"] + 1}
        conn.execute(f"INSERT INTO session_v2 ({','.join(newer)}) VALUES ({','.join('?' * len(newer))})",
                     list(newer.values()))
    found = OpenCodeTranscript.locate_all(tmp_path, Path(OPENCODE_CWD))
    assert [t.session_id() for t in found] == ["ses_newer", "ses_e905308ccffeeXSjW1kXCCAOY0"]
    assert [t.session_id() for t in found if t.find_token("c87261aa")] == ["ses_e905308ccffeeXSjW1kXCCAOY0"]


def test_opencode_prompt_found_in_inbox_table_while_busy(tmp_path, fixtures):
    build_db(fixtures / "opencode" / "inbox.json", tmp_path)
    t = OpenCodeTranscript.locate(tmp_path, Path("/Users/me/wrksp/_scratch/agent-comms/runs/20261024-154209-3fff/"
                                                 "work/opencode"))
    assert [(k, text) for _, k, text in t.find_token("cafe0004")] == [
        ("queue", 'ACK-REQUEST cafe0004: reply with exactly "ACK cafe0004". queued probe')]
    assert t.is_idle() is False
    kinds = [k for _, k, _ in t.entries()]
    assert kinds.count("tool_use") == kinds.count("tool_result") == 2


def test_opencode_promoted_inbox_row_is_reported_once_as_user(fixtures):
    rows = json.loads((fixtures / "opencode" / "inbox.json").read_text())["rows"]
    inbox = rows["session_inbox"][0]
    promoted = {"id": inbox["id"], "type": "user", "seq": 47, "time_created": 1792874673300,
                "data": inbox["payload"]}
    entries = merge_entries([*rows["session_message"], promoted], [(inbox, "payload")])
    assert [k for _, k, t in entries if "cafe0004" in t] == ["user"]


def test_opencode_pending_row_payload_parses_like_inbox(fixtures):
    inbox = json.loads((fixtures / "opencode" / "inbox.json").read_text())["rows"]["session_inbox"][0]
    pending = {"id": inbox["id"], "data": inbox["payload"], "time_created": inbox["time_created"]}
    assert parse_queued(pending, "data") == parse_queued(inbox, "payload")
    assert parse_queued(pending, "data")[0][1] == "queue"


def test_droid_parser_keeps_only_typed_prompt_as_user(fixtures):
    t = DroidTranscript(fixtures / "droid" / "s1-pilot.jsonl")
    user = [text for _, k, text in t.entries() if k == "user"]
    assert user == ['ACK-REQUEST a9e28242: reply with exactly "ACK a9e28242". This is an idle-wake test from the '
                    "agentcomms harness; no other action is needed."]
    assert [text for _, k, text in t.entries() if k == "assistant"] == ["ACK a9e28242"]
    assert t.is_idle() is True


def test_droid_hook_and_reminder_records_are_system(fixtures):
    t = DroidTranscript(fixtures / "droid" / "hooks.jsonl")
    entries = t.entries()
    assert [text for _, k, text in entries if k == "user"] == [
        'ACK-REQUEST cafe0006: reply with exactly "ACK cafe0006". hook probe']
    system = [text for _, k, text in entries if k == "system"]
    assert system[0].startswith("hook:SessionStart\n")
    assert "hook-context-marker" in system[1]
    assert sum(text.startswith("<system-reminder>") for text in system) == 6
    assert system[-1] == "turn_outcome:completed"


def test_droid_session_lookup_by_cwd_slug(tmp_path, fixtures):
    slug_dir = tmp_path / ".factory" / "sessions" / cwd_slug(Path(DROID_CWD))
    slug_dir.mkdir(parents=True)
    wanted = slug_dir / "7bf99072-3e6f-4eb3-99e3-2e095fe088e0.jsonl"
    shutil.copy(fixtures / "droid" / "s1-pilot.jsonl", wanted)
    (slug_dir / "7bf99072-3e6f-4eb3-99e3-2e095fe088e0.settings.json").write_text("{}")
    found = DroidTranscript.locate(tmp_path, Path(DROID_CWD))
    assert found.path == wanted
    assert found.session_id() == "7bf99072-3e6f-4eb3-99e3-2e095fe088e0"
    assert cwd_slug(Path(DROID_CWD)) == "-Users-me-wrksp-_scratch-agent-comms-runs-20261024-154942-15e7-work-droid"


def test_droid_turn_without_outcome_is_busy(fixtures):
    lines = (fixtures / "droid" / "s1-pilot.jsonl").read_text().splitlines()
    from agentcomms.transcripts.droid import idle_from_records
    assert idle_from_records([json.loads(line) for line in lines[:3]]) is False


def with_header(source: Path, dest: Path, **changes) -> Path:
    lines = source.read_text().splitlines()
    dest.write_text("\n".join([json.dumps(json.loads(lines[0]) | changes), *lines[1:]]) + "\n")
    return dest


def test_pi_session_lookup_picks_id_among_same_cwd_sessions(tmp_path, fixtures):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    pilot = fixtures / "pi" / "s1-pilot.jsonl"
    wanted = with_header(pilot, sessions / "a.jsonl")
    newer = with_header(pilot, sessions / "b.jsonl", id="11111111-0000-4000-8000-000000000000",
                        timestamp="2026-10-24T21:00:00.000Z")
    assert PiTranscript.locate(sessions, Path(PI_CWD), "7fbd7f59-eff5-41cb-bfb1-4a330fd0ad70").path == wanted
    assert PiTranscript.locate(sessions, Path(PI_CWD)).path == newer


def pi_records(fixtures: Path) -> list[dict]:
    return [json.loads(line) for line in (fixtures / "pi" / "s1-pilot.jsonl").read_text().splitlines()]


def test_pi_trailing_custom_message_is_unknown_because_turn_trigger_is_not_recorded(fixtures):
    notice = {"type": "custom_message", "customType": "ext", "content": "notice", "display": True, "id": "n1"}
    custom = {"type": "custom", "customType": "ext", "data": {}, "id": "c1"}
    assert idle_from_records([*pi_records(fixtures), notice]) is None
    assert idle_from_records([*pi_records(fixtures), notice, custom]) is None
    assert idle_from_records([*pi_records(fixtures), custom]) is True


def test_pi_tool_use_stop_reason_is_busy(fixtures):
    records = pi_records(fixtures)
    last = records[-1] | {"message": records[-1]["message"] | {"stopReason": "toolUse"}}
    assert idle_from_records([*records[:-1], last]) is False


def add_rows(path: Path, sql: str, rows: list[tuple]) -> None:
    with sqlite3.connect(path) as conn:
        conn.executemany(sql, rows)


def test_opencode_locate_by_session_id_ignores_child_sessions(tmp_path, fixtures):
    path = build_db(fixtures / "opencode" / "s1-pilot.json", tmp_path)
    add_rows(path, "INSERT INTO session_v2 (id, project_id, parent_id, slug, directory, path, version, time_created, "
                   "time_updated) VALUES (?, 'p', ?, 's', ?, 'w', '2.1.4', ?, ?)",
             [("ses_child", "ses_e905308ccffeeXSjW1kXCCAOY0", OPENCODE_CWD, 1792874999999, 1792874999999)])
    parent = "ses_e905308ccffeeXSjW1kXCCAOY0"
    assert OpenCodeTranscript.locate(tmp_path, Path(OPENCODE_CWD), parent).session_id() == parent
    assert OpenCodeTranscript.locate(tmp_path, Path(OPENCODE_CWD)).session_id() == parent
    assert OpenCodeTranscript.locate(tmp_path, Path(OPENCODE_CWD), "ses_child") is None
    assert OpenCodeTranscript.locate(tmp_path, Path(OPENCODE_CWD), "ses_missing") is None


def test_opencode_reads_messages_and_queues_in_one_connection(tmp_path, fixtures, monkeypatch):
    build_db(fixtures / "opencode" / "inbox.json", tmp_path)
    t = OpenCodeTranscript.locate(tmp_path, Path("/Users/me/wrksp/_scratch/agent-comms/runs/20261024-154209-3fff/"
                                                 "work/opencode"))
    opened = []
    real = opencode.connect_ro
    monkeypatch.setattr(opencode, "connect_ro", lambda p: opened.append(p) or real(p))
    assert t.is_idle() is False
    assert [k for _, k, _ in t.find_token("cafe0004")] == ["queue"]
    assert opened == [t.path, t.path]


def test_opencode_credential_purge_keeps_transcript_tables(tmp_path, fixtures):
    path = build_db(fixtures / "opencode" / "s1-pilot.json", tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE credential (id text PRIMARY KEY, integration_id text, label text NOT NULL, "
                     "value text NOT NULL, time_created integer NOT NULL, time_updated integer NOT NULL)")
        conn.execute("INSERT INTO credential VALUES ('c1', 'opencode', 'API key', 'secret-marker-x9', 1, 1)")
    assert isolation.purge_credentials(path) == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM credential").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM session_message").fetchone() == (3,)
    on_disk = b"".join(p.read_bytes() for p in path.parent.glob("opencode.db*"))
    assert b"secret-marker-x9" not in on_disk
    assert OpenCodeTranscript.locate(tmp_path, Path(OPENCODE_CWD)).find_token("c87261aa")[1][2] == "ACK c87261aa"


def test_droid_session_lookup_picks_id_or_newest_among_same_cwd(tmp_path, fixtures):
    slug_dir = tmp_path / ".factory" / "sessions" / cwd_slug(Path(DROID_CWD))
    slug_dir.mkdir(parents=True)
    pilot = fixtures / "droid" / "s1-pilot.jsonl"
    wanted = with_header(pilot, slug_dir / "7bf99072-3e6f-4eb3-99e3-2e095fe088e0.jsonl")
    newer = with_header(pilot, slug_dir / "22222222.jsonl", id="22222222")
    os.utime(wanted, (1_000_000, 1_000_000))
    assert DroidTranscript.locate(tmp_path, Path(DROID_CWD)).path == newer
    assert DroidTranscript.locate(tmp_path, Path(DROID_CWD), "7bf99072-3e6f-4eb3-99e3-2e095fe088e0").path == wanted


def test_droid_session_lookup_falls_back_to_any_slug_dir(tmp_path, fixtures):
    other = tmp_path / ".factory" / "sessions" / "renamed-slug"
    other.mkdir(parents=True)
    wanted = with_header(fixtures / "droid" / "s1-pilot.jsonl", other / "s.jsonl")
    assert DroidTranscript.locate(tmp_path, Path(DROID_CWD)).path == wanted


def test_droid_error_turn_outcome_is_api_error():
    assert parse_record({"type": "agent_turn_outcome", "reason": "error"}, 5.0) == [
        (5.0, "api_error", "turn_outcome:error")]
