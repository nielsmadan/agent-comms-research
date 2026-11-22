import json
from pathlib import Path

from agentcomms.records import ResultRecord

RAW = Path(__file__).resolve().parent.parent / "results" / "raw.jsonl"


def test_every_committed_record_parses():
    lines = RAW.read_text().splitlines()
    records = [ResultRecord.from_dict(json.loads(line)) for line in lines]
    assert len(records) == len(lines) > 0
