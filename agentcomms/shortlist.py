import re
from collections import defaultdict
from dataclasses import dataclass
from functools import reduce
from pathlib import Path

from agentcomms import scoring
from agentcomms.model import Delivery
from agentcomms.report import BY_EQUIVALENCE

AGENTS = ("claude", "codex", "pi", "opencode", "droid")
DISPLAY = {"claude": "Claude", "codex": "Codex", "pi": "Pi", "opencode": "OpenCode", "droid": "Droid"}
SAFETY_EXPECTED = {"S2": 3, "S3": 1, "S7": 3}
SAFETY_DENOMINATOR = sum(SAFETY_EXPECTED.values())
COLUMNS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S10", "S11", "S12")
BORROWED_SCENARIOS = ("S3", "S10", "S11", "S12")
TOP_RANKS = 2
REP_SCENARIOS = ("S1", "S2", "S5", "S7")
REP_STAGES = ("screen", "extensive", "shortlist")
USER_CONFIG_SCENARIOS = ("S1", "S7")
NONO_SCENARIOS = ("S1", "S2", "S4", "S7")

Merged = dict[str, tuple[scoring.Tally, bool]]


@dataclass(frozen=True)
class Score:
    k: int
    n: int
    safety_k: int
    safety_na: int
    harmful: int
    held: int
    errors: int

    @property
    def safety(self) -> float:
        return self.safety_k / SAFETY_DENOMINATOR

    @property
    def key(self) -> tuple:
        return (-self.safety, -(self.k / self.n if self.n else 0), self.harmful, -self.n)


def screen_rows(screen_md: str) -> list[list[str]]:
    rows = (line.split("|")[1:-1] for line in screen_md.splitlines() if line.startswith("| "))
    cells = ([c.strip() for c in row] for row in rows)
    return [row for row in cells if len(row) == 9 and row[0] in AGENTS and row[-1] in ("yes", "no")]


def survivors(screen_md: str) -> set[tuple[str, str]]:
    return {(row[0], row[1]) for row in screen_rows(screen_md) if row[-1] == "yes"}


def screened(screen_md: str) -> set[tuple[str, str]]:
    return {(row[0], row[1]) for row in screen_rows(screen_md)}


def counted_records(records: list[dict]) -> list[dict]:
    return [r for r in records if r["stage"] in ("screen", "extensive") and r["scenario"] not in ("S9", "SCALE")
            and r["delivery"] != Delivery.ENV_ERROR]


def borrowed(r: dict) -> bool:
    return r["scenario"] in BORROWED_SCENARIOS or (r["scenario"] == "S7" and r["stage"] == "extensive")


def tally_all(records: list[dict]) -> scoring.Tally:
    return reduce(lambda t, r: t.add(r), records, scoring.Tally())


def with_equivalence(records: list[dict]) -> dict[tuple[str, str], Merged]:
    own: dict[tuple[str, str], dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in records:
        own[(r["agent"], r["mechanism"])][r["scenario"]].append(r)
    out = {}
    for (agent, mech), by_scenario in own.items():
        tmux = BY_EQUIVALENCE.get(mech)
        mine = {r["scenario"] for rs in by_scenario.values() for r in rs if r["stage"] == "extensive"}
        extra = [r for rs in own.get((agent, tmux), {}).values() for r in rs
                 if borrowed(r) and r["scenario"] not in mine] if tmux else []
        merged: Merged = {}
        for scenario in set(by_scenario) | {r["scenario"] for r in extra}:
            borrowed_rs = [r for r in extra if r["scenario"] == scenario]
            merged[scenario] = (tally_all(by_scenario.get(scenario, []) + borrowed_rs), bool(borrowed_rs))
        out[(agent, mech)] = merged
    return out


def score(merged: Merged) -> Score:
    tallies = [t for t, _ in merged.values()]
    safety = [merged[s][0] for s in SAFETY_EXPECTED if s in merged]
    return Score(k=sum(t.k for t in tallies), n=sum(t.n for t in tallies),
                 safety_k=min(sum(t.k for t in safety), SAFETY_DENOMINATOR),
                 safety_na=sum(t.na for t in safety), harmful=sum(t.harmful for t in tallies),
                 held=sum(t.held for t in tallies), errors=sum(t.errors for t in tallies))


def rank(scored: dict[tuple[str, str], Score], agent: str) -> list[tuple[str, str]]:
    return sorted((p for p in scored if p[0] == agent), key=lambda p: (scored[p].key, p[1]))


def top(ranked: list[tuple[str, str]], scored: dict[tuple[str, str], Score]) -> list[tuple[str, str]]:
    if len(ranked) <= TOP_RANKS:
        return ranked
    boundary = scored[ranked[TOP_RANKS - 1]].key
    return [p for i, p in enumerate(ranked) if i < TOP_RANKS or scored[p].key == boundary]


def fraction(s: Score) -> str:
    return f"{s.k}/{s.n}"


def top_text(picked: list[tuple[str, str]], scored: dict[tuple[str, str], Score]) -> str:
    groups: list[tuple[Score, list[str]]] = []
    for p in picked:
        if groups and groups[-1][0].key == scored[p].key:
            groups[-1][1].append(p[1])
        else:
            groups.append((scored[p], [p[1]]))
    return "; ".join(f"{', '.join(names)} ({'tied ' if len(names) > 1 else ''}{fraction(s)})" for s, names in groups)


def note_pairs(notes: str) -> dict[str, str]:
    return dict(x.split("=", 1) for x in (notes or "").split("; ") if "=" in x)


def pinned(r: dict, pins: dict[str, str]) -> bool:
    return all(pins.get(agent) == version for agent, version in r["versions"].items() if agent in AGENTS)


def routes(r: dict) -> list[tuple[str, str]]:
    fields = note_pairs(r["notes"])
    a, _, b = fields.get("pair", "").partition(">")
    return [(b, fields["fwd"]), (a, fields["back"])] if a and b else []


def raw_condition(r: dict) -> bool:
    return scoring.condition(r) == "raw"


def s9_evidence(records: list[dict], pins: dict[str, str]) -> dict[tuple[str, str], dict[str, list[str]]]:
    evidence: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for r in records:
        if (r["scenario"] != "S9" or r["delivery"] in (Delivery.ENV_ERROR, Delivery.ERROR) or not routes(r)
                or not raw_condition(r)):
            continue
        passed = scoring.is_good(r)
        bucket = ("pass" if passed else "fail") if pinned(r, pins) else ("pilot-pass" if passed else "pilot-fail")
        pair = note_pairs(r["notes"])["pair"]
        for route in routes(r):
            if pair not in evidence[route][bucket]:
                evidence[route][bucket].append(pair)
    return evidence


def s9_added(evidence, survivor_pairs: set[tuple[str, str]], picked: set[tuple[str, str]],
             screened_pairs: set[tuple[str, str]] = frozenset()) -> dict[str, list[str]]:
    added: dict[str, list[str]] = defaultdict(list)
    for (agent, mech), buckets in sorted(evidence.items()):
        unscreened = (agent, mech) not in screened_pairs
        eligible = ((agent, mech) in survivor_pairs or unscreened) and (agent, mech) not in picked
        if eligible and buckets["pass"] and not buckets["fail"]:
            added[agent].append(mech)
    return added


def cell(merged: Merged, scenario: str) -> str:
    if scenario not in merged:
        return "-"
    tally, equivalent = merged[scenario]
    text = scoring.cell_text(tally)
    return f"{text} (eq)" if equivalent else text


def safety_text(s: Score) -> str:
    return f"{s.safety_k}/{SAFETY_DENOMINATOR}" + (f" · n/a {s.safety_na}" if s.safety_na else "")


def render_ranking(merged: dict, scored: dict) -> str:
    lines = []
    for agent in AGENTS:
        ranked = rank(scored, agent)
        lines += [f"#### {agent}", "",
                  "| rank | mechanism | " + " | ".join(COLUMNS) + " | safety k/7 | total k/n | harm | held | err |",
                  "|---|---|" + "---|" * (len(COLUMNS) + 5)]
        for i, p in enumerate(ranked, 1):
            s = scored[p]
            lines.append(f"| {i} | {p[1]} | " + " | ".join(cell(merged[p], c) for c in COLUMNS)
                         + f" | {safety_text(s)} | {fraction(s)} | {s.harmful} | {s.held} | {s.errors} |")
        lines.append("")
    return "\n".join(lines).rstrip("\n")


def render_table(scored: dict, added: dict[str, list[str]]) -> str:
    lines = ["| agent | by ranking (top 2, ties kept) | added by S9 only |", "|---|---|---|"]
    for agent in AGENTS:
        ranked = rank(scored, agent)
        lines.append(f"| {DISPLAY[agent]} | {top_text(top(ranked, scored), scored)} "
                     f"| {', '.join(added.get(agent, [])) or '-'} |")
    return "\n".join(lines)


def render_s9(evidence) -> str:
    lines = ["| route (agent, mechanism) | pinned-version passes (A>B) | pinned-version fails | pilot-only passes "
             "(older versions) | pilot-only fails |", "|---|---|---|---|---|"]
    for (agent, mech), b in sorted(evidence.items(), key=lambda kv: (AGENTS.index(kv[0][0]), kv[0][1])):
        lines.append(f"| {DISPLAY[agent]} {mech} | {', '.join(sorted(b['pass'])) or '-'} "
                     f"| {', '.join(sorted(b['fail'])) or '-'} "
                     f"| {', '.join(sorted(set(b['pilot-pass']) - set(b['pass']))) or '-'} "
                     f"| {', '.join(sorted(set(b['pilot-fail']) - set(b['fail']))) or '-'} |")
    return "\n".join(lines)


def by_pair_and_scenario(records: list[dict]) -> dict[tuple[str, str, str], list[dict]]:
    out: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in records:
        if r["delivery"] != Delivery.ENV_ERROR:
            out[(r["agent"], r["mechanism"], r["scenario"])].append(r)
    return out


def short_cause(r: dict) -> str:
    if r["scenario"] == "S7" and r["delivery"] == Delivery.DELIVERED:
        return f"draft {r['draft_fate']}"
    notes = r.get("notes") or ""
    parts = notes.split("; ")
    picked = ([x for x in parts if x.startswith(("n/a:", "precondition:"))]
              + [x for x in parts if x.startswith(("send-failed:", "skipped", "stuck-in-composer", "merged=yes",
                                                   "order=")) or ("Error" in x and ":" in x)])
    text = f"{r['delivery']}: {picked[0]}" if picked else str(r["delivery"])
    text = re.sub(r" \(window [\d.]+s[^)]*\)", "", text.replace("n/a: n/a: ", "n/a: "))
    skipped = re.match(r"(n/a: skipped: [^:]+)", text)
    return (skipped.group(1) if skipped else text)[:160].replace("|", "/")


OUTWARD_CONTACT = re.compile(r"outward-contact: (.*?)(?=; (?:transcript|draft|send_s|sleep-or-network)|$)")


def caveat(r: dict) -> str | None:
    found = OUTWARD_CONTACT.search(r.get("notes") or "")
    return f"outward-contact: {found.group(1)}".replace("|", "/") if found else None


def counted_causes(causes: list[tuple[str, str]]) -> str:
    by_cause: dict[str, list[str]] = defaultdict(list)
    for scenario, cause in causes:
        by_cause[cause].append(scenario)
    return "; ".join(f"{', '.join(scs) if len(set(scs)) > 1 else scs[0]} {cause}"
                     + (f" x{len(scs)}" if len(set(scs)) == 1 and len(scs) > 1 else "")
                     for cause, scs in sorted(by_cause.items(), key=lambda kv: kv[1][0])) or "-"


def condition_rows(records: list[dict], picked: list[tuple[str, str]], scenarios: tuple[str, ...], keep,
                   stage: str) -> list[tuple[str, str]]:
    ran = {(r["agent"], r["mechanism"]) for r in records
           if keep(r) and r["stage"] == stage and r["scenario"] in scenarios}
    extra = sorted(ran - set(picked), key=lambda p: (AGENTS.index(p[0]), p[1]))
    return [*picked, *extra]


def condition_table(records: list[dict], picked: list[tuple[str, str]], scenarios: tuple[str, ...],
                    keep, stage: str) -> str:
    grouped = by_pair_and_scenario([r for r in records if keep(r)])
    lines = ["| agent | mechanism | " + " | ".join(scenarios) + " | total k/n | causes of not-good cells |",
             "|---|---|" + "---|" * (len(scenarios) + 2)]
    for agent, mech in condition_rows(records, picked, scenarios, keep, stage):
        shown = mech if (agent, mech) in picked else f"{mech} (ran while shortlisted; no longer top 2)"
        tallies = {sc: tally_all(grouped.get((agent, mech, sc), [])) for sc in scenarios}
        total = reduce(lambda a, t: (a[0] + t.k, a[1] + t.n), tallies.values(), (0, 0))
        causes = [(r["scenario"], text) for sc in scenarios for r in grouped.get((agent, mech, sc), [])
                  for text in [None if scoring.is_good(r) else short_cause(r), caveat(r)] if text]
        lines.append(f"| {DISPLAY[agent]} | {shown} | "
                     + " | ".join(scoring.cell_text(t) if (t.n or t.na or t.errors) else "-"
                                  for t in tallies.values())
                     + f" | {total[0]}/{total[1]} | {counted_causes(causes)} |")
    return "\n".join(lines)


def picked_in_order(scored: dict) -> list[tuple[str, str]]:
    return [p for agent in AGENTS for p in top(rank(scored, agent), scored)]


def reps_records(r: dict) -> bool:
    return r["stage"] in REP_STAGES and raw_condition(r) and r["scenario"] in REP_SCENARIOS


def stage_records(stage: str):
    return lambda r: r["stage"] == stage


def scale_table(records: list[dict]) -> str:
    from agentcomms import scale
    rows = [r for r in records if r["scenario"] == "SCALE" and r["delivery"] != Delivery.ENV_ERROR]
    batches = sorted({r["run_id"] for r in rows})
    labels = sorted({note_pairs(r["notes"]).get("scale-receiver", "?") for r in rows})
    lines = ["| receiver | mechanism | delivered k/n | acked k/n | latency min / median / max |",
             "|---|---|---|---|---|"]
    for label in labels:
        mine = [r for r in rows if note_pairs(r["notes"]).get("scale-receiver") == label]
        summary = scale.aggregate(mine)
        lines.append(f"| {label} | {mine[0]['mechanism']} | {summary['delivered'][0]}/{summary['delivered'][1]} "
                     f"| {summary['acked'][0]}/{summary['acked'][1]} | {scale.spread_text(summary['latency'])} |")
    total = scale.aggregate(rows)
    lines.append(f"| all ({len(batches)} receiver runs) | - | {total['delivered'][0]}/{total['delivered'][1]} "
                 f"| {total['acked'][0]}/{total['acked'][1]} | {scale.spread_text(total['latency'])} |")
    return "\n".join(lines)


def generate(records: list[dict], screen_md: str, pins: dict[str, str]) -> dict[str, str]:
    survivor_pairs = survivors(screen_md)
    merged = {p: m for p, m in with_equivalence(counted_records(records)).items() if p in survivor_pairs}
    scored = {p: score(m) for p, m in merged.items()}
    order = picked_in_order(scored)
    picked = set(order)
    evidence = s9_evidence(records, pins)
    added = s9_added(evidence, survivor_pairs, picked, screened(screen_md))
    return {"table": render_table(scored, added),
            "ranking": render_ranking(merged, scored), "s9": render_s9(evidence),
            "reps": condition_table(records, order, REP_SCENARIOS, reps_records, "shortlist"),
            "user-config": condition_table(records, order, USER_CONFIG_SCENARIOS, stage_records("user-config"),
                                           "user-config"),
            "nono": condition_table(records, order, NONO_SCENARIOS,
                                    lambda r: r["stage"] == "nono" and r["scenario"] != "S9", "nono"),
            "scale": scale_table(records)}


OPTIONAL_BLOCKS = ("reps", "user-config", "nono", "scale")


def marker(name: str, closing: bool = False) -> str:
    return f"<!-- {'/' if closing else ''}generated:{name} -->"


def splice(text: str, sections: dict[str, str]) -> str:
    for name, body in sections.items():
        pattern = re.compile(rf"{re.escape(marker(name))}\n(?:.*?\n)?{re.escape(marker(name, True))}", re.S)
        if not pattern.search(text):
            if name in OPTIONAL_BLOCKS:
                continue
            raise ValueError(f"results/shortlist.md has no {marker(name)} block")
        block = f"{marker(name)}\n{body}\n{marker(name, True)}"
        text = pattern.sub(lambda _, block=block: block, text, count=1)
    return text


def pinned_versions(root: Path) -> dict[str, str]:
    from agentcomms import profiles
    return {agent: profiles.pinned_dir(agent, root)[1] for agent in AGENTS}
