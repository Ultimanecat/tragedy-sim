"""Information-safe hidden-world candidates for future ISMCTS agents.

The evidence object is intentionally constructed from a protagonist projection,
not from ``Game.scenario`` or ``Game.roles``.  Catalog sampling is the first
particle source; later generators can implement the full combinatorial script
space behind the same boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from copy import deepcopy
from itertools import combinations
import hashlib
import json
import random
from typing import Any, Mapping, Sequence

from .catalog import MODULES, PLOTS
from .engine import RuleError
from .scenario import validate_scenario
from .scenario_library import ScenarioLibrary


_PRESENTATION_FIELDS = {
    "description", "label", "labels", "language", "message", "module_name",
    "name", "passive", "phase_name", "scenario_id", "text", "timepoint",
    "title", "traits",
}


def _semantic_projection(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _semantic_projection(item)
            for key, item in value.items()
            if key not in _PRESENTATION_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [_semantic_projection(item) for item in value]
    return deepcopy(value)


@dataclass(frozen=True)
class PublicEvidence:
    module: str
    days: int
    loops: int
    table_talk: bool
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
            table_talk=bool(view.get("table_talk", False)),
            characters=tuple(sorted(view.get("characters", {}))),
            schedule=schedule, known_roles=known_roles,
            known_culprits=known_culprits,
            known_plots=tuple(sorted(str(item) for item in view.get("known_plots", ()))),
        )


@dataclass(frozen=True)
class PublicSnapshot:
    """Canonical protagonist-visible state, stripped of presentation metadata."""

    key: str

    @classmethod
    def from_view(cls, view: Mapping[str, Any]) -> "PublicSnapshot":
        projection = _semantic_projection(view)
        return cls(json.dumps(projection, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"), allow_nan=False))

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.key.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class HiddenWorldHypothesis:
    """Private particle.  Never serialize this object into a player response."""

    scenario_id: str
    main_plot: str
    subplots: tuple[str, ...]
    roles: tuple[tuple[str, str], ...]
    incidents: tuple[tuple[int, str, str, str], ...]

    @classmethod
    def from_scenario(cls, scenario: Mapping[str, Any]) -> "HiddenWorldHypothesis":
        return cls(
            scenario_id=str(scenario["id"]), main_plot=str(scenario["main_plot"]),
            subplots=tuple(str(item) for item in scenario["subplots"]),
            roles=tuple(sorted((str(cid), str(role))
                               for cid, role in scenario["cast"].items())),
            incidents=tuple(sorted(
                (int(item["day"]), str(item["kind"]),
                 str(item.get("public_kind", item["kind"])), str(item["culprit"]))
                for item in scenario["incidents"])),
        )

    def materialize(self, evidence: PublicEvidence) -> dict[str, Any]:
        """Build a validated standard script without consulting a real game."""
        incidents = []
        for day, kind, public_kind, culprit in self.incidents:
            incident = {"day": day, "kind": kind, "culprit": culprit}
            if public_kind != kind:
                incident["public_kind"] = public_kind
            incidents.append(incident)
        return validate_scenario({
            "id": self.scenario_id, "title": "ISMCTS sampled world",
            "module": evidence.module, "days": evidence.days,
            "loops": evidence.loops, "main_plot": self.main_plot,
            "subplots": list(self.subplots), "cast": dict(self.roles),
            "incidents": incidents, "table_talk": evidence.table_talk,
        })


@dataclass(frozen=True)
class ParticleReplayResult:
    accepted: bool
    game: Any | None
    decisions: int
    reason: str | None = None


class ParticleReplayer:
    """Replay an explicitly public command stream inside one sampled world."""

    def replay(self, hypothesis: HiddenWorldHypothesis,
               evidence: PublicEvidence,
               commands: Sequence[Mapping[str, Any]], *,
               viewer: str,
               expected: PublicSnapshot | None = None) -> ParticleReplayResult:
        # Local import keeps the belief data model independent from the engine.
        from .game import Game

        try:
            game = Game(hypothesis.materialize(evidence))
        except RuleError as exc:
            return ParticleReplayResult(False, None, 0, f"invalid_particle:{exc}")
        for index, supplied in enumerate(commands):
            command = deepcopy(dict(supplied))
            actor = command.get("actor")
            if actor != game.controller or command not in game.search_actions(actor):
                return ParticleReplayResult(False, None, index, "public_command_illegal")
            game = game.transition(command).game
        if expected is not None and PublicSnapshot.from_view(game.view(viewer)) != expected:
            return ParticleReplayResult(False, None, len(commands),
                                        "public_snapshot_mismatch")
        return ParticleReplayResult(True, game, len(commands))


@dataclass(frozen=True)
class ParticleAdvanceResult:
    successors: tuple[Any, ...]
    tested_actions: int


class ObservationParticleAdvancer:
    """Infer hidden actions by matching their protagonist-visible consequence."""

    def advance(self, game: Any, *, viewer: str,
                observed: PublicSnapshot,
                public_command: Mapping[str, Any] | None = None,
                max_successors: int | None = None) -> ParticleAdvanceResult:
        if max_successors is not None and (
                type(max_successors) is not int or max_successors < 1):
            raise ValueError("max_successors must be a positive integer or None")
        legal = list(game.search_actions(game.controller))
        if public_command is not None:
            command = dict(public_command)
            legal = [command] if command in legal else []
        successors = []
        tested = 0
        for command in legal:
            tested += 1
            candidate = game.transition(command).game
            if PublicSnapshot.from_view(candidate.view(viewer)) != observed:
                continue
            successors.append(candidate)
            if max_successors is not None and len(successors) >= max_successors:
                break
        return ParticleAdvanceResult(tuple(successors), tested)


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


class ConstraintBeliefSampler:
    """Generate validator-approved worlds from ruleset role-slot constraints.

    This deliberately does not consult ``ScenarioLibrary``.  It is suitable for
    standard casts; scripts with character-specific setup fields will be added
    once those public setup facts are represented in ``PublicEvidence``.
    """

    @staticmethod
    def _plot_sets(evidence: PublicEvidence) -> list[tuple[str, tuple[str, ...]]]:
        spec = MODULES[evidence.module]
        mains = [plot for plot in spec.plots if PLOTS[plot][1] == "Y"]
        subplots = [plot for plot in spec.plots if PLOTS[plot][1] == "X"]
        known = set(evidence.known_plots)
        return [
            (main, tuple(selected))
            for main in mains
            for selected in combinations(subplots, spec.subplot_count)
            if known.issubset({main, *selected})
            and not ("wm_mad_truth" in selected)
        ]

    @staticmethod
    def _role_slots(module: str, plots: tuple[str, ...]) -> Counter[str]:
        spec = MODULES[module]
        expected: Counter[str] = Counter()
        for plot in plots:
            expected.update(PLOTS[plot][2])
        for role, cap in spec.role_caps.items():
            expected[role] = min(expected[role], cap)
        return +expected

    @staticmethod
    def _cast(evidence: PublicEvidence, slots: Counter[str],
              rng: random.Random) -> dict[str, str] | None:
        known = dict(evidence.known_roles)
        remaining = slots.copy()
        for cid, role in known.items():
            if cid not in evidence.characters:
                return None
            if role != "ordinary":
                if remaining[role] < 1:
                    return None
                remaining[role] -= 1
        unassigned = [cid for cid in evidence.characters if cid not in known]
        role_bag = list(remaining.elements())
        if len(role_bag) > len(unassigned):
            return None
        role_bag.extend(["ordinary"] * (len(unassigned) - len(role_bag)))
        rng.shuffle(role_bag)
        return {**known, **dict(zip(unassigned, role_bag))}

    @staticmethod
    def _incidents(evidence: PublicEvidence,
                   rng: random.Random) -> list[dict[str, Any]] | None:
        spec = MODULES[evidence.module]
        known = dict(evidence.known_culprits)
        incidents = []
        for day, public_kind in evidence.schedule:
            culprit = known.get(day, rng.choice(evidence.characters))
            if public_kind in spec.incidents:
                incidents.append({"day": day, "kind": public_kind,
                                  "culprit": culprit})
            elif "fake_incident" in spec.incidents:
                incidents.append({"day": day, "kind": "fake_incident",
                                  "public_kind": public_kind, "culprit": culprit})
            else:
                return None
        return incidents

    def sample(self, evidence: PublicEvidence, count: int, *,
               rng: random.Random, max_attempts: int | None = None
               ) -> tuple[HiddenWorldHypothesis, ...]:
        if type(count) is not int or count < 1:
            raise ValueError("count must be a positive integer")
        plot_sets = self._plot_sets(evidence)
        if not plot_sets:
            return ()
        limit = max_attempts or max(200, count * 100)
        hypotheses: list[HiddenWorldHypothesis] = []
        signatures: set[tuple[Any, ...]] = set()
        for attempt in range(limit):
            main, subplots = rng.choice(plot_sets)
            cast = self._cast(
                evidence, self._role_slots(evidence.module, (main, *subplots)), rng)
            incidents = self._incidents(evidence, rng)
            if cast is None or incidents is None:
                continue
            scenario = {
                "id": f"belief-{evidence.module.lower()}-{attempt}",
                "title": "ISMCTS sampled world", "module": evidence.module,
                "days": evidence.days, "loops": evidence.loops,
                "main_plot": main, "subplots": list(subplots),
                "cast": cast, "incidents": incidents, "table_talk": False,
            }
            try:
                validated = validate_scenario(scenario)
            except RuleError:
                continue
            hypothesis = HiddenWorldHypothesis.from_scenario(validated)
            signature = (hypothesis.main_plot, hypothesis.subplots,
                         hypothesis.roles, hypothesis.incidents)
            if signature in signatures:
                continue
            signatures.add(signature)
            hypotheses.append(hypothesis)
            if len(hypotheses) >= count:
                break
        return tuple(hypotheses)
