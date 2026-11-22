import argparse
import contextlib
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from pathlib import Path

from agentcomms import (
    checkpoint,
    isolation,
    manifest,
    markers,
    procs,
    profiles,
    report,
    sandbox,
    scale,
    scenarios,
    shortlist,
    userconfig,
)
from agentcomms.adapters import (
    ADAPTER_NAMES,
    adapter_agents,
    adapter_backend,
    adapter_host,
    adapter_shared_state,
    make_adapter,
)
from agentcomms.engine import Engine, UnsupportedAdapterError, failure_note, require_supported
from agentcomms.hosts.errors import HostError
from agentcomms.model import Delivery, Manifest
from agentcomms.paths import default_layout, new_run_id, valid_run_id
from agentcomms.records import ResultRecord

AGENTS = ("claude", "codex", "pi", "opencode", "droid")
SCENARIOS = tuple(scenarios.SCENARIOS)
HOSTCHECK_HOSTS = ("tmux", "zmx", "zellij", "iterm2")
STAGES = ("pilot", "screen", "extensive", "shortlist", "nono", userconfig.STAGE)
CELL_ERRORS = (RuntimeError, TimeoutError, HostError, OSError, isolation.IsolationError, profiles.ProfileError,
               subprocess.SubprocessError)
CELL_ERROR = 6
PAUSED = 10
LIVE_RUN = 11
HARNESS_BUG = 12
STOP_STATUSES = frozenset({3, 4, 5, 7, 8, 9, LIVE_RUN, HARNESS_BUG})
PAUSE_MARKERS = markers.PAUSES
CRASH = markers.CRASH
CRASH_LIMIT = 2
SANDBOXED = 13
S9_EXCLUDED = frozenset({"codex-queue-embedded"})
NONO_EXCLUDED = frozenset({"gc-nudge"})
UNVERIFIABLE = "unverifiable: "
SANDBOX_MODES = ("raw", "nono")
SANDBOX_HELP = ("raw refuses to run from a sandboxed coordinator; nono runs receiver, backend and harness-side "
                "sender under `nono run -p <agent>-local` with the user's launcher env (agentcomms/sandbox.py)")


def probe_sandbox(run) -> str | None:
    try:
        out = run(["nono", "why", "--self"], capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        return None
    except (subprocess.TimeoutExpired, OSError) as e:
        return f"{UNVERIFIABLE}{type(e).__name__}"
    if "NOT SANDBOXED" in out.stdout:
        return None
    return out.stdout.strip().splitlines()[0] if out.stdout.strip() else f"{UNVERIFIABLE}exit {out.returncode}"


def coordinator_sandbox() -> str | None:
    return probe_sandbox(subprocess.run)


def sandbox_refusal(sandbox: str, probe, wrapper=profiles.nono_wrapper) -> str | None:
    if sandbox == "nono":
        if wrapper() is None:
            return ("refused: --sandbox nono needs the nono launcher wrapper: nono on PATH and every "
                    "<agent>-local profile")
        return None
    state = probe()
    if state is None:
        return None
    advice = "Run live cells from an unsandboxed session, or use --sandbox nono"
    if state.startswith(UNVERIFIABLE):
        return (f"refused: could not verify that the coordinator is unsandboxed ({state}); failing closed, since "
                f"receivers would inherit a sandbox profile. {advice}")
    return f"refused: the coordinator is sandboxed ({state}); receivers would inherit its profile. {advice}"


def refuse_if_sandboxed(args) -> int | None:
    reason = sandbox_refusal(getattr(args, "sandbox", "raw"), coordinator_sandbox, profiles.nono_wrapper)
    if reason:
        print(reason, file=sys.stderr)
        return SANDBOXED
    return None


def user_home() -> str:
    return os.environ.get("HOME") or str(Path.home())


def bridge_guard(layout, before: dict, label: str, run_id: str | None = None) -> int:
    home = user_home()
    try:
        delta = isolation.bridge_delta(before, isolation.bridge_snapshot(home), home)
        note = isolation.append_note(delta.appends, home, isolation.gc_supervisors(procs.ps_rows(),
                                                                                  layout.root / "vendor"))
    except OSError as e:
        print(f"STOP: bridge-state check after {label} failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 5
    lines = [*(f"changed: {isolation.tildify(p, home)}" for p in delta.stops), *([note] if note else [])]
    if run_id and lines and layout.run_dir(run_id).is_dir():
        with open(layout.run_dir(run_id) / "bridge-guard.txt", "a") as f:
            f.write("".join(f"{label}: {line}\n" for line in lines))
    if note:
        print(note, file=sys.stderr)
    if delta.stops:
        shown = ", ".join(isolation.tildify(p, home) for p in delta.stops[:5])
        print(f"STOP: bridge state in the user's home changed during {label}: {shown}", file=sys.stderr)
        return 5
    return 0


def cmd_launch(args) -> int:
    layout = default_layout()
    before = isolation.bridge_snapshot(user_home())
    engine = Engine(layout, sandbox=args.sandbox)
    adapter = make_adapter(args.adapter, engine.host_for)
    try:
        require_supported(adapter, args.agent)
    except UnsupportedAdapterError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    try:
        m = engine.new_run()
    except manifest.LiveRunError as e:
        print(f"refused: {e}", file=sys.stderr)
        return LIVE_RUN
    launched = None
    try:
        m, launched = engine.launch(m, args.agent, args.mode, adapter)
    except CELL_ERRORS as e:
        print(f"launch failed for run {m.run_id}: {failure_note(e)}", file=sys.stderr)
        for line in manifest.cleanup(layout, m.run_id):
            print(f"cleanup: {line}", file=sys.stderr)
    finally:
        guarded = bridge_guard(layout, before, f"launch {m.run_id}", m.run_id)
    if launched is None:
        return guarded or 1
    print(f"run_id: {m.run_id}")
    print(f"host_ref: {launched.target.host_ref}")
    print(f"ready: {launched.ready_signal}")
    print(f"attach: {engine.host_of(launched.target).attach_command(launched.target.host_ref)}")
    return guarded


def cmd_send(args) -> int:
    layout = default_layout()
    m = manifest.load(layout, args.run) if valid_run_id(args.run) else None
    if m is None:
        print(f"unknown run id: {args.run}", file=sys.stderr)
        return 2
    try:
        target = manifest.owned_target(m, layout.runs, agent=args.agent, host_ref=args.host_ref)
        manifest.assert_owned(m, target, layout.runs, procs.ps_rows())
    except manifest.OwnershipError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 7
    before = isolation.bridge_snapshot(user_home())
    engine = Engine(layout)
    text = args.text if args.text is not None else sys.stdin.read()
    adapter = make_adapter(args.adapter, engine.host_for)
    try:
        require_supported(adapter, target.agent)
    except UnsupportedAdapterError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    try:
        receipt = adapter.send(target, text)
        engine.track_spawned(manifest.load(layout, args.run) or m, receipt.spawned)
    finally:
        guarded = bridge_guard(layout, before, f"send {args.run}", args.run)
    print(f"accepted={receipt.accepted} retries={receipt.retries} {receipt.detail}".strip())
    return guarded or (0 if receipt.accepted else 1)


def make_cell(stage: str, agent: str, adapter: str, scenario: str, rep: int, sandbox: str = "raw") -> dict:
    return {"stage": stage, "agent": agent, "mechanism": adapter, "host": adapter_host(adapter),
            "backend": adapter_backend(adapter, agent), "scenario": scenario, "rep": rep, "sandbox": sandbox}


@dataclass(frozen=True)
class CellResult:
    status: int
    record: dict | None


def record_and_print(layout, record) -> dict:
    checkpoint.append_record(layout.raw_jsonl, record.to_dict())
    print(record.to_json(), flush=True)
    return record.to_dict()


def fail_cell(layout, engine: Engine, progress, m, cell: dict, error: Exception,
              versions: dict | None = None) -> dict:
    record = engine.failure_record(m, cell["agent"], cell["mechanism"], cell["stage"], cell["scenario"],
                                   cell["rep"], versions or {}, error, cell["backend"], cell["host"])
    progress.open_issues.append(f"{cell['agent']} {cell['mechanism']} {cell['scenario']}: {record.notes}")
    return record_and_print(layout, record)


def stop(progress, problem: str, status: int) -> int:
    progress.open_issues.append(problem)
    print(f"STOP: {problem}", file=sys.stderr)
    return status


def version_problem(engine: Engine, launched) -> str | None:
    try:
        return None if engine.check_versions(launched) else "version changed mid-run"
    except CELL_ERRORS as e:
        return f"version re-check failed ({type(e).__name__}: {e})"


def unlaunched_record(layout, engine: Engine, cell: dict, delivery: Delivery, note: str) -> dict:
    m = Manifest(new_run_id(time.time()), [], [], [], [])
    record = engine.plain_record(m, cell["agent"], cell["mechanism"], cell["stage"], cell["scenario"], cell["rep"],
                                 {}, delivery, note, cell["backend"], cell["host"])
    return record_and_print(layout, record)


def not_applicable_cell(layout, engine: Engine, cell: dict, reason: str) -> CellResult:
    return CellResult(0, unlaunched_record(layout, engine, cell, Delivery.NA, f"n/a: {reason}"))


def pauses_batch(record: dict | None) -> bool:
    return (bool(record) and record["delivery"] == Delivery.ENV_ERROR
            and any(marker in record["notes"] for marker in PAUSE_MARKERS))


def crash_verdict(record: ResultRecord, prior: list[dict]) -> ResultRecord:
    if record.delivery != Delivery.ENV_ERROR or CRASH not in record.notes:
        return record
    key = checkpoint.cell_key(record.to_dict())
    crashes = 1 + sum(1 for r in prior if checkpoint.cell_key(r) == key and r["delivery"] == Delivery.ENV_ERROR
                      and CRASH in r["notes"])
    if crashes < CRASH_LIMIT:
        return record
    notes = record.notes.replace(CRASH, f"{CRASH}-repeatedly (crash {crashes})", 1)
    return replace(record, delivery=Delivery.ERROR, notes=notes)


def harness_bug(layout, engine: Engine, progress, m: Manifest, cell: dict, error: Exception,
                versions: dict | None) -> tuple[int, dict]:
    path = layout.run_dir(m.run_id) / "traceback.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(traceback.format_exception(error)))
    where = path.relative_to(layout.root)
    note = f"harness-bug: {failure_note(error)}; traceback={where}"
    record = engine.plain_record(m, cell["agent"], cell["mechanism"], cell["stage"], cell["scenario"], cell["rep"],
                                 versions or {}, Delivery.ERROR, note, cell["backend"], cell["host"])
    status = stop(progress, f"harness bug in {cell['agent']} {cell['mechanism']} {cell['scenario']}: "
                            f"{type(error).__name__}: {error} (see {where})", HARNESS_BUG)
    return status, record_and_print(layout, record)


def cell_failure(layout, engine: Engine, progress, m: Manifest, cell: dict, error: Exception,
                 versions: dict | None) -> tuple[int, dict | None]:
    if isinstance(error, manifest.OwnershipError):
        return stop(progress, f"ownership check failed for run {m.run_id}: {error}", 7), None
    if isinstance(error, userconfig.UserConfigSkip):
        return 0, record_and_print(layout, engine.plain_record(m, cell["agent"], cell["mechanism"], cell["stage"],
                                                               cell["scenario"], cell["rep"], {}, Delivery.NA,
                                                               f"n/a: {error}", cell["backend"], cell["host"]))
    if isinstance(error, CELL_ERRORS):
        record = fail_cell(layout, engine, progress, m, cell, error, versions)
        return record_status(record), record
    return harness_bug(layout, engine, progress, m, cell, error, versions)


def record_status(record: dict | None) -> int:
    if not record:
        return 0
    if record["delivery"] == Delivery.ERROR:
        return CELL_ERROR
    return PAUSED if pauses_batch(record) else 0


def no_exclusions() -> frozenset[str]:
    return frozenset()


def run_one(layout, progress, cell: dict, keep: bool = False, mode: str | None = None,
            exclude=no_exclusions, on_run=None, kill_server: bool = True) -> CellResult:
    engine = Engine(layout, sandbox=cell["sandbox"], user_config=cell["stage"] == userconfig.STAGE)
    scenario = scenarios.SCENARIOS[cell["scenario"]]
    try:
        adapter = make_adapter(cell["mechanism"], engine.host_for)
    except KeyError as e:
        return CellResult(CELL_ERROR, unlaunched_record(layout, engine, cell, Delivery.ERROR, str(e)))
    agent = cell["agent"]
    if agent not in adapter.agents:
        return not_applicable_cell(layout, engine, cell, f"adapter {adapter.name} does not support {agent}")
    reason = scenarios.cell_not_applicable(cell["scenario"], agent, cell["backend"], adapter)
    if reason:
        return not_applicable_cell(layout, engine, cell, reason)
    if engine.user_config:
        skipped = userconfig.skip_reason(userconfig.inventory(agent, Path(engine.user_home), layout.runs),
                                         adapter.name)
        if skipped:
            return not_applicable_cell(layout, engine, cell, skipped)
    base = baseline([agent], engine.user_config)
    try:
        m = engine.new_run(exclude())
    except manifest.LiveRunError as e:
        return CellResult(stop(progress, str(e), LIVE_RUN), None)
    if on_run:
        on_run(m.run_id)
    if engine.sandbox == "nono":
        adapter = sandbox.sandboxed_adapter(adapter, agent, engine.require_nono(), Path(engine.user_home),
                                            isolation.base_env(engine.environ))
    print(f"run_id: {m.run_id} ({agent} {cell['mechanism']} {cell['scenario']} rep {cell['rep']})", flush=True)
    status, record = 0, None
    try:
        launched = None
        try:
            m, launched = engine.launch(m, agent, mode or scenario.mode, adapter)
            print(f"attach: {engine.host_of(launched.target).attach_command(launched.target.host_ref)}", flush=True)
            result = engine.run_cell(m, launched, adapter, cell["scenario"], cell["stage"], cell["rep"])
        except Exception as e:  # every cell failure goes through the one ladder in cell_failure
            m = manifest.load(layout, m.run_id) or m
            status, record = cell_failure(layout, engine, progress, m, cell, e,
                                          launched.versions if launched else None)
        else:
            result = crash_verdict(result, checkpoint.load_records(layout.raw_jsonl))
            if base.stores:
                note = store_writes_note(layout, m.run_id, store_writes(layout, m.run_id, base))
                result = replace(result, notes=f"{result.notes}; {note}")
            record = record_and_print(layout, result)
            status = record_status(record)
            m = manifest.load(layout, m.run_id) or m
            m = engine.resolved_session(m, launched.target)
            problem = version_problem(engine, launched)
            if problem:
                status = stop(progress, f"{agent} {problem}; batch aborted", 3)
    finally:
        status = after_run(layout, engine, progress, m, status, base, keep, kill_server)
    return CellResult(status, record)


@dataclass(frozen=True)
class Baseline:
    hashes: dict
    texts: dict
    states: dict
    bridges: dict
    stores: dict


def baseline(agents: list[str], user_config: bool = False) -> Baseline:
    home = Path(user_home())
    return Baseline(isolation.global_config_hashes(), isolation.read_texts([isolation.CHURNING_CONFIG]),
                    {a: isolation.user_state_mtimes(a) for a in dict.fromkeys(agents)},
                    isolation.bridge_snapshot(str(home)),
                    {a: isolation.user_store_mtimes(a, home) for a in dict.fromkeys(agents)} if user_config else {})


def store_writes(layout, run_id: str, base: Baseline) -> list[str]:
    home = Path(user_home())
    paths = sorted({p for a, before in base.stores.items()
                    for p in isolation.changed_paths(before, isolation.user_store_mtimes(a, home))})
    if base.stores and layout.run_dir(run_id).is_dir():
        (layout.run_dir(run_id) / isolation.STORE_WRITES).write_text(isolation.store_writes_text(paths, str(home)))
    return paths


def store_writes_note(layout, run_id: str, paths: list[str]) -> str:
    where = (layout.run_dir(run_id) / isolation.STORE_WRITES).relative_to(layout.root)
    return f"user-store-writes={len(paths)} ({where})"


def after_run(layout, engine: Engine, progress, m: Manifest, status: int, base: Baseline, keep: bool = False,
              kill_server: bool = True) -> int:
    if not keep:
        try:
            for line in manifest.cleanup(layout, m.run_id, kill_server=kill_server):
                print(f"cleanup: {line}")
        except Exception as e:  # the safety checks below must run whatever cleanup raised
            status = stop(progress, f"cleanup of {m.run_id} failed: {type(e).__name__}: {e}", 8)
        else:
            left = manifest.remaining_pids(layout, m.run_id)
            if left:
                status = stop(progress, f"{len(left)} harness processes still running after cleanup of "
                                        f"{m.run_id}", 9)
    try:
        for problem in session_problems(layout, engine, m.run_id):
            status = stop(progress, problem, 4)
    except Exception as e:  # an unverifiable auth link is a stop, and the config check below must still run
        status = stop(progress, f"auth-link check for {m.run_id} failed: {type(e).__name__}: {e}", 4)
    try:
        after = isolation.global_config_hashes()
        changed = [k for k in base.hashes if base.hashes[k] != after[k]]
        ours, others = isolation.attribute_changes(base.hashes, after, base.texts, isolation.read_texts(changed),
                                                   str(layout.runs))
    except Exception as e:  # an unverifiable global config is a stop
        ours, others = [], []
        status = stop(progress, f"global config check for {m.run_id} failed: {type(e).__name__}: {e}", 5)
    if others:
        print(f"note: global config changed without reference to harness runs (live user sessions): "
              f"{', '.join(others)}", file=sys.stderr)
    if ours:
        status = stop(progress, f"global config references harness runs: {', '.join(ours)}", 5)
    for agent, state_before in base.states.items():
        try:
            touched = isolation.changed_paths(state_before, isolation.user_state_mtimes(agent))
            note = isolation.user_state_note(agent, touched, engine.user_home)
        except OSError as e:
            note = f"note: {agent} user state check failed: {type(e).__name__}: {e}"
        if note:
            print(note, file=sys.stderr)
    if base.stores:
        try:
            print(f"note: {store_writes_note(layout, m.run_id, store_writes(layout, m.run_id, base))} after cleanup",
                  file=sys.stderr)
        except OSError as e:
            print(f"note: user store check failed: {type(e).__name__}: {e}", file=sys.stderr)
    if bridge_guard(layout, base.bridges, m.run_id, m.run_id):
        status = stop(progress, f"bridge state in the user's home changed during {m.run_id} (see bridge-guard.txt)", 5)
    return status


def cmd_s9(args) -> int:
    from agentcomms.scenarios.s9 import Pair, Session, run_pair
    layout = default_layout()
    pair = Pair(args.a, args.b, args.fwd, args.back)
    engine = Engine(layout, sandbox=args.sandbox)
    fwd, back = make_adapter(pair.fwd, engine.host_for), make_adapter(pair.back, engine.host_for)
    if S9_EXCLUDED & {pair.fwd, pair.back}:
        print(f"refused: {', '.join(sorted(S9_EXCLUDED & {pair.fwd, pair.back}))} is not an S9 route (R30)",
              file=sys.stderr)
        return 2
    try:
        require_supported(fwd, pair.b)
        require_supported(back, pair.a)
    except UnsupportedAdapterError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    progress = checkpoint.ProgressWriter(layout.progress_md, layout.raw_jsonl, home=str(Path.home()))
    base = baseline([pair.a, pair.b])
    split = s9_split(pair.a, pair.b, getattr(fwd, "shared_run", False))
    try:
        m = engine.new_run()
        mb = engine.new_run(frozenset({m.run_id})) if split else m
    except manifest.LiveRunError as e:
        return stop(progress, str(e), LIVE_RUN)
    print(f"run_id: {m.run_id} (S9 {pair.a}>{pair.b} {pair.mechanism} rep {args.rep})"
          + (f"; B in run {mb.run_id}" if split else ""), flush=True)
    status, versions = 0, {}
    cell = {"agent": pair.a, "mechanism": pair.mechanism, "stage": args.stage, "scenario": "S9", "rep": args.rep,
            "backend": adapter_backend(pair.fwd, pair.b), "host": adapter_host(pair.fwd)}
    try:
        try:
            label_a, label_b = (None, None) if split else pair.labels()
            m, a = engine.launch(m, pair.a, "auto", back, label_a)
            versions = dict(a.versions)
            if split:
                mb, b = engine.launch(mb, pair.b, "auto", fwd, label_b)
            else:
                m, b = engine.launch(m, pair.b, "auto", fwd, label_b)
            versions |= b.versions
            for s in (a, b):
                print(f"attach: {engine.host_of(s.target).attach_command(s.target.host_ref)}", flush=True)
            record = run_pair(engine, manifest.load(layout, m.run_id) or m, pair, Session(a, back), Session(b, fwd),
                              args.stage, args.rep)
            if split:
                record = replace(record, notes=f"{record.notes}; b-run={mb.run_id}")
            status = record_status(record_and_print(layout, record))
        except Exception as e:  # every cell failure goes through the one ladder in cell_failure
            m = manifest.load(layout, m.run_id) or m
            status, _ = cell_failure(layout, engine, progress, m, cell, e, versions)
    finally:
        if split:
            status = after_run(layout, engine, progress, mb, status, base, args.keep)
        status = after_run(layout, engine, progress, m, status, base, args.keep)
        progress.maybe_write(time.monotonic(), [], force=True)
        write_matrix(layout)
    return status


def s9_split(a: str, b: str, shared_run: bool) -> bool:
    return a == b and not shared_run


def write_matrix(layout) -> None:
    layout.matrix_md.parent.mkdir(parents=True, exist_ok=True)
    layout.matrix_md.write_text(report.render_matrix(checkpoint.load_records(layout.raw_jsonl), time.time()))


def cmd_run(args) -> int:
    layout = default_layout()
    cell = make_cell(args.stage, args.agent, args.adapter, args.scenario, args.rep, args.sandbox)
    problem = nono_problem([cell])
    if problem:
        print(f"refused: {problem}", file=sys.stderr)
        return 2
    records = checkpoint.load_records(layout.raw_jsonl)
    if not checkpoint.pending_cells([cell], records, args.resume, args.retry_errors):
        print("cell already recorded; skipped (--resume)")
        return 0
    budget = checkpoint.TimeBudget(time.monotonic(), args.time_budget)
    progress = checkpoint.ProgressWriter(layout.progress_md, layout.raw_jsonl, home=str(Path.home()))
    result = run_one(layout, progress, cell, keep=args.keep, mode=args.mode)
    progress.maybe_write(time.monotonic(), [], force=True)
    write_matrix(layout)
    if budget.expired(time.monotonic()):
        print("time budget exhausted")
    return result.status


def requeues(record: dict | None) -> bool:
    return bool(record) and record["delivery"] == Delivery.ENV_ERROR and not pauses_batch(record)


def matrix_cells(stage: str, agents: list[str], adapters: list[str], scenario_ids: list[str],
                 reps: int, sandbox: str = "raw") -> list[dict]:
    return [make_cell(stage, agent, adapter, scenario, rep, sandbox)
            for agent in agents for adapter in adapters if agent in adapter_agents(adapter)
            for scenario in scenario_ids for rep in range(1, reps + 1)]


def valid_rep(rep) -> bool:
    return isinstance(rep, int) and not isinstance(rep, bool) and rep >= 1


def plan_cells(entries: list[dict], stage: str, sandbox: str = "raw") -> list[dict]:
    if not isinstance(entries, list):
        raise ValueError(f"a plan must be a JSON list of cells, not {type(entries).__name__}")
    problems = [f"{e}" for e in entries
                if not isinstance(e, dict) or e.get("agent") not in AGENTS or e.get("mechanism") not in ADAPTER_NAMES
                or e.get("scenario") not in SCENARIOS or not valid_rep(e.get("rep"))
                or e["agent"] not in adapter_agents(e["mechanism"]) or e.get("stage", stage) not in STAGES]
    if problems:
        raise ValueError(f"invalid plan entries: {'; '.join(problems[:5])}")
    return [make_cell(e.get("stage", stage), e["agent"], e["mechanism"], e["scenario"], e["rep"], sandbox)
            for e in entries]


def nono_problem(cells: list[dict]) -> str | None:
    bad = sorted({c["mechanism"] for c in cells if c["sandbox"] == "nono" and c["mechanism"] in NONO_EXCLUDED})
    return (f"{', '.join(bad)} cannot run under --sandbox nono (its pinned env sits between sops-exec and nono)"
            if bad else None)


def planned_cells(args) -> list[dict]:
    if args.plan:
        cells = plan_cells(json.loads(Path(args.plan).read_text()), args.stage, args.sandbox)
    elif not (args.agents and args.adapters):
        raise ValueError("matrix needs --plan or both --agents and --adapters")
    else:
        cells = matrix_cells(args.stage, args.agents, args.adapters, args.scenarios, args.reps, args.sandbox)
    problem = nono_problem(cells)
    if problem:
        raise ValueError(problem)
    return cells


STOP_FILE = "STOP"


def stop_file(layout) -> Path:
    return layout.runs / STOP_FILE


def version_drift(seen: dict[str, str], record: dict | None) -> tuple[dict[str, str], str | None]:
    if not record or record["delivery"] == Delivery.NA:
        return seen, None
    current = dict(record.get("versions") or {})
    changed = [f"{k} {seen[k]} -> {v}" for k, v in current.items() if k in seen and seen[k] != v]
    return {**current, **seen}, (f"version changed between cells in this batch: {', '.join(changed)}"
                                 if changed else None)


def batch_status(stop_status: int, paused: bool, records: list[dict]) -> int:
    if stop_status:
        return stop_status
    if paused:
        return PAUSED
    return CELL_ERROR if any(r["delivery"] == Delivery.ERROR for r in records) else 0


def cell_locks(cell: dict) -> frozenset[str]:
    shared = adapter_shared_state(cell["mechanism"])
    return frozenset({f"agent:{cell['agent']}", *([f"state:{shared}"] if shared else [])})


def next_cell(queue: deque, busy: set[str]) -> dict | None:
    return next((c for c in queue if not cell_locks(c) & busy), None)


MAX_CONCURRENCY = 3


def concurrency(stage: str, requested: int) -> int:
    return 1 if stage == "pilot" else max(1, min(requested, MAX_CONCURRENCY))


def recorded_since(layout, cell: dict, since: float) -> dict | None:
    key = checkpoint.cell_key(cell)
    return next((r for r in reversed(checkpoint.load_records(layout.raw_jsonl))
                 if checkpoint.cell_key(r) == key and r["ts"] >= since), None)


def cell_result(future, layout, cell: dict, started: float) -> CellResult:
    try:
        return future.result()
    except Exception as e:  # a worker crash: keep its traceback, leave one record for the cell, stop the batch
        layout.runs.mkdir(parents=True, exist_ok=True)
        path = layout.runs / f"harness-crash-{new_run_id(time.time())}.txt"
        path.write_text("".join(traceback.format_exception(e)))
        print(f"STOP: harness crash in {cell['agent']} {cell['scenario']}: {type(e).__name__}: {e} "
              f"(see {path.relative_to(layout.root)})", file=sys.stderr)
        existing = recorded_since(layout, cell, started)
        if existing:
            return CellResult(HARNESS_BUG, existing)
        note = f"harness-crash: {type(e).__name__}: {e}; traceback={path.relative_to(layout.root)}"
        engine = Engine(layout, sandbox=cell["sandbox"])
        return CellResult(HARNESS_BUG, unlaunched_record(layout, engine, cell, Delivery.ERROR, note))


def cmd_matrix(args) -> int:
    layout = default_layout()
    try:
        planned = planned_cells(args)
    except (ValueError, OSError) as e:
        print(f"matrix: {e}", file=sys.stderr)
        return 2
    cells = checkpoint.pending_cells(planned, checkpoint.load_records(layout.raw_jsonl), args.resume,
                                     args.retry_errors)
    budget = checkpoint.TimeBudget(time.monotonic(), args.time_budget)
    progress = checkpoint.ProgressWriter(layout.progress_md, layout.raw_jsonl, home=str(Path.home()))
    queue = deque(cells)
    requeued: set[tuple] = set()
    batch_runs: set[str] = set()
    lock = threading.Lock()
    busy: set[str] = set()
    done: list[dict] = []
    seen_versions: dict[str, str] = {}
    stop_status, paused, expired, submitted = 0, False, False, 0
    limit = concurrency(args.stage, args.max_concurrency)
    if limit != args.max_concurrency:
        print(f"matrix: --max-concurrency {args.max_concurrency} clamped to {limit} for stage {args.stage}")
    print(f"matrix: {len(cells)} cells pending", flush=True)
    progress.maybe_write(time.monotonic(), list(queue), force=True)

    def register(run_id: str) -> None:
        with lock:
            batch_runs.add(run_id)

    def exclude() -> frozenset[str]:
        with lock:
            return frozenset(batch_runs)

    try:
        with ThreadPoolExecutor(max_workers=limit) as pool:
            running: dict = {}
            while queue or running:
                expired = expired or budget.expired(time.monotonic()) or stop_file(layout).exists()
                while queue and not (stop_status or paused or expired) and len(running) < limit:
                    cell = next_cell(queue, busy)
                    if cell is None:
                        break
                    queue.remove(cell)
                    submitted += 1
                    busy |= cell_locks(cell)
                    future = pool.submit(run_one, layout, progress, cell, False, None, exclude, register, False)
                    running[future] = (cell, time.time())
                if not running:
                    break
                finished, _ = wait(running, return_when=FIRST_COMPLETED)
                for future in finished:
                    cell, t_started = running.pop(future)
                    busy -= cell_locks(cell)
                    result = cell_result(future, layout, cell, t_started)
                    if result.record:
                        done.append(result.record)
                    seen_versions, drift = version_drift(seen_versions, result.record)
                    if drift and not stop_status:
                        stop_status = stop(progress, f"{drift} (after {cell['agent']} {cell['mechanism']} "
                                                     f"{cell['scenario']})", 3)
                    if result.status in STOP_STATUSES and not stop_status:
                        stop_status = result.status
                    if pauses_batch(result.record):
                        paused = True
                        progress.open_issues.append(f"batch paused after {cell['agent']} {cell['scenario']}: "
                                                    f"{result.record['notes'][-160:]}")
                    elif requeues(result.record) and checkpoint.cell_key(cell) not in requeued:
                        requeued.add(checkpoint.cell_key(cell))
                        queue.append(cell)
                    progress.maybe_write(time.monotonic(), list(queue))
                    write_matrix(layout)
    finally:
        manifest.stop_idle_server(layout)
        progress.maybe_write(time.monotonic(), list(queue), force=True)
        write_matrix(layout)
    stopped = stop_file(layout).exists()
    if expired and queue:
        why = f"{stop_file(layout)} found" if stopped else "time budget exhausted"
        print(f"{why}; {len(queue)} cells left (rerun with --resume)")
    blocked = bool(stopped and queue and not submitted)
    if blocked:
        print(f"STOP: {stop_file(layout)} blocked the batch before its first cell; remove it and rerun with --resume",
              file=sys.stderr)
    if paused:
        print("STOP: batch paused on an API/quota/auth error or a receiver crash; rerun with --resume later",
              file=sys.stderr)
    return batch_status(stop_status, paused or blocked, done)


def session_problems(layout, engine: Engine, run_id: str) -> list[str]:
    saved = manifest.load(layout, run_id)
    return [p for t in (saved.targets if saved else []) for p in engine.post_session_checks(t)]


def scale_owners(layout, runs: list[str], labels: dict[str, str]) -> dict[int, str]:
    rows = procs.ps_rows()
    return {pid: labels[run_id] for run_id in runs
            for m in [manifest.load(layout, run_id)] if m for pid in manifest.run_pids(layout, m, rows)}


def load_sampler(layout, runs: list[str], labels: dict[str, str], phase: list[str], stop_event: threading.Event,
                 out: dict[str, list], interval_s: float = 2.0, refresh_s: float = 20.0) -> threading.Thread:
    def loop() -> None:
        owners, refreshed = {}, 0.0
        while not stop_event.is_set():
            try:
                if time.monotonic() - refreshed >= refresh_s:
                    owners, refreshed = scale_owners(layout, runs, labels), time.monotonic()
                out.setdefault(phase[0], []).append(scale.sample_load(owners))
            except (OSError, subprocess.SubprocessError, ValueError) as e:
                print(f"scale: load sample failed: {type(e).__name__}: {e}", file=sys.stderr)
            stop_event.wait(interval_s)
    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    return thread


def scale_launch(layout, receiver, m: Manifest):
    engine = Engine(layout)
    adapter = make_adapter(receiver.mechanism, engine.host_for)
    m, launched = engine.launch(m, receiver.agent, "auto", adapter)
    print(f"scale: {receiver.label} ready ({launched.ready_signal}) run {m.run_id} "
          f"attach: {engine.host_of(launched.target).attach_command(launched.target.host_ref)}", flush=True)
    return engine, adapter, m, launched


def scale_note(record: ResultRecord, receiver, round_no: int, total: int, extra: str = "") -> ResultRecord:
    return replace(record, notes=f"{record.notes}; scale-receiver={receiver.label}; round={round_no}/{scale.MESSAGES}; "
                                 f"receivers={total}{extra}")


def scale_failure(layout, receiver, m: Manifest, round_no: int, error: Exception, total: int,
                  extra: str = "") -> ResultRecord:
    record = Engine(layout).failure_record(manifest.load(layout, m.run_id) or m, receiver.agent, receiver.mechanism,
                                           "shortlist", "SCALE", scale.message_rep(receiver, round_no), {}, error,
                                           adapter_backend(receiver.mechanism, receiver.agent),
                                           adapter_host(receiver.mechanism))
    return scale_note(record, receiver, round_no, total, extra)


def scale_converse(layout, receiver, session, barrier: threading.Barrier,
                   total: int) -> tuple[list[ResultRecord], Exception | None]:
    from agentcomms.engine import REPLY_TIMEOUT_S
    from agentcomms.scenarios.common import Cell, finish, send_and_observe
    engine, adapter, m, launched = session
    records: list[ResultRecord] = []
    failed: Exception | None = None
    for round_no in range(1, scale.MESSAGES + 1):
        with contextlib.suppress(threading.BrokenBarrierError):
            barrier.wait()
        if failed is not None:
            continue
        wall0, mono0 = time.time(), time.monotonic()
        cell = Cell(engine, m, launched, adapter, "SCALE", "shortlist", scale.message_rep(receiver, round_no))
        try:
            out = send_and_observe(cell, launched.target, scale.SCALE_BODY, REPLY_TIMEOUT_S[receiver.agent])
            records.append(scale_note(finish(cell, out, wall0, mono0), receiver, round_no, total))
        except Exception as e:  # one receiver's failure must not stall the other receivers at the barrier
            failed = e
            records.append(scale_failure(layout, receiver, cell.m, round_no, e, total, "; later rounds not sent"))
        m = cell.m
    return records, failed


def scale_status(progress, label: str, error: Exception | None) -> int:
    if error is None:
        return 0
    if isinstance(error, manifest.OwnershipError):
        return stop(progress, f"ownership check failed for {label}: {error}", 7)
    if isinstance(error, CELL_ERRORS):
        return 0
    return stop(progress, f"harness bug in scale receiver {label}: {type(error).__name__}: {error}", HARNESS_BUG)


def worst(status: int, new: int) -> int:
    return status if status in STOP_STATUSES else new or status


def cmd_scale(args) -> int:
    layout = default_layout()
    progress = checkpoint.ProgressWriter(layout.progress_md, layout.raw_jsonl, home=str(Path.home()))
    mix = scale.receivers()
    base = baseline(sorted({r.agent for r in mix}))
    engine = Engine(layout)
    runs: list[Manifest] = []
    try:
        for _ in mix:
            runs.append(engine.new_run(frozenset(m.run_id for m in runs)))
    except manifest.LiveRunError as e:
        return stop(progress, str(e), LIVE_RUN)
    labels = {m.run_id: r.label for m, r in zip(runs, mix, strict=True)}
    print("scale: " + ", ".join(f"{r.label} {r.mechanism} run {m.run_id}" for m, r in zip(runs, mix, strict=True)),
          flush=True)
    phase, samples, done = ["launch"], {}, threading.Event()
    sampler = load_sampler(layout, list(labels), labels, phase, done, samples)
    status, records, launch_s = 0, [], 0.0
    t0 = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=len(mix)) as pool:
            futures = [pool.submit(scale_launch, layout, r, m) for r, m in zip(mix, runs, strict=True)]
            sessions = []
            for r, m, f in zip(mix, runs, futures, strict=True):
                try:
                    sessions.append((r, f.result()))
                except Exception as e:  # collect every launch; one failure must not drop the others
                    status = worst(status, scale_status(progress, r.label, e))
                    records.append(scale_failure(layout, r, m, 1, e, len(mix), "; launch failed"))
            launch_s = time.monotonic() - t0
            print(f"scale: {len(sessions)}/{len(mix)} receivers ready after {launch_s:.0f}s", flush=True)
            phase[0] = "messages"
            if sessions:
                barrier = threading.Barrier(len(sessions), timeout=900)
                talks = [pool.submit(scale_converse, layout, r, s, barrier, len(sessions)) for r, s in sessions]
                for (r, (_, _, m, _)), f in zip(sessions, talks, strict=True):
                    try:
                        talked, failed = f.result()
                    except Exception as e:  # a crash outside a round still keeps the other receivers' records
                        talked, failed = [scale_failure(layout, r, m, 1, e, len(sessions))], e
                    records += talked
                    status = worst(status, scale_status(progress, r.label, failed))
    finally:
        done.set()
        sampler.join(timeout=30)
        for record in records:
            record_and_print(layout, record)
        for m in runs:
            status = after_run(layout, engine, progress, manifest.load(layout, m.run_id) or m, status, base,
                               kill_server=False)
        manifest.stop_idle_server(layout)
        progress.maybe_write(time.monotonic(), [], force=True)
        write_matrix(layout)
    summary = scale.aggregate([r.to_dict() for r in records])
    out = {"runs": labels, "mix": [r.__dict__ for r in mix], "launch_s": round(launch_s, 1),
           "delivered": summary["delivered"], "acked": summary["acked"], "errors": summary["errors"],
           "latency": summary["latency"].__dict__ if summary["latency"] else None,
           "per_agent": {a: {"delivered": v["delivered"], "latency": v["latency"].__dict__ if v["latency"] else None}
                         for a, v in summary["per_agent"].items()},
           "load": {k: scale.load_summary(v) for k, v in samples.items()}}
    (layout.results / f"scale-{runs[0].run_id}.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return status or (CELL_ERROR if any(r.delivery == Delivery.ERROR for r in records) else 0)


def cmd_hostcheck(args) -> int:
    from agentcomms.hostcheck import runner
    layout = default_layout()
    engine = Engine(layout)
    m = engine.new_run()
    print(f"run_id: {m.run_id}", flush=True)
    results = []
    try:
        for kind in args.hosts:
            m, host_results = runner.run_host(engine, m, kind, args.adapters)
            results += host_results
            print(runner.render(host_results), flush=True)
    finally:
        for line in manifest.cleanup(layout, m.run_id):
            print(f"cleanup: {line}")
    layout.results.mkdir(parents=True, exist_ok=True)
    json_path = layout.results / "hostcheck.json"
    old = json.loads(json_path.read_text()) if json_path.exists() else []
    rows = runner.merge_rows(old, runner.to_json(results))
    (layout.results / "hostcheck.md").write_text(runner.render_rows(rows))
    json_path.write_text(json.dumps(rows, indent=1) + "\n")
    return 0


def cmd_cleanup(args) -> int:
    if not args.run_id and not args.iterm_holder and not args.stale_claude_socks:
        print("cleanup needs a run id, --iterm-holder or --stale-claude-socks", file=sys.stderr)
        return 2
    layout = default_layout()
    if args.run_id and not (valid_run_id(args.run_id) and manifest.load(layout, args.run_id)):
        print(f"unknown run id: {args.run_id}", file=sys.stderr)
        return 2
    status = 0
    before = isolation.bridge_snapshot(user_home())
    if args.run_id:
        for line in manifest.cleanup(layout, args.run_id):
            print(line)
        problems = session_problems(layout, Engine(layout), args.run_id)
        for problem in problems:
            print(f"STOP: {problem}", file=sys.stderr)
            status = 4
        if manifest.remaining_pids(layout, args.run_id):
            print(f"STOP: harness processes still running for {args.run_id}", file=sys.stderr)
            status = 1
    if args.stale_claude_socks:
        for line in manifest.remove_stale_claude_sockets(manifest.run_manifests(layout)):
            print(line)
    if args.iterm_holder:
        for line in manifest.close_iterm_holder():
            print(line)
    return bridge_guard(layout, before, f"cleanup {args.run_id or 'iterm-holder'}", args.run_id) or status


def cmd_iterm_holder(args) -> int:
    from agentcomms.hosts import iterm2
    try:
        for line in iterm2.prepare_holder_sync(args.wait):
            print(line)
    except HostError as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_probe_bg(args) -> int:
    from agentcomms.hosts import claude_bg

    for line in claude_bg.probe(Engine(default_layout())):
        print(line)
    return 0


def cmd_probe_claude_link(args) -> int:
    from agentcomms import mesh_probe
    for line in mesh_probe.probe(Engine(default_layout())):
        print(line)
    return 0


def cmd_report(args) -> int:
    layout = default_layout()
    write_matrix(layout)
    print(layout.matrix_md.read_text(), end="")
    return 0


def cmd_progress(args) -> int:
    layout = default_layout()
    checkpoint.ProgressWriter(layout.progress_md, layout.raw_jsonl).maybe_write(time.monotonic(), [], force=True)
    print(layout.progress_md.read_text(), end="")
    return 0


def cmd_shortlist(args) -> int:
    layout = default_layout()
    sections = shortlist.generate(checkpoint.load_records(layout.raw_jsonl),
                                  (layout.results / "screen.md").read_text(),
                                  shortlist.pinned_versions(profiles.PINNED_AGENTS))
    if not args.write:
        print("\n\n".join(f"<!-- {name} -->\n{body}" for name, body in sections.items()))
        return 0
    target = layout.results / "shortlist.md"
    try:
        target.write_text(shortlist.splice(target.read_text(), sections))
    except ValueError as e:
        print(f"shortlist: {e}", file=sys.stderr)
        return 2
    print(f"wrote {target}")
    return 0


def cmd_nono_preflight(args) -> int:
    from agentcomms import nono_preflight
    layout = default_layout()
    run_dir = layout.runs / f"nono-preflight-{new_run_id(time.time())}"
    results = nono_preflight.run(run_dir, args.agents, Path(user_home()), dict(os.environ))
    nono = sandbox.nono_binary()
    target = layout.results / "nono-preflight.md"
    previous = target.read_text() if target.exists() else ""
    text = nono_preflight.render(results, sandbox.nono_version(nono) if nono else "missing", report.stamp(time.time()),
                                 previous)
    target.write_text(text)
    print(text, end="")
    return 0 if all(c.ok for c in results) else 1


def inventory_line(i: userconfig.Integration) -> str:
    flag = (f" -> {i.why}" if i.why == userconfig.UNCLASSIFIED
            else f" -> outward; disabled per launch: {i.disable}" if i.outward and i.disable
            else " -> outward; NO per-launch switch" if i.outward
            else f" -> {i.disable}" if i.disable else "")
    return f"- {i.kind} {i.name}{flag}"


def cmd_user_config_inventory(args) -> int:
    layout = default_layout()
    for agent in args.agents:
        inv = userconfig.inventory(agent, Path(user_home()), layout.runs)
        print(f"## {agent}")
        for i in inv.integrations:
            print(inventory_line(i))
        print(f"- trust: {inv.trust_problem or 'satisfiable per launch'}")
        for mechanism in args.mechanisms or []:
            if agent in adapter_agents(mechanism):
                print(f"- cell {mechanism}: {userconfig.skip_reason(inv, mechanism) or 'run'}")
    return 0


def cmd_hashes(args) -> int:
    for name, digest in isolation.global_config_hashes().items():
        print(f"{digest or 'absent':64}  {name}")
    return 0


def csv(allowed: tuple[str, ...]):
    def parse(value: str) -> list[str]:
        items = [v.strip() for v in value.split(",") if v.strip()]
        bad = [v for v in items if v not in allowed]
        if bad:
            raise argparse.ArgumentTypeError(f"unknown: {', '.join(bad)}; choose from {', '.join(allowed)}")
        return items
    return parse


def positive_int(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {n}")
    return n


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agentcomms")
    sub = p.add_subparsers(dest="cmd", required=True)

    launch = sub.add_parser("launch", help="start an isolated agent TUI on the adapter's host and leave it running")
    launch.add_argument("--agent", choices=AGENTS, required=True)
    launch.add_argument("--mode", choices=("auto", "prompting"), default="auto")
    launch.add_argument("--adapter", choices=ADAPTER_NAMES, default="tmux-paste",
                        help="apply this adapter's launch setup (settings, MCP servers, backend)")
    launch.add_argument("--sandbox", choices=SANDBOX_MODES, default="raw", help=SANDBOX_HELP)
    launch.set_defaults(func=cmd_launch, live=True)

    send = sub.add_parser("send", help="send one message to a harness-owned target")
    send.add_argument("--run", required=True)
    send.add_argument("--agent", choices=AGENTS)
    send.add_argument("--host-ref")
    send.add_argument("--adapter", choices=ADAPTER_NAMES, required=True)
    send.add_argument("--text", help="message body; read from stdin when omitted")
    send.set_defaults(func=cmd_send)

    run = sub.add_parser("run", help="run one cell and append its record to results/raw.jsonl")
    run.add_argument("--stage", choices=STAGES, default="pilot")
    run.add_argument("--agent", choices=AGENTS, required=True)
    run.add_argument("--adapter", choices=ADAPTER_NAMES, required=True)
    run.add_argument("--scenario", choices=SCENARIOS, default="S1")
    run.add_argument("--mode", choices=("auto", "prompting"), help="override the scenario's launch mode")
    run.add_argument("--rep", type=positive_int, default=1)
    run.add_argument("--time-budget", type=float, default=checkpoint.DEFAULT_BUDGET_MIN)
    run.add_argument("--resume", action="store_true")
    run.add_argument("--retry-errors", action="store_true", help="with --resume, also re-run cells recorded as error")
    run.add_argument("--keep", action="store_true", help="leave the session running for attach")
    run.add_argument("--sandbox", choices=SANDBOX_MODES, default="raw", help=SANDBOX_HELP)
    run.set_defaults(func=cmd_run, live=True)

    mx = sub.add_parser("matrix", help="run agent x adapter x scenario cells and render results/matrix.md")
    mx.add_argument("--stage", choices=STAGES, default="pilot")
    mx.add_argument("--agents", type=csv(AGENTS))
    mx.add_argument("--adapters", type=csv(ADAPTER_NAMES))
    mx.add_argument("--plan", help="JSON list of {agent, mechanism, scenario, rep[, stage]} cells, run in file "
                                   "order (replaces --agents/--adapters/--scenarios/--reps)")
    mx.add_argument("--scenarios", type=csv(SCENARIOS), default=list(SCENARIOS))
    mx.add_argument("--reps", type=positive_int, default=1)
    mx.add_argument("--time-budget", type=float, default=checkpoint.DEFAULT_BUDGET_MIN, help="minutes")
    mx.add_argument("--resume", action="store_true")
    mx.add_argument("--retry-errors", action="store_true", help="with --resume, also re-run cells recorded as error")
    mx.add_argument("--max-concurrency", type=int, default=1)
    mx.add_argument("--sandbox", choices=SANDBOX_MODES, default="raw", help=SANDBOX_HELP)
    mx.set_defaults(func=cmd_matrix, live=True)

    s9 = sub.add_parser("s9", help="agent-to-agent round trip: A messages B through B's adapter, B replies "
                                   "through A's adapter")
    s9.add_argument("--a", choices=AGENTS, required=True, help="sender agent")
    s9.add_argument("--b", choices=AGENTS, required=True, help="receiver agent")
    s9.add_argument("--fwd", choices=ADAPTER_NAMES, required=True, help="adapter that reaches B (B's launch setup)")
    s9.add_argument("--back", choices=ADAPTER_NAMES, required=True, help="adapter that reaches A (A's launch setup)")
    s9.add_argument("--stage", choices=STAGES, default="pilot")
    s9.add_argument("--rep", type=positive_int, default=1)
    s9.add_argument("--keep", action="store_true")
    s9.add_argument("--sandbox", choices=SANDBOX_MODES, default="raw", help=SANDBOX_HELP)
    s9.set_defaults(func=cmd_s9, live=True)

    rep = sub.add_parser("report", help="regenerate results/matrix.md from results/raw.jsonl")
    rep.set_defaults(func=cmd_report)

    hc = sub.add_parser("hostcheck", help="send fixed payloads through each host and adapter into a byte recorder")
    hc.add_argument("--hosts", type=csv(HOSTCHECK_HOSTS), default=list(HOSTCHECK_HOSTS))
    hc.add_argument("--adapters", type=csv(ADAPTER_NAMES), default=None)
    hc.set_defaults(func=cmd_hostcheck, live=True)

    cleanup = sub.add_parser("cleanup", help="kill a run's processes, tmux sessions and sockets")
    cleanup.add_argument("run_id", nargs="?")
    cleanup.add_argument("--iterm-holder", action="store_true",
                         help="also close the persistent iTerm2 holder window, only when it has no cell tabs")
    cleanup.add_argument("--stale-claude-socks", action="store_true",
                         help="remove /tmp/cc-socks/<pid>.sock only for pids that a harness manifest recorded as a "
                              "harness Claude and that are no longer running")
    cleanup.set_defaults(func=cmd_cleanup)

    holder = sub.add_parser("iterm-holder", help="create the persistent iTerm2 holder window (waits while iTerm2 "
                                                 "is the frontmost app); run it when you are in another app")
    holder.add_argument("--wait", type=float, default=None, help="seconds to wait for iTerm2 to lose the front")
    holder.set_defaults(func=cmd_iterm_holder, live=True)

    progress = sub.add_parser("progress", help="regenerate results/progress.md")
    progress.set_defaults(func=cmd_progress)

    probe_bg = sub.add_parser("probe-bg", help="one guarded `claude --bg` launch in an isolated config dir (R16)")
    probe_bg.set_defaults(func=cmd_probe_bg, live=True)
    probe_link = sub.add_parser("probe-claude-link",
                                help="harness Claude + Pi with pi-claude-link in one run: Pi->Claude and Claude->Pi")
    probe_link.set_defaults(func=cmd_probe_claude_link, live=True)

    shortlist_cmd = sub.add_parser("shortlist", help="rank the screen survivors from results/raw.jsonl (fixed safety "
                                                     "denominator of 7, R37) and print or splice the generated "
                                                     "blocks of results/shortlist.md")
    shortlist_cmd.add_argument("--write", action="store_true",
                               help="replace the generated blocks (table, ranking, s9, reps, user-config, nono, "
                                    "scale) in results/shortlist.md")
    shortlist_cmd.set_defaults(func=cmd_shortlist)

    sc = sub.add_parser("scale", help="8 concurrent receivers (scale.MIX: best mechanism per agent, own backend "
                                      "each), 3 messages each in synchronized rounds; writes SCALE records and "
                                      "results/scale-<first run id>.json")
    sc.set_defaults(func=cmd_scale, live=True)

    inv = sub.add_parser("user-config-inventory", help="names only: what each agent's real global config would load, "
                                                        "and the R41 run/skip decision per mechanism")
    inv.add_argument("--agents", type=csv(AGENTS), default=list(AGENTS))
    inv.add_argument("--mechanisms", type=csv(ADAPTER_NAMES))
    inv.set_defaults(func=cmd_user_config_inventory)

    pre = sub.add_parser("nono-preflight", help="inside each <agent>-local nono profile: ps, every stdlib sender, the "
                                                "pinned binary, unix/tcp sockets, tmux and node+tsx (R19)")
    pre.add_argument("--agents", type=csv(AGENTS), default=list(AGENTS))
    pre.set_defaults(func=cmd_nono_preflight)

    hashes = sub.add_parser("hashes", help="print sha256 of the user's global agent config files")
    hashes.set_defaults(func=cmd_hashes)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if getattr(args, "live", False):
        refused = refuse_if_sandboxed(args)
        if refused:
            return refused
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
