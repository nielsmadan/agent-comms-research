import json
from pathlib import Path

from agentcomms.manifest import manifest_from_dict, manifest_to_dict
from agentcomms.model import Ack, Delivery, DraftFate, Manifest, Target
from agentcomms.records import FIELD_ORDER, ResultRecord, sha256

DOCUMENTED = {
    "run_id": "20261024-101500-a1b2", "stage": "screen", "agent": "codex",
    "versions": {"codex": "0.163.0", "codex_daemon": "0.164.0"},
    "mechanism": "codex-queue", "host": "tmux", "backend": "codex-daemon",
    "scenario": "S7", "rep": 1, "sandbox": "raw",
    "delivery": "delivered", "intact": True, "draft_fate": "preserved", "ack": "acked",
    "harmful": False, "retries": 0, "latency_s": 18.2,
    "evidence": ["transcript", "pane"], "sent_sha256": "…", "recv_sha256": "…",
    "notes": "", "ts": 1792850100.0,
}


def test_enum_values_match_documented_strings():
    assert [d.value for d in Delivery] == [
        "delivered", "queued", "interrupted", "rejected", "lost", "held", "n/a", "error", "env_error"]
    assert [d.value for d in DraftFate] == ["preserved", "submitted", "merged", "lost", "n/a"]
    assert [a.value for a in Ack] == ["acked", "model_noncompliant", "none"]


def test_record_serialises_to_documented_json():
    record = ResultRecord.from_dict(DOCUMENTED)
    assert json.loads(record.to_json()) == DOCUMENTED | {"token": None}
    assert [k for k in record.to_dict() if k != "token"] == list(DOCUMENTED)
    assert list(record.to_dict()) == list(FIELD_ORDER)
    assert record.delivery is Delivery.DELIVERED


def test_sha256_of_text():
    assert sha256("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_manifest_round_trips_through_json():
    target = Target(run_id="r1", agent="claude", host="tmux", backend="none", work_dir=Path("/w"),
                    home_dir=Path("/h"), session_id="s", host_ref="agentcomms:r1-claude", backend_ref=None,
                    transcript=Path("/h/t.jsonl"), agent_pid=42)
    m = Manifest(run_id="r1", pgids=[7], targets=[target], sockets=[Path("/tmp/ac/x.sock")],
                 backends=[])
    assert manifest_from_dict(json.loads(json.dumps(manifest_to_dict(m)))) == m


def test_record_carries_the_message_tokens():
    record = ResultRecord.from_dict(DOCUMENTED | {"token": "0a1b2c3d"})
    assert record.to_dict()["token"] == "0a1b2c3d"
