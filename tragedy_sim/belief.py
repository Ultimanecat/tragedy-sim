"""Information-safe hidden-world candidates for future ISMCTS agents.

The evidence object is intentionally constructed from a protagonist projection,
not from ``Game.scenario`` or ``Game.roles``.  Catalog sampling is the first
particle source; later generators can implement the full combinatorial script
space behind the same boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any, Mapping

from .scenario_library import ScenarioLibrary


@dataclass(frozen=True)
class PublicEvidence:
    module: str
    days: int
    loops: int
    characters: tuple[str, ...]
    schedule: tuple[tuple[int, str], ...]
    known_roles: tuple[tuple[str, str], ...]
    known_culprits: tuple[tuple[int, str], ...]
    known_plots: tuple[str, ...]

    @classmethod
    def from_view(cls, view: Mapping[str, Any]) -> "PublicEvidence":
        """Extract only facts explicitly present in a protagonist view."""
        known_roles = tuple(sorted(
            (cid, fact["role"])
            for cid, fact in view.get("known_roles", {}).items()
            if isinstance(fact, Mapping) and isinstance(fact.get("role"), str)
        ))
        known_culprits = tuple(sorted(
            (int(day), cid)
            for day, cid in view.get("known_culprits", {}).items()
        ))
        schedule = tuple(sorted(
            (int(item["day"]), str(item["kind"]))
            for item in view.get("schedule", ())
        ))
        return cls(
            module=str(view["module"]), days=int(view["days"]),
            loops=int(view["loops"]),
            characters=tuple(sorted(view.get("characters", {}))),
            schedule=schedule, known_roles=known_roles,
            known_culprits=known_culprits,
            known_plots=tuple(sorted(str(item) for item in view.get("known_plots", ()))),
        )


@dataclass(frozen=True)
class HiddenWorldHypothesis:
    """Private particle.  Never serialize this object into a player response."""

    scenario_id: str
    main_plot: str
    subplots: tuple[str, ...]
    roles: tuple[tuple[str, str], ...]
    incidents: tuple[tuple[int, str, str], ...]

    @classmethod
    def from_scenario(cls, scenario: Mapping[str, Any]) -> "HiddenWorldHypothesis":
        return cls(
            scenario_id=str(scenario["id"]), main_plot=str(scenario["main_plot"]),
            subplots=tuple(str(item) for item in scenario["subplots"]),
            roles=tuple(sorted((str(cid), str(role))
                               for cid, role in scenario["cast"].items())),
            incidents=tuple(sorted(
                (int(item["day"]), str(item.get("public_kind", item["kind"])),
                 str(item["culprit"]))
                for item in scenario["incidents"])),
        )


class CatalogBeliefSampler:
    """Filter server-owned scripts using protagonist-visible evidence only."""

    def __init__(self, library: ScenarioLibrary | None = None):
        self.library = library or ScenarioLibrary()

    @staticmethod
    def _matches(evidence: PublicEvidence, scenario: Mapping[str, Any]) -> bool:
        if scenario["module"] != evidence.module or scenario["days"] != evidence.days:
            return False
        if evidence.loops not in scenario.get("loop_options", [scenario["loops"]]):
            return False
        if tuple(sorted(scenario["cast"])) != evidence.characters:
            return False
        public_schedule = tuple(sorted(
            (int(item["day"]), str(item.get("public_kind", item["kind"])))
            for item in scenario["incidents"]))
        if public_schedule != evidence.schedule:
            return False
        roles = scenario["cast"]
        if any(roles.get(cid) != role for cid, role in evidence.known_roles):
            return False
        incidents_by_day: dict[int, set[str]] = {}
        for item in scenario["incidents"]:
            incidents_by_day.setdefault(int(item["day"]), set()).add(str(item["culprit"]))
        if any(cid not in incidents_by_day.get(day, set())
               for day, cid in evidence.known_culprits):
            return False
        plots = {scenario["main_plot"], *scenario["subplots"]}
        return all(plot in plots for plot in evidence.known_plots)

    def candidates(self, evidence: PublicEvidence) -> tuple[HiddenWorldHypothesis, ...]:
        hypotheses = []
        for summary in self.library.list(evidence.module):
            scenario = self.library.get(summary["id"])
            if self._matches(evidence, scenario):
                hypotheses.append(HiddenWorldHypothesis.from_scenario(scenario))
        return tuple(sorted(hypotheses, key=lambda item: item.scenario_id))

    def sample(self, evidence: PublicEvidence, count: int, *,
               rng: random.Random) -> tuple[HiddenWorldHypothesis, ...]:
        if type(count) is not int or count < 1:
            raise ValueError("count must be a positive integer")
        candidates = self.candidates(evidence)
        if not candidates:
            return ()
        return tuple(rng.choice(candidates) for _ in range(count))
