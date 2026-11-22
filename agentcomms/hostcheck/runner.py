import json
import sys
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from agentcomms import manifest, procs
from agentcomms.adapters import ADAPTERS, make_adapter
from agentcomms.engine import Engine, pid_or_stop
from agentcomms.hostcheck import analysis
from agentcomms.hosts import state_dir_for
from agentcomms.hosts.errors import HostError
from agentcomms.model import Manifest, Target
from agentcomms.paths import SOCKET_DIR

RECORDER = Path(__file__).with_name("recorder.py")
QUIET_S = 0.8
SETTLE_TIMEOUT_S = 8.0
READY_TIMEOUT_S = 15.0
HOST_KINDS = ("tmux", "zmx", "zellij", "iterm2")


@dataclass
class AdapterResult:
    host: str
    adapter: str
    summary: analysis.Summary | None
    cases: list[analysis.CaseResult]
    burst: analysis.BurstResult | None
    blocked: str | None = None
    notes: list[str] = field(default_factory=list)


def host_adapters(kind: str, only: list[str] | None = None) -> list[str]:
    names = [name for name, cls in ADAPTERS.items() if getattr(cls, "host_kind", "tmux") == kind
             and cls.kind == "terminal"]
    return [n for n in names if only is None or n in only]


def read_all(log: Path) -> tuple[dict, list[analysis.Read]]:
    return analysis.parse_log(log.read_text(errors="replace")) if log.exists() else ({}, [])


def wait_quiet(log: Path, since: int, quiet_s: float = QUIET_S, timeout_s: float = SETTLE_TIMEOUT_S) -> None:
    deadline = time.monotonic() + timeout_s
    last_count, last_change = since, time.monotonic()
    while time.monotonic() < deadline:
        count = len(read_all(log)[1])
        if count != last_count:
            last_count, last_change = count, time.monotonic()
        elif count > since and time.monotonic() - last_change >= quiet_s:
            return
        time.sleep(0.15)


def wait_ready(log: Path, timeout_s: float = READY_TIMEOUT_S) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        meta, _ = read_all(log)
        if meta.get("ready"):
            return meta
        time.sleep(0.2)
    raise HostError("the recorder never reported ready")


def run_adapter(engine: Engine, adapter, target: Target,
                log: Path) -> tuple[list[analysis.CaseResult], analysis.BurstResult]:
    cases = []
    for case, text in analysis.CASES.items():
        before = len(read_all(log)[1])
        engine.check_owned(target)
        adapter.send(target, text)
        wait_quiet(log, before)
        cases.append(analysis.analyze_case(case, text, read_all(log)[1][before:]))
    before = len(read_all(log)[1])
    for text in analysis.BURST:
        engine.check_owned(target)
        adapter.send(target, text)
    wait_quiet(log, before, timeout_s=SETTLE_TIMEOUT_S * 2)
    return cases, analysis.analyze_burst(analysis.BURST, read_all(log)[1][before:])


def start_recorder(engine: Engine, m: Manifest, kind: str, run_dir: Path) -> tuple[Manifest, Target, Path, dict]:
    host = engine.host_for(kind)
    log = run_dir / f"hostcheck-{kind}.log"
    work = run_dir / "work" / f"hostcheck-{kind}"
    work.mkdir(parents=True, exist_ok=True)
    name = f"{m.run_id}-hc-{kind}"
    argv = [sys.executable, "-I", str(RECORDER), str(log)]
    ref = host.start(name, argv, {"PATH": "/usr/bin:/bin", "TERM": host.term}, work,
                     run_dir / f"env-{name}.sh", state_dir_for(kind, m.run_id, SOCKET_DIR))
    root = pid_or_stop(host, ref)
    target = Target(m.run_id, "claude", kind, "none", work, work, None, ref, None, None, None)
    m = manifest.with_target(replace(m, pgids=[*m.pgids, procs.owned_group(procs.ps_rows(), root)]), target)
    manifest.save(engine.layout, m)
    return m, target, log, wait_ready(log)


def run_host(engine: Engine, m: Manifest, kind: str, only: list[str] | None) -> tuple[Manifest, list[AdapterResult]]:
    run_dir = engine.layout.run_dir(m.run_id)
    names = host_adapters(kind, only)
    try:
        m, target, log, meta = start_recorder(engine, m, kind, run_dir)
    except HostError as e:
        notes = engine.host_notes(kind)
        return m, [AdapterResult(kind, n, None, [], None, blocked=str(e), notes=notes) for n in names]
    results = []
    for name in names:
        adapter = make_adapter(name, engine.host_for)
        cases, burst = run_adapter(engine, adapter, target, log)
        results.append(AdapterResult(kind, name, analysis.summarize(cases, burst), cases, burst))
        results[-1].notes += engine.host_notes(kind)
        (run_dir / f"hostcheck-{kind}-{name}.json").write_text(json.dumps(
            {"meta": meta, "cases": [asdict(c) for c in cases], "burst": asdict(burst)}, indent=1, default=str))
    return m, results


def row_order(row: dict) -> tuple[int, int]:
    adapters = list(ADAPTERS)
    return (HOST_KINDS.index(row["host"]) if row["host"] in HOST_KINDS else len(HOST_KINDS),
            adapters.index(row["adapter"]) if row["adapter"] in adapters else len(adapters))


def merge_rows(old: list[dict], new: list[dict]) -> list[dict]:
    replaced = {(r["host"], r["adapter"]) for r in new}
    return sorted([r for r in old if (r["host"], r["adapter"]) not in replaced] + new, key=row_order)


def render_rows(rows: list[dict]) -> str:
    done = [(r["host"], r["adapter"], analysis.Summary(**r["summary"])) for r in rows if r["summary"]]
    blocked = [f"- {r['host']} / {r['adapter']}: blocked: {r['blocked']}" for r in rows if r["blocked"]]
    notes = [f"- {r['host']} / {r['adapter']}: {'; '.join(r['notes'])}" for r in rows if r.get("notes")]
    return (analysis.render_table(done) + ("\nBlocked:\n" + "\n".join(blocked) + "\n" if blocked else "")
            + ("\nHost notes:\n" + "\n".join(notes) + "\n" if notes else ""))


def render(results: list[AdapterResult]) -> str:
    return render_rows(to_json(results))


def to_json(results: list[AdapterResult]) -> list[dict]:
    return [{"host": r.host, "adapter": r.adapter, "blocked": r.blocked, "notes": r.notes,
             "summary": asdict(r.summary) if r.summary else None,
             "cases": [asdict(c) | {"sizes": list(c.sizes)} for c in r.cases],
             "burst": asdict(r.burst) if r.burst else None} for r in results]
