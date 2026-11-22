import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TMUX_SOCKET = "agentcomms"
SOCKET_DIR = Path("/tmp/ac")
DEFERRED_LOG = "deferred.log"
RUN_ID = re.compile(r"\A\d{8}-\d{6}-[0-9A-Za-z]{4}\Z")


@dataclass(frozen=True)
class Layout:
    root: Path

    @property
    def runs(self) -> Path:
        return self.root / "runs"

    @property
    def results(self) -> Path:
        return self.root / "results"

    @property
    def raw_jsonl(self) -> Path:
        return self.results / "raw.jsonl"

    @property
    def progress_md(self) -> Path:
        return self.results / "progress.md"

    @property
    def matrix_md(self) -> Path:
        return self.results / "matrix.md"

    @property
    def tmux_conf(self) -> Path:
        return self.root / "tmux.conf"

    def run_dir(self, run_id: str) -> Path:
        return self.runs / run_id

    def work_dir(self, run_id: str, agent: str) -> Path:
        return self.run_dir(run_id) / "work" / agent

    def home_dir(self, run_id: str, agent: str) -> Path:
        return self.run_dir(run_id) / "home" / agent

    def manifest_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "manifest.json"


def default_layout() -> Layout:
    return Layout(Path(os.environ.get("AGENTCOMMS_ROOT", REPO_ROOT)).resolve())


def new_run_id(now: float, suffix: str | None = None) -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + "-" + (suffix or secrets.token_hex(2))


def valid_run_id(run_id: str) -> bool:
    return bool(RUN_ID.match(run_id))
