"""Information-safe hidden-world candidates for future ISMCTS agents.

The evidence object is intentionally constructed from a protagonist projection,
not from ``Game.scenario`` or ``Game.roles``.  Catalog sampling is the first
particle source; later generators can implement the full combinatorial script
space behind the same boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from collections import Counter
from copy import deepcopy
from functools import lru_cache
from itertools import combinations, permutations
import hashlib
import json
from math import factorial
import random
from typing import Any, Mapping, Sequence

from .catalog import CHARACTERS, MODULES, PLOTS, REFUSAL
from .engine import RuleError
from .scenario import validate_scenario
from .scenario_library import ScenarioLibrary


_PRESENTATION_FIELDS = {
    "description", "label", "labels", "language", "message", "module_name",
    "name", "passive", "phase_name", "scenario_id", "text", "timepoint",
    "title", "traits",
}


def _observed_role_matches(initial_role: str | None, observed_role: str,
                           plots: Sequence[str]) -> bool:
    """Whether a public current-role observation fits an initial script role."""
    if initial_role == observed_role:
        return True
    # Delusion Expansion Virus changes an Ordinary into a Serial Killer for
    # the current loop.  BTX's final guess still asks for the initial role.
    return (observed_role == "serial" and initial_role == "ordinary"
            and "virus" in plots)


def _player_view(game: Any, viewer: str) -> Mapping[str, Any]:
    return (game.protagonist_team_view() if viewer == "team"
            else game.view(viewer))


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
class CommandObservation:
    """Explicit per-seat visibility for one command checkpoint."""

    visibility: str
    fields: tuple[tuple[str, Any], ...] = ()
    hidden_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.visibility not in {"public", "partial", "hidden"}:
            raise ValueError("command visibility must be public, partial or hidden")
        if self.visibility == "public" and self.hidden_fields:
            raise ValueError("public command observations cannot hide fields")
        if self.visibility == "hidden" and self.fields:
            raise ValueError("hidden command observations cannot expose fields")

    @property
    def pattern(self) -> dict[str, Any] | None:
        return dict(self.fields) if self.fields else None


@dataclass(frozen=True)
class ObservationCheckpoint:
    """Compact semantic observations after one real engine decision."""

    decision: int
    digests: tuple[tuple[str, str], ...]
    command_observations: tuple[tuple[str, CommandObservation], ...] = ()

    def for_viewer(self, viewer: str) -> str:
        try:
            return dict(self.digests)[viewer]
        except KeyError as exc:
            raise ValueError(f"checkpoint has no viewer {viewer}") from exc

    def command_for_viewer(self, viewer: str) -> dict[str, Any] | None:
        observation = dict(self.command_observations).get(viewer)
        return None if observation is None else observation.pattern

    def visibility_for_viewer(self, viewer: str) -> CommandObservation | None:
        return dict(self.command_observations).get(viewer)


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
        if expected is not None and PublicSnapshot.from_view(
                _player_view(game, viewer)) != expected:
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
                observed: PublicSnapshot | str,
                public_command: Mapping[str, Any] | None = None,
                max_successors: int | None = None) -> ParticleAdvanceResult:
        if max_successors is not None and (
                type(max_successors) is not int or max_successors < 1):
            raise ValueError("max_successors must be a positive integer or None")
        legal = list(game.search_actions(game.controller))
        observed_digest = observed.digest if isinstance(observed, PublicSnapshot) else observed
        if public_command is not None:
            pattern = dict(public_command)
            legal = [command for command in legal
                     if all(command.get(key) == value
                            for key, value in pattern.items())]
        successors = []
        tested = 0
        for command in legal:
            tested += 1
            candidate = game.transition(command).game
            if PublicSnapshot.from_view(
                    _player_view(candidate, viewer)).digest != observed_digest:
                continue
            successors.append(candidate)
            if max_successors is not None and len(successors) >= max_successors:
                break
        return ParticleAdvanceResult(tuple(successors), tested)


@dataclass(frozen=True)
class ParticleFilterResult:
    particles: tuple[Any, ...]
    input_particles: int
    tested_actions: int
    matching_successors: int
    unique_successors: int


class BeliefParticleFilter:
    """Bound an observation update without choosing one hidden explanation."""

    def __init__(self, *, max_particles: int = 64,
                 rng: random.Random | None = None):
        if type(max_particles) is not int or max_particles < 1:
            raise ValueError("max_particles must be a positive integer")
        self.max_particles = max_particles
        self.rng = rng or random.Random(0)
        self.advancer = ObservationParticleAdvancer()

    @staticmethod
    def materialize(hypotheses: Sequence[HiddenWorldHypothesis],
                    evidence: PublicEvidence) -> tuple[Any, ...]:
        from .game import Game

        particles = []
        for hypothesis in hypotheses:
            try:
                particles.append(Game(hypothesis.materialize(evidence)))
            except RuleError:
                continue
        return tuple(particles)

    def advance(self, particles: Sequence[Any], *, viewer: str,
                observed: PublicSnapshot | str,
                public_command: Mapping[str, Any] | None = None
                ) -> ParticleFilterResult:
        reservoir: list[Any] = []
        seen_keys: set[str] = set()
        tested = 0
        matching = 0
        unique = 0
        for particle in particles:
            advanced = self.advancer.advance(
                particle, viewer=viewer, observed=observed,
                public_command=public_command)
            tested += advanced.tested_actions
            matching += len(advanced.successors)
            for successor in advanced.successors:
                private_key = successor.state_key("m")
                if private_key in seen_keys:
                    continue
                seen_keys.add(private_key)
                unique += 1
                if len(reservoir) < self.max_particles:
                    reservoir.append(successor)
                    continue
                replacement = self.rng.randrange(unique)
                if replacement < self.max_particles:
                    reservoir[replacement] = successor
        return ParticleFilterResult(
            particles=tuple(reservoir), input_particles=len(particles),
            tested_actions=tested, matching_successors=matching,
            unique_successors=unique)


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
        plots = (scenario["main_plot"], *scenario["subplots"])
        if any(not _observed_role_matches(roles.get(cid), role, plots)
               for cid, role in evidence.known_roles):
            return False
        incidents_by_day: dict[int, set[str]] = {}
        for item in scenario["incidents"]:
            incidents_by_day.setdefault(int(item["day"]), set()).add(str(item["culprit"]))
        if any(cid not in incidents_by_day.get(day, set())
               for day, cid in evidence.known_culprits):
            return False
        return all(plot in set(plots) for plot in evidence.known_plots)

    def candidates(self, evidence: PublicEvidence, *, witnesses=()
                   ) -> tuple[HiddenWorldHypothesis, ...]:
        from .witness import FsbtxWitnessMatcher

        matcher = FsbtxWitnessMatcher()
        hypotheses = []
        for summary in self.library.list(evidence.module):
            scenario = self.library.get(summary["id"])
            if self._matches(evidence, scenario):
                hypothesis = HiddenWorldHypothesis.from_scenario(scenario)
                if matcher.matches(hypothesis, witnesses):
                    hypotheses.append(hypothesis)
        return tuple(sorted(hypotheses, key=lambda item: item.scenario_id))

    def sample(self, evidence: PublicEvidence, count: int, *,
               rng: random.Random, witnesses=()) -> tuple[HiddenWorldHypothesis, ...]:
        if type(count) is not int or count < 1:
            raise ValueError("count must be a positive integer")
        candidates = self.candidates(evidence, witnesses=witnesses)
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
    def _irregular_roles(module: str, plots: Sequence[str]) -> tuple[str, ...]:
        """Printed Irregular roles are extra and do not consume plot slots."""
        selected = {role for plot in plots for role in PLOTS[plot][2]}
        available = {
            role for plot in MODULES[module].plots for role in PLOTS[plot][2]
        }
        return tuple(sorted(available - selected))

    @staticmethod
    def _cast(evidence: PublicEvidence, slots: Counter[str],
              plots: Sequence[str],
              rng: random.Random) -> dict[str, str] | None:
        known = dict(evidence.known_roles)
        remaining = slots.copy()
        assigned: dict[str, str] = {}
        if "irregular" in evidence.characters:
            options = list(ConstraintBeliefSampler._irregular_roles(
                evidence.module, plots))
            observed = known.pop("irregular", None)
            if observed is not None:
                options = [role for role in options
                           if _observed_role_matches(role, observed, plots)]
            if not options:
                return None
            assigned["irregular"] = rng.choice(options)
        for cid, observed in known.items():
            if cid not in evidence.characters:
                return None
            options = [observed]
            if observed == "serial" and "virus" in plots:
                options.append("ordinary")
            rng.shuffle(options)
            initial = next((role for role in options
                            if role == "ordinary" or remaining[role] > 0), None)
            if initial is None:
                return None
            assigned[cid] = initial
            if initial != "ordinary":
                if remaining[initial] < 1:
                    return None
                remaining[initial] -= 1
        unassigned = [cid for cid in evidence.characters if cid not in assigned]
        role_bag = list(remaining.elements())
        if len(role_bag) > len(unassigned):
            return None
        role_bag.extend(["ordinary"] * (len(unassigned) - len(role_bag)))
        rng.shuffle(role_bag)
        return {**assigned, **dict(zip(unassigned, role_bag))}

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
               rng: random.Random, max_attempts: int | None = None, witnesses=()
               ) -> tuple[HiddenWorldHypothesis, ...]:
        from .witness import FsbtxWitnessMatcher

        if type(count) is not int or count < 1:
            raise ValueError("count must be a positive integer")
        plot_sets = self._plot_sets(evidence)
        if not plot_sets:
            return ()
        has_soft = any(getattr(witness, "strength", None) == "soft"
                       for witness in witnesses)
        limit = max_attempts or max(200, count * (300 if has_soft else 100))
        hypotheses: list[HiddenWorldHypothesis] = []
        signatures: set[tuple[Any, ...]] = set()
        matcher = FsbtxWitnessMatcher()
        for attempt in range(limit):
            main, subplots = rng.choice(plot_sets)
            plots = (main, *subplots)
            cast = self._cast(
                evidence, self._role_slots(evidence.module, plots), plots, rng)
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
            if not matcher.matches(hypothesis, witnesses):
                continue
            if has_soft:
                score = matcher.soft_score(hypothesis, witnesses)
                # Keep every explanation possible while sampling worlds that
                # explain repeated public phenomena more often.
                if rng.random() >= min(1.0, 0.005 * (2.0 ** (score / 2.0))):
                    continue
            signature = (hypothesis.main_plot, hypothesis.subplots,
                         hypothesis.roles, hypothesis.incidents)
            if signature in signatures:
                continue
            signatures.add(signature)
            hypotheses.append(hypothesis)
            if len(hypotheses) >= count:
                break
        return tuple(hypotheses)


@dataclass(frozen=True)
class FactorizedBeliefResult:
    worlds: tuple[HiddenWorldHypothesis, ...]
    role_candidates: int
    culprit_options: tuple[tuple[int, int], ...]
    reason: str | None = None


@dataclass(frozen=True)
class ExactRoleMapResult:
    """Exact final-guess MAP over the legal joint role-assignment space."""

    ranked: tuple[tuple[HiddenWorldHypothesis, float], ...]
    compatible_count: int
    plot_sets: int

    @property
    def selected(self) -> HiddenWorldHypothesis | None:
        return self.ranked[0][0] if self.ranked else None


class FactorizedBeliefState:
    """Keep script/role and per-day culprit beliefs independent.

    Dark cards are deliberately absent here: they are sampled from the public
    hand and pending targets only when a search world is materialized.
    Every update scores the accumulated public witnesses afresh, so evidence
    cannot be counted twice by repeatedly resampling a particle reservoir.
    """

    def __init__(self, *, capacity: int = 192, seed: int = 0):
        self.capacity = capacity
        self.rng = random.Random(seed)
        self.sampler = ConstraintBeliefSampler()
        self._signature: tuple[Any, ...] | None = None
        self._roles: dict[tuple[Any, ...], HiddenWorldHypothesis] = {}
        self._exact_roles = False
        self._plot_sizes: Counter[tuple[str, tuple[str, ...]]] = Counter()

    @staticmethod
    def _key(world: HiddenWorldHypothesis) -> tuple[Any, ...]:
        return world.main_plot, world.subplots, world.roles

    def _enumerate_roles(self, evidence: PublicEvidence) -> None:
        for main, subplots in self.sampler._plot_sets(evidence):
            slots = self.sampler._role_slots(evidence.module,
                                            (main, *subplots))
            bag = list(slots.elements())
            characters = tuple(cid for cid in evidence.characters
                               if cid != "irregular")
            irregular_roles = (self.sampler._irregular_roles(
                evidence.module, (main, *subplots))
                if "irregular" in evidence.characters else (None,))
            if not irregular_roles or len(bag) > len(characters):
                continue
            bag.extend(["ordinary"] * (len(characters) - len(bag)))
            incidents = self.sampler._incidents(evidence, self.rng)
            if incidents is None:
                continue
            for assignment in sorted(set(permutations(bag))):
                for irregular_role in irregular_roles:
                    self._plot_sizes[(main, subplots)] += 1
                    cast = dict(zip(characters, assignment))
                    if irregular_role is not None:
                        cast["irregular"] = irregular_role
                    plots = (main, *subplots)
                    if any(not _observed_role_matches(
                            cast.get(cid), role, plots)
                           for cid, role in evidence.known_roles):
                        continue
                    try:
                        scenario = validate_scenario({
                            "id": "belief-exact-roles",
                            "title": "ISMCTS exact roles",
                            "module": evidence.module, "days": evidence.days,
                            "loops": evidence.loops, "main_plot": main,
                            "subplots": list(subplots), "cast": cast,
                            "incidents": incidents,
                            "table_talk": evidence.table_talk,
                        })
                    except RuleError:
                        continue
                    world = HiddenWorldHypothesis.from_scenario(scenario)
                    self._roles[self._key(world)] = world

    def _refresh_roles(self, evidence: PublicEvidence, witnesses: Sequence[Any]) -> None:
        from .witness import FsbtxWitnessMatcher

        matcher = FsbtxWitnessMatcher()
        role_witnesses = self._role_witnesses(witnesses)
        signature = PersistentBeliefState._static_signature(evidence)
        if signature != self._signature:
            self._signature = signature
            self._roles.clear()
            self._plot_sizes.clear()
            self._exact_roles = len(evidence.characters) <= 6
            if self._exact_roles:
                self._enumerate_roles(evidence)
        self._roles = {key: world for key, world in self._roles.items()
                       if matcher.matches(world, role_witnesses)}
        # Keep a diverse reservoir across decisions, and continue proposing
        # scripts even when the reservoir is full. A witness can then promote
        # a previously unseen role assignment without any history replay.
        proposed = (() if self._exact_roles else self.sampler.sample(
            evidence, min(64, self.capacity), rng=self.rng,
            witnesses=tuple(w for w in role_witnesses if w.strength == "hard")))
        for world in proposed:
            key = self._key(world)
            if key in self._roles or not matcher.matches(world, role_witnesses):
                continue
            if len(self._roles) >= self.capacity:
                old = self.rng.choice(tuple(self._roles))
                del self._roles[old]
            self._roles[key] = world

    def _culprits(self, evidence: PublicEvidence,
                  witnesses: Sequence[Any]) -> dict[int, tuple[str, ...]]:
        from .witness import FsbtxWitnessMatcher, WitnessVerdict

        matcher = FsbtxWitnessMatcher()
        known = dict(evidence.known_culprits)
        result: dict[int, tuple[str, ...]] = {}
        for day, public_kind in evidence.schedule:
            day_witnesses = tuple(w for w in witnesses if w.kind in {
                "culprit_is", "culprit_in", "incident_happened",
                "incident_not_happened"}
                and int(w.subject) == day)
            candidates = []
            for cid in evidence.characters:
                if day in known and known[day] != cid:
                    continue
                # The incident matcher reads only the one event tuple here.
                candidate = HiddenWorldHypothesis(
                    "belief-culprit", "", (), (),
                    ((day, public_kind, public_kind, cid),))
                if all(w.strength != "hard" or matcher.verdict(
                        candidate, w) != WitnessVerdict.CONTRADICTED
                       for w in day_witnesses):
                    candidates.append(cid)
            result[day] = tuple(candidates)
        return result

    def role_posterior(self, evidence: PublicEvidence,
                       witnesses: Sequence[Any]
                       ) -> tuple[tuple[HiddenWorldHypothesis, float], ...]:
        """Return the candidate *joint* role assignments and their weights.

        Final guessing must rank complete assignments directly. Sampling a
        small number of full worlds would turn a large, mostly unique BTX
        identity space into an arbitrary tie-break between singletons.
        """
        from .witness import FsbtxWitnessMatcher

        self._refresh_roles(evidence, witnesses)
        matcher = FsbtxWitnessMatcher()
        role_witnesses = self._role_witnesses(witnesses)
        return tuple((world,
                      2.0 ** matcher.soft_score(world, role_witnesses)
                      / (self._plot_sizes[(world.main_plot, world.subplots)]
                         if self._exact_roles else 1))
                     for world in self._roles.values())

    @staticmethod
    def _role_witnesses(witnesses: Sequence[Any]) -> tuple[Any, ...]:
        return tuple(w for w in witnesses if w.kind in {
            "role_is", "role_in", "role_not_in", "plot_present",
            "plot_not_present", "plot_pressure",
            "day_end_death_companion", "joint_plot_role_pressure",
            "role_pressure", "day_end_killer_candidate", "loss_after_death",
            "loop_end_plot_explanation", "role_route_pressure",
            "mastermind_ability_route"})

    @staticmethod
    def _assignment_count(characters: tuple[str, ...],
                          domains: Mapping[str, tuple[str, ...]],
                          counts: Counter[str], *,
                          friend_gender_split: bool = False,
                          used_friend_genders: tuple[bool, bool] = (False, False)
                          ) -> int:
        roles = tuple(sorted(counts))

        @lru_cache(maxsize=None)
        def visit(index: int, remaining: tuple[int, ...],
                  used_male: bool, used_female: bool) -> int:
            if index == len(characters):
                return int(not any(remaining))
            values = dict(zip(roles, remaining))
            total = 0
            for role in domains[characters[index]]:
                if values.get(role, 0) < 1:
                    continue
                next_male, next_female = used_male, used_female
                if friend_gender_split and role == "friend":
                    traits = CHARACTERS[characters[index]].traits
                    male = "boy" in traits or "man" in traits
                    female = "girl" in traits or "woman" in traits
                    if (male and used_male) or (female and used_female):
                        continue
                    next_male = used_male or male
                    next_female = used_female or female
                next_remaining = list(remaining)
                next_remaining[roles.index(role)] -= 1
                total += visit(index + 1, tuple(next_remaining),
                               next_male, next_female)
            return total

        return visit(0, tuple(counts[role] for role in roles),
                     *used_friend_genders)

    @classmethod
    def _complete_assignment(cls, characters: tuple[str, ...],
                             domains: Mapping[str, tuple[str, ...]],
                             counts: Counter[str], fixed: Mapping[str, str], *,
                             friend_gender_split: bool = False
                             ) -> dict[str, str] | None:
        remaining = counts.copy()
        result = dict(fixed)
        used_male = used_female = False
        for cid, role in fixed.items():
            if cid not in characters:
                continue
            if role not in domains[cid] or remaining[role] < 1:
                return None
            if friend_gender_split and role == "friend":
                traits = CHARACTERS[cid].traits
                male = "boy" in traits or "man" in traits
                female = "girl" in traits or "woman" in traits
                if (male and used_male) or (female and used_female):
                    return None
                used_male = used_male or male
                used_female = used_female or female
            remaining[role] -= 1
        unassigned = tuple(cid for cid in sorted(characters)
                           if cid not in result)
        for index, cid in enumerate(unassigned):
            tail = unassigned[index + 1:]
            selected = None
            for role in sorted(domains[cid], reverse=True):
                if remaining[role] < 1:
                    continue
                next_male, next_female = used_male, used_female
                if friend_gender_split and role == "friend":
                    traits = CHARACTERS[cid].traits
                    male = "boy" in traits or "man" in traits
                    female = "girl" in traits or "woman" in traits
                    if (male and used_male) or (female and used_female):
                        continue
                    next_male = used_male or male
                    next_female = used_female or female
                remaining[role] -= 1
                if cls._assignment_count(
                        tail, domains, remaining,
                        friend_gender_split=friend_gender_split,
                        used_friend_genders=(next_male, next_female)) > 0:
                    selected = role
                    used_male, used_female = next_male, next_female
                    break
                remaining[role] += 1
            if selected is None:
                return None
            result[cid] = selected
        return result if not any(remaining.values()) else None

    @staticmethod
    def _soft_realizations(witness: Any, main: str,
                           plots: Sequence[str]) -> tuple[dict[str, str], ...]:
        """Small constructive alternatives that can satisfy one soft factor."""
        value = witness.value
        if witness.kind == "mastermind_ability_route":
            if set(value.get("plots", ())) & {main, *plots}:
                return ({},)
            return tuple({str(cid): str(role)}
                         for role, candidates in value.get("roles", {}).items()
                         for cid in candidates)
        if witness.kind == "joint_plot_role_pressure":
            if main != witness.subject:
                return ({},)
            return ({}, *({str(cid): str(value["role"])}
                           for cid in value.get("candidates", ())))
        if witness.kind == "role_pressure":
            return ({}, *({str(cid): str(witness.subject)}
                           for cid in value.get("candidates", ())))
        if witness.kind == "day_end_death_companion":
            cid = str(value.get("character") if isinstance(value, Mapping)
                      else value)
            options = [{cid: "serial"}]
            if (isinstance(value, Mapping) and value.get("virus_eligible")
                    and "virus" in plots):
                options.append({cid: "ordinary"})
            return ({}, *options)
        if witness.kind == "day_end_killer_candidate":
            return ({}, {str(witness.subject): "key",
                         str(value): "killer"})
        if witness.kind == "loss_after_death":
            cid = str(witness.subject)
            roles = ["key", "friend"]
            if isinstance(value, Mapping) and value.get("factor_key_possible"):
                roles.append("factor")
            return ({}, *({cid: role} for role in roles))
        return ({},)

    def exact_role_map(self, evidence: PublicEvidence,
                       witnesses: Sequence[Any], *, top: int = 8
                       ) -> ExactRoleMapResult:
        """Solve final identity guessing independently of the action reservoir.

        Soft role evidence consists of a small set of unary, pair, or
        existential predicates.  We enumerate ways to realize those predicates,
        then fill all evidence-irrelevant roles deterministically.  This finds
        the exact maximum score without enumerating millions of symmetric
        Ordinary placements.
        """
        from .witness import FsbtxWitnessMatcher, WitnessStrength

        matcher = FsbtxWitnessMatcher()
        role_witnesses = self._role_witnesses(witnesses)
        soft = tuple(w for w in role_witnesses
                     if w.strength == WitnessStrength.SOFT)
        # Repeated observations share one realization choice; the matcher still
        # counts each occurrence and applies the normal per-channel cap.
        unique_soft: dict[str, Any] = {}
        for witness in soft:
            signature = json.dumps(
                [witness.kind, witness.subject, witness.value],
                sort_keys=True, ensure_ascii=False, default=str)
            unique_soft.setdefault(signature, witness)

        ranked: list[tuple[HiddenWorldHypothesis, float]] = []
        compatible_count = 0
        plot_sets = 0
        known_roles = dict(evidence.known_roles)
        known_role_sets: dict[str, set[str]] = {}
        excluded_roles: dict[str, set[str]] = {}
        for witness in role_witnesses:
            if witness.strength != WitnessStrength.HARD:
                continue
            if witness.kind == "role_is":
                subject = ("part_timer" if witness.subject ==
                           "part_timer_question" else str(witness.subject))
                known_roles[subject] = str(witness.value)
            elif witness.kind == "role_in":
                subject = ("part_timer" if witness.subject ==
                           "part_timer_question" else str(witness.subject))
                known_role_sets.setdefault(subject, set(
                    str(role) for role in witness.value))
            elif witness.kind == "role_not_in":
                subject = ("part_timer" if witness.subject ==
                           "part_timer_question" else str(witness.subject))
                excluded_roles.setdefault(subject, set()).update(
                    str(role) for role in witness.value)

        known_culprits = dict(evidence.known_culprits)
        used_culprits: set[str] = set()
        incident_rows = []
        for day, kind in evidence.schedule:
            culprit = known_culprits.get(day)
            if culprit is None:
                culprit = next((cid for cid in evidence.characters
                                if cid not in used_culprits),
                               evidence.characters[0])
            if kind != "serial_murder":
                used_culprits.add(culprit)
            incident_rows.append((day, kind, kind, culprit))
        incidents = tuple(incident_rows)
        for main, subplots in self.sampler._plot_sets(evidence):
            plots = (main, *subplots)
            if any(witness.strength == WitnessStrength.HARD
                   and witness.kind == "plot_present"
                   and witness.subject not in plots
                   for witness in role_witnesses):
                continue
            if any(witness.strength == WitnessStrength.HARD
                   and witness.kind == "plot_not_present"
                   and witness.subject in plots
                   for witness in role_witnesses):
                continue
            slots = self.sampler._role_slots(evidence.module, plots)
            regular = tuple(cid for cid in evidence.characters
                            if cid != "irregular")
            if sum(slots.values()) > len(regular):
                continue
            counts = slots.copy()
            counts["ordinary"] += len(regular) - sum(counts.values())
            available = tuple(sorted(counts))
            domains: dict[str, tuple[str, ...]] = {}
            for cid in regular:
                observed = known_roles.get(cid)
                allowed = tuple(role for role in available
                                if (observed is None or _observed_role_matches(
                                    role, observed, plots))
                                and not ("sign" in plots and role == "key"
                                        and "girl" not in CHARACTERS[cid].traits)
                                and not (cid == "little_sister"
                                        and role in REFUSAL)
                                and not (cid == "ai" and role == "ordinary")
                                and (cid not in known_role_sets
                                     or role in known_role_sets[cid])
                                and role not in excluded_roles.get(cid, ()))
                domains[cid] = allowed
            if any(not domain for domain in domains.values()):
                continue
            irregular_options: tuple[str | None, ...] = (None,)
            if "irregular" in evidence.characters:
                irregular_options = self.sampler._irregular_roles(
                    evidence.module, plots)
                observed = known_roles.get("irregular")
                irregular_options = tuple(
                    role for role in irregular_options
                    if (observed is None or _observed_role_matches(
                        role, observed, plots))
                    and ("irregular" not in known_role_sets
                         or role in known_role_sets["irregular"])
                    and role not in excluded_roles.get("irregular", ()))
                if not irregular_options:
                    continue
            gender_split = MODULES[evidence.module].friend_gender_split
            assignment_count = self._assignment_count(
                regular, domains, counts,
                friend_gender_split=gender_split)
            if assignment_count == 0:
                continue
            plot_sets += 1
            compatible_count += assignment_count * len(irregular_options)
            unconstrained_size = (factorial(len(regular)) //
                                  max(1, factorial(len(regular) -
                                                   sum(slots.values()))))
            for amount in slots.values():
                unconstrained_size //= factorial(amount)
            unconstrained_size *= len(irregular_options)

            hard_routes = {json.dumps(
                [witness.kind, witness.subject, witness.value],
                sort_keys=True, ensure_ascii=False, default=str): witness
                for witness in role_witnesses
                if witness.strength == WitnessStrength.HARD
                and witness.kind == "mastermind_ability_route"}
            realization_groups = tuple(
                self._soft_realizations(witness, main, plots)
                for witness in (*unique_soft.values(), *hard_routes.values()))
            seen_roles: set[tuple[tuple[str, str], ...]] = set()

            def propose(index: int, fixed: dict[str, str]) -> None:
                if index < len(realization_groups):
                    for addition in realization_groups[index]:
                        merged = dict(fixed)
                        compatible = True
                        for cid, role in addition.items():
                            if cid not in evidence.characters:
                                compatible = False
                                break
                            if cid in merged and merged[cid] != role:
                                compatible = False
                                break
                            if cid != "irregular" and role not in domains[cid]:
                                compatible = False
                                break
                            merged[cid] = role
                        if compatible:
                            propose(index + 1, merged)
                    return
                for irregular_role in irregular_options:
                    if ("irregular" in fixed
                            and fixed["irregular"] != irregular_role):
                        continue
                    roles = self._complete_assignment(
                        regular, domains, counts, fixed,
                        friend_gender_split=gender_split)
                    if roles is None:
                        continue
                    if irregular_role is not None:
                        roles["irregular"] = irregular_role
                    signature = tuple(sorted(roles.items()))
                    if signature in seen_roles:
                        continue
                    seen_roles.add(signature)
                    world = HiddenWorldHypothesis(
                        "belief-exact-map", main, subplots, signature, incidents)
                    if not matcher.matches(world, role_witnesses):
                        continue
                    weight = (2.0 ** matcher.soft_score(
                        world, role_witnesses) / max(1, unconstrained_size))
                    ranked.append((world, weight))

            propose(0, {})

        ordered = sorted(
            ranked,
            key=lambda pair: (pair[1], tuple(sorted(pair[0].roles)),
                              pair[0].main_plot, pair[0].subplots),
            reverse=True)
        return ExactRoleMapResult(tuple(ordered[:max(1, top)]),
                                  compatible_count, plot_sets)

    def sample(self, evidence: PublicEvidence, witnesses: Sequence[Any],
               count: int, *, rng: random.Random) -> FactorizedBeliefResult:
        from .witness import FsbtxWitnessMatcher

        if count < 1:
            raise ValueError("count must be positive")
        ranked_roles = self.role_posterior(evidence, witnesses)
        culprits = self._culprits(evidence, witnesses)
        sizes = tuple((day, len(options)) for day, options in sorted(culprits.items()))
        if not ranked_roles or any(not options for options in culprits.values()):
            return FactorizedBeliefResult((), len(ranked_roles), sizes,
                                          "no_compatible_factor")
        matcher = FsbtxWitnessMatcher()
        roles = tuple(world for world, _ in ranked_roles)
        weights = [weight for _, weight in ranked_roles]
        culprit_witnesses = tuple(w for w in witnesses if w.kind in {
            "culprit_is", "culprit_in", "incident_happened",
            "incident_not_happened"})
        culprit_weights = {
            day: [2.0 ** matcher.soft_score(HiddenWorldHypothesis(
                "belief-culprit", "", (), (),
                ((day, kind, kind, cid),)), culprit_witnesses)
                  for cid in culprits[day]]
            for day, kind in evidence.schedule
        }
        worlds = []
        attempts = 0
        while len(worlds) < count and attempts < count * 12:
            attempts += 1
            role = rng.choices(roles, weights=weights, k=1)[0]
            incidents = tuple((day, kind, public_kind,
                               rng.choices(culprits[day],
                                           weights=culprit_weights[day], k=1)[0])
                              for day, kind, public_kind, _ in role.incidents)
            world = replace(role, incidents=incidents)
            try:
                world.materialize(evidence)
            except RuleError:
                continue
            worlds.append(world)
        return FactorizedBeliefResult(tuple(worlds), len(roles), sizes,
                                      None if worlds else "composition_invalid")


class DarkCardBelief:
    """Draw only currently hidden card faces, conditional on public hand data."""

    @classmethod
    def placement_tendencies(cls, events: Sequence[Mapping[str, Any]], *,
                             day: int, loop: int, days: int,
                             targets: Sequence[str], cards: Sequence[str]
                             ) -> tuple[dict[str, Any], ...]:
        """Smoothed behavioral posterior, diagnostic rather than a hard fact.

        The same recency-weighted evidence drives ``sample``. Target and
        face probabilities are separate because today's targets are public,
        while faces remain hidden. Card depletion is handled during sampling.
        """
        history = cls.historical_weights(events, day=day, loop=loop, days=days)
        unique_targets = tuple(dict.fromkeys(targets))
        available = tuple(dict.fromkeys(cards))
        if not unique_targets or not available:
            return ()
        target_weights = {target: 1.0 + sum(
            weight for (seen_target, _), weight in history.items()
            if seen_target == target) for target in unique_targets}
        total_targets = sum(target_weights.values())
        result = []
        for target in unique_targets:
            face_weights = {card: 1.0 + history.get((target, card), 0.0)
                            for card in available}
            total_faces = sum(face_weights.values())
            result.append({
                "target": target,
                "target_probability": target_weights[target] / total_targets,
                "card_probabilities": {
                    card: 0.25 / len(available) + 0.75 * weight / total_faces
                    for card, weight in face_weights.items()},
            })
        return tuple(result)

    @staticmethod
    def historical_weights(events: Sequence[Mapping[str, Any]], *,
                           day: int, loop: int, days: int = 4
                           ) -> dict[tuple[str, str], float]:
        """Past public reveals inform a prior, never a hard constraint."""
        weights: dict[tuple[str, str], float] = {}
        for event in events:
            if (event.get("kind") != "cards_revealed"
                    or (int(event.get("loop", loop)),
                        int(event.get("round", day))) >= (loop, day)):
                continue
            age = max(1, (loop - int(event["loop"])) * days
                      + day - int(event["round"]))
            same_day = int(event["round"]) == day
            for placement in event.get("cards", ()):
                if placement.get("actor") != "m":
                    continue
                target, card = placement.get("target"), placement.get("card")
                if isinstance(target, str) and isinstance(card, str):
                    key = (target, card)
                    weights[key] = weights.get(key, 0.0) + (
                        6.0 * (1.5 if same_day else 1.0) * 0.85 ** (age - 1))
        return weights

    @staticmethod
    def sample(pending: Sequence[Mapping[str, Any]],
               hands: Mapping[str, list[str]], *,
               rng: random.Random,
               historical_weights: Mapping[tuple[str, str], float] | None = None,
               uniform_fraction: float = 0.25,
               force_history: bool = False,
               ) -> tuple[tuple[str, str, str], ...] | None:
        remaining = {actor: list(cards) for actor, cards in hands.items()}
        for item in pending:
            card = item.get("card")
            if card is None:
                continue
            available = remaining[str(item["actor"])]
            if card not in available:
                return None
            available.remove(card)
        selected = []
        for item in pending:
            actor = str(item["actor"])
            card = item.get("card")
            available = remaining[actor]
            if card is None:
                if not available:
                    return None
                if (historical_weights and force_history
                        and any(historical_weights.get((str(item["target"]), candidate), 0.0)
                                for candidate in available)):
                    target = str(item["target"])
                    card = max(available, key=lambda candidate: (
                        historical_weights.get((target, candidate), 0.0),
                        -available.index(candidate)))
                elif (historical_weights and rng.random() >= uniform_fraction):
                    target = str(item["target"])
                    card = rng.choices(
                        available,
                        weights=[1.0 + historical_weights.get((target, candidate), 0.0)
                                 for candidate in available], k=1)[0]
                else:
                    card = rng.choice(available)
                available.remove(card)
            selected.append((actor, str(card), str(item["target"])))
        return tuple(selected)


@dataclass(frozen=True)
class PersistentBeliefSync:
    particles: tuple[Any, ...]
    initialized: bool
    processed: int
    tested_actions: int
    matching_successors: int
    reason: str | None = None


class PersistentBeliefState:
    """Advance one seat's private particles through its public observations.

    The tracker receives only protagonist-view snapshot hashes plus the subset
    of each command that was public to that seat.  It never consumes the real
    scenario or the server's hidden command history.
    """

    def __init__(self, *, max_particles: int = 24, seed: int = 0):
        if type(max_particles) is not int or max_particles < 1:
            raise ValueError("max_particles must be a positive integer")
        self.max_particles = max_particles
        self.rng = random.Random(seed)
        self.filter = BeliefParticleFilter(
            max_particles=max_particles, rng=self.rng)
        self.particles: tuple[Any, ...] = ()
        self.last_decision = -1
        self._signature: tuple[Any, ...] | None = None
        self._witness_signature: str | None = None

    @staticmethod
    def _static_signature(evidence: PublicEvidence) -> tuple[Any, ...]:
        return (evidence.module, evidence.days, evidence.loops,
                evidence.table_talk, evidence.characters, evidence.schedule)

    def reset(self) -> None:
        self.particles = ()
        self.last_decision = -1
        self._signature = None
        self._witness_signature = None

    @staticmethod
    def _condition_reveal(particle: Any,
                          disclosed: Sequence[Mapping[str, Any]]) -> Any | None:
        """Condition unrevealed dark cards on a later public reveal.

        This is a particle bridge, not private information: the cards are read
        from the protagonist's already visible journal.  Without it a bounded
        reservoir is unlikely to contain the exact three-card dark bundle.
        """
        pending = [item for item in particle.state.pending if item.actor == "m"]
        if not pending:
            return particle
        known = {(str(item.get("actor")), str(item.get("target"))):
                 str(item.get("card")) for item in disclosed
                 if item.get("actor") == "m" and item.get("card") is not None}
        if any((item.actor, item.target) not in known for item in pending):
            return None
        world = deepcopy(particle)
        hand = world.state.hands["m"]
        hand.extend(item.card for item in pending)
        changed = []
        for item in world.state.pending:
            if item.actor != "m":
                changed.append(item)
                continue
            card = known[(item.actor, item.target)]
            if card not in hand:
                return None
            hand.remove(card)
            changed.append(replace(item, card=card))
        world.state.pending = changed
        return world

    @staticmethod
    def _incident_variants(particle: Any, evidence: PublicEvidence,
                           happened: bool) -> tuple[Any, ...]:
        """Rejuvenate a first-loop hidden culprit at its public resolution."""
        incident = next((item for item in particle.scenario["incidents"]
                         if item["day"] == particle.state.round), None)
        if incident is None or particle.state.loop != 1 or not happened:
            return (particle,)
        known = dict(evidence.known_culprits).get(particle.state.round)
        variants = []
        for cid in evidence.characters:
            if known is not None and cid != known:
                continue
            world = deepcopy(particle)
            selected = next(item for item in world.scenario["incidents"]
                            if item["day"] == world.state.round)
            selected["culprit"] = cid
            variants.append(world)
        return tuple(variants)

    def sync(self, evidence: PublicEvidence, *, viewer: str,
             observations: Sequence[tuple[int, str, CommandObservation | None]],
             witnesses=(), sampler: ConstraintBeliefSampler | None = None,
             revealed_placements: Mapping[tuple[int, int],
                                          Sequence[Mapping[str, Any]]] | None = None,
             incident_outcomes: Mapping[tuple[int, int], bool] | None = None
             ) -> PersistentBeliefSync:
        records = tuple(observations)
        if not records:
            return PersistentBeliefSync(
                self.particles, False, 0, 0, 0, "no_observations")
        signature = self._static_signature(evidence)
        initialized = False
        if self._signature != signature or self.last_decision > records[-1][0]:
            self.reset()
        elif self._signature == signature and not self.particles:
            # Particle depletion is a bounded-sampling failure, not proof that
            # the public history is impossible.  Retry from the full record on
            # the next decision with a fresh deterministic RNG position.
            self.reset()
        if self._signature is None:
            source = sampler or ConstraintBeliefSampler()
            hypotheses = source.sample(
                evidence, self.max_particles, rng=self.rng,
                witnesses=witnesses)
            candidates = self.filter.materialize(hypotheses, evidence)
            initial_decision, initial_digest, _ = records[0]
            self.particles = tuple(
                particle for particle in candidates
                if PublicSnapshot.from_view(_player_view(particle, viewer)).digest
                == initial_digest)
            self.last_decision = initial_decision
            self._signature = signature
            initialized = True
        processed = tested = matching = 0
        for decision, digest, command_observation in records:
            if decision <= self.last_decision:
                continue
            if decision != self.last_decision + 1:
                self.particles = ()
                self.last_decision = decision
                return PersistentBeliefSync(
                    (), initialized, processed, tested, matching,
                    "observation_gap")
            if revealed_placements and self.particles:
                conditioned = []
                for particle in self.particles:
                    if particle.state.phase != "reveal":
                        conditioned.append(particle)
                        continue
                    disclosed = revealed_placements.get(
                        (particle.state.loop, particle.state.round))
                    if disclosed is None:
                        conditioned.append(particle)
                        continue
                    bridged = self._condition_reveal(particle, disclosed)
                    if bridged is not None:
                        conditioned.append(bridged)
                self.particles = tuple(conditioned)
            if incident_outcomes and self.particles:
                expanded = []
                for particle in self.particles:
                    if particle.state.phase != "incident":
                        expanded.append(particle)
                        continue
                    outcome = incident_outcomes.get(
                        (particle.state.loop, particle.state.round))
                    if outcome is None:
                        expanded.append(particle)
                    else:
                        expanded.extend(self._incident_variants(
                            particle, evidence, outcome))
                self.particles = tuple(expanded)
            result = self.filter.advance(
                self.particles, viewer=viewer, observed=digest,
                public_command=(None if command_observation is None
                                else command_observation.pattern))
            self.particles = result.particles
            self.last_decision = decision
            processed += 1
            tested += result.tested_actions
            matching += result.matching_successors
            if not self.particles:
                return PersistentBeliefSync(
                    (), initialized, processed, tested, matching,
                    "all_particles_rejected")
        witness_signature = repr(tuple(witnesses))
        if not witnesses:
            self._witness_signature = witness_signature
        elif self.particles and witness_signature != self._witness_signature:
            from .witness import FsbtxWitnessMatcher

            matcher = FsbtxWitnessMatcher()
            weighted: list[tuple[Any, float]] = []
            for particle in self.particles:
                hypothesis = HiddenWorldHypothesis.from_scenario(
                    particle.scenario)
                if matcher.matches(hypothesis, witnesses):
                    weighted.append((
                        particle,
                        2.0 ** min(9.0, matcher.soft_score(
                            hypothesis, witnesses))))
            if not weighted:
                self.particles = ()
                return PersistentBeliefSync(
                    (), initialized, processed, tested, matching,
                    "witnesses_rejected_all_particles")
            if (len(weighted) != len(self.particles)
                    or any(weight != 1.0 for _, weight in weighted)):
                target = min(self.max_particles, max(len(self.particles), 1))
                self.particles = tuple(self.rng.choices(
                    [item for item, _ in weighted],
                    weights=[weight for _, weight in weighted], k=target))
            self._witness_signature = witness_signature
        return PersistentBeliefSync(
            self.particles, initialized, processed, tested, matching)
