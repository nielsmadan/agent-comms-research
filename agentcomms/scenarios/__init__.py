import time
from collections.abc import Callable
from dataclasses import dataclass

from agentcomms.engine import Engine, Launched
from agentcomms.isolation import Mode
from agentcomms.model import Adapter, Manifest
from agentcomms.records import ResultRecord
from agentcomms.scenarios import s1, s2, s3, s4, s5, s6, s7, s8, s10, s11, s12
from agentcomms.scenarios.common import Cell, Outcome, finish


def always(agent: str, backend: str, adapter: Adapter | None = None) -> str | None:
    return None


@dataclass(frozen=True)
class Scenario:
    id: str
    run: Callable[[Cell], Outcome]
    mode: Mode = "auto"
    not_applicable: Callable[[str, str, Adapter | None], str | None] = always


SCENARIOS: dict[str, Scenario] = {
    "S1": Scenario("S1", s1.run),
    "S2": Scenario("S2", s2.run),
    "S3": Scenario("S3", s3.run, "prompting", s3.not_applicable),
    "S4": Scenario("S4", s4.run),
    "S5": Scenario("S5", s5.run),
    "S6": Scenario("S6", s6.run),
    "S7": Scenario("S7", s7.run),
    "S8": Scenario("S8", s8.run),
    "S10": Scenario("S10", s10.run, "auto", s10.not_applicable),
    "S11": Scenario("S11", s11.run),
    "S12": Scenario("S12", s12.run, "auto", s12.not_applicable),
}


def cell_not_applicable(scenario_id: str, agent: str, backend: str, adapter: Adapter) -> str | None:
    own = getattr(adapter, "scenario_not_applicable", None)
    return (own(agent, scenario_id) if own else None) or SCENARIOS[scenario_id].not_applicable(agent, backend, adapter)


def run_scenario(engine: Engine, m: Manifest, launched: Launched, adapter: Adapter, scenario: str, stage: str,
                 rep: int) -> ResultRecord:
    wall0, mono0 = time.time(), time.monotonic()
    cell = Cell(engine, m, launched, adapter, scenario, stage, rep)
    out = SCENARIOS[scenario].run(cell)
    return finish(cell, out, wall0, mono0)
