import time
from collections import Counter

from agentcomms import scoring


def stamp(now: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))


NOTES_HEADING = "## Notes"
BY_EQUIVALENCE = {"zmx-send": "tmux-keys", "zellij-write": "tmux-keys", "zmx-paste": "tmux-paste",
                  "zellij-paste": "tmux-paste"}
EQUIVALENCE_SCENARIOS = ("S3", "S7 reps 2-3", "S10", "S11", "S12")


def equivalence_note() -> str:
    pairs = ", ".join(f"`{a}` = `{t}`" for a, t in BY_EQUIVALENCE.items())
    return (f"By equivalence (R34): {pairs} for {', '.join(EQUIVALENCE_SCENARIOS)} in the extensive stage. These "
            "pairs deliver byte-identical input to their tmux adapter (`results/hostcheck.md`), so only the "
            "host-sensitive S2, S5 and S6 were run on them; read the tmux row for the rest (no records are written "
            "for them). A pair whose host-sensitive result differed from tmux got the full set and has its own "
            "cells (`results/shortlist.md`).")


def notes_section(text: str) -> list[str]:
    lines = text.splitlines()
    if NOTES_HEADING not in lines:
        return []
    body = lines[lines.index(NOTES_HEADING) + 1:]
    end = next((i for i, line in enumerate(body) if line.startswith("## ")), len(body))
    return trim_blank(body[:end])


def trim_blank(lines: list[str]) -> list[str]:
    filled = [i for i, line in enumerate(lines) if line.strip()]
    return lines[filled[0]:filled[-1] + 1] if filled else []


def render_progress(records: list[dict], open_issues: list[str], next_cells: list[dict], now: float,
                    notes: list[str] = ()) -> str:
    kept = trim_blank(list(notes))
    lines = ["# Progress", "", f"Updated: {stamp(now)}", ""]
    if kept:
        lines += [NOTES_HEADING, "", *kept, ""]
    lines += ["## Done cells", ""]
    if records:
        lines += ["| run | stage | agent | mechanism | host | scenario | rep | delivery | ack | latency_s |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        lines += [
            f"| {r['run_id']} | {r['stage']} | {r['agent']} | {r['mechanism']} | {r['host']} | {r['scenario']} "
            f"| {r['rep']} | {r['delivery']} | {r['ack']} | {r['latency_s'] if r['latency_s'] is not None else '-'} |"
            for r in records
        ]
        counts = Counter(r["delivery"] for r in records)
        lines += ["", "Totals: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))]
    else:
        lines.append("None yet.")
    lines += ["", "## Open issues", ""]
    lines += [f"- {i}" for i in open_issues] or ["None."]
    lines += ["", "## Next cells", ""]
    lines += [f"- {c['stage']} {c['agent']} {c['mechanism']} {c['scenario']} rep {c['rep']}" for c in next_cells] or [
        "None queued."]
    return "\n".join(lines) + "\n"


def scenario_columns(table: dict[tuple, dict[str, scoring.Tally]]) -> list[str]:
    present = {s for row in table.values() for s in row}
    return [s for s in scoring.SCENARIO_ORDER if s in present]


def render_matrix(records: list[dict], now: float, stage: str | None = None) -> str:
    table = scoring.tally(records, stage)
    columns = scenario_columns(table)
    scope = f"stage `{stage}`" if stage else "all stages"
    lines = ["# Matrix", "", f"Updated: {stamp(now)} · {scope}", "",
             "Cells are k/n: k good outcomes (per `agentcomms/scoring.py`) out of n verdicts. `error` (harness "
             "failure or failed precondition), `n/a` and `env_error` records are not counted in n; `err N` and "
             "`harm N` list them; `held N` counts messages the receiver parked for a human Deny/Deliver (counted in n, "
             "never good). The `macOS` column is the major version from `versions.os`; records written before it "
             "existed count as 26. `condition` is `raw` (no sandbox, isolated homes), `nono` (receiver, backend and "
             "harness-side sender under the user's `nono run -p <agent>-local` launcher) or `raw + user config` "
             "(the user's real global config loaded, Task 10). Only frequent failures are detectable at these rep "
             "counts.", ""]
    if not table:
        return "\n".join([*lines, "No records yet."]) + "\n"
    lines += ["| agent | mechanism | host | backend | macOS | condition | " + " | ".join(columns) + " |",
              "|---|---|---|---|---|---|" + "---|" * len(columns)]
    for key in sorted(table):
        row = table[key]
        lines.append("| " + " | ".join(key) + " | " + " | ".join(scoring.cell_text(row.get(s)) for s in columns)
                     + " |")
    return "\n".join([*lines, "", equivalence_note()]) + "\n"
