"""Shared public-belief planning infrastructure; no legacy search policy.

Owns observation permissions, hypothesis materialization, traces, plan execution
and joint MAP final guesses. Fair particle planning and historical ISMCTS reuse
these facilities without inheriting each other's action-search algorithms.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import random
from typing import Any, Mapping, Sequence

from .ai import DefensiveProtagonistAgent
from .ai_decisions import JointCardDecisionProvider
from .belief import (CommandObservation, ConstraintBeliefSampler, DarkCardBelief,
                     FactorizedBeliefState, PersistentBeliefState, PublicEvidence)
from .cards import ACTORS
from .engine import Character, Placement, RuleError
from .evaluation import ScenarioConditionedEvaluator
from .game import Game
from .search import SearchBudget
from .witness import FsbtxWitnessCompiler, FsbtxWitnessMatcher, PublicEvidenceLedger


def _command(offer: Mapping[str, Any]) -> dict[str, Any]:
    kind = str(offer.get("type", offer.get("kind", ""))).removeprefix("core.")
    return {"actor": offer["actor"], "action": kind,
            **deepcopy(dict(offer.get("parameters", {})))}


def _key(command: Mapping[str, Any]) -> str:
    return json.dumps(command, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


@dataclass(frozen=True)
class IsmctsTrace:
    strategy: str
    seed: int
    module: str
    particles: int
    witnesses: int
    iterations: int
    rollout_depth: int
    fallback: str | None
    selected_action_id: str
    root_actions: tuple[dict[str, Any], ...]
    belief_roles: tuple[dict[str, Any], ...] = ()
    belief_source: str = "resampled"
    observation_updates: int = 0
    evidence_hard: int = 0
    evidence_soft: int = 0
    evidence_elapsed_ms: float = 0.0
    search_elapsed_ms: float = 0.0
    planned_commands: tuple[dict[str, Any], ...] = ()
    belief_failure: str | None = None
    role_candidates: int = 0
    culprit_options: tuple[tuple[int, int], ...] = ()
    belief_culprits: tuple[dict[str, Any], ...] = ()
    belief_dark_cards: tuple[dict[str, Any], ...] = ()
    placement_tendencies: tuple[dict[str, Any], ...] = ()
    evaluated_pairs: int = 0
    stop_reason: str | None = None
    belief_setups: tuple[dict[str, Any], ...] = ()
    rollout_horizon: str = "day"
    mastermind_policy_samples: int = 1
    mastermind_policy_aggregation: str = "single"
    information_reward_weight: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self), ensure_ascii=False,
                                     allow_nan=False))


class PublicStateDeterminizer:
    """Materialize one sampled setup at a protagonist-visible action state."""

    _CHARACTER_FIELDS = (
        "location", "forbidden", "paranoia", "goodwill", "intrigue",
        "hope", "despair", "alive", "present", "action_targetable",
        "echo_board_actions",
    )

    def determinize(self, hypothesis: Any, evidence: PublicEvidence,
                    view: Mapping[str, Any], *, rng: random.Random,
                    history_prior: bool = False,
                    force_history: bool = False,
                    coherent_history: bool = False) -> Game | None:
        if view.get("module") not in ("FS", "BTX") or view.get("phase") != "protagonists":
            return None
        try:
            game = Game(hypothesis.materialize(evidence))
        except RuleError:
            return None
        state = game.state
        state.loop = int(view["loop"])
        state.round = int(view["round"])
        state.phase = "protagonists"
        state.leader = str(view["leader"])
        state.locations = deepcopy(dict(view["locations"]))
        game.mastermind_plays = int(view["action_counts"]["mastermind"])
        game.protagonist_order = tuple(view["protagonist_order"])
        for cid, observed in view["characters"].items():
            if cid not in state.characters:
                state.characters[cid] = Character(
                    cid, str(observed.get("name", cid)), str(observed["location"]),
                    tuple(observed.get("forbidden", ())))
                game.roles[cid] = game.roles.get("part_timer", "ordinary")
                game.guards[cid] = 0
                game.ex_cards[cid] = 0
            character = state.characters[cid]
            for field in self._CHARACTER_FIELDS:
                if field in observed:
                    value = observed[field]
                    setattr(character, field, tuple(value) if field == "forbidden" else value)
            game.guards[cid] = int(observed.get("guard", 0))
            game.ex_cards[cid] = int(observed.get("ex_cards", 0))

        state.discarded = deepcopy(dict(view["discarded"]))
        state.hands = {actor: [card for card in game._deck(actor)
                               if card not in state.discarded[actor]
                               and not (actor == 'm' and card in game.scenario.get(
                                   'special_rules', {}).get('disabled_mastermind_cards', []))]
                       for actor in ACTORS}
        from .belief_dark_constraints import dark_card_domains
        from .belief_matrix import BeliefContradiction
        try:
            _, slots, _ = dark_card_domains(view)
        except BeliefContradiction:
            return None
        master_index = 0
        card_domains = {}
        for index, placement in enumerate(view.get("pending", ())):
            if placement.get("actor") == "m":
                card_domains[index] = slots[str(master_index)]
                master_index += 1
        dark_bundle = DarkCardBelief.sample(
            view.get("pending", ()), state.hands, rng=rng,
            historical_weights=(DarkCardBelief.historical_weights(
                view.get("events", ()), day=state.round, loop=state.loop,
                days=int(view.get("days", 4)))
                if history_prior else None),
            force_history=force_history, card_domains=card_domains,
            historical_cards=(DarkCardBelief.historical_bundle(
                view.get("pending", ()), state.hands, view.get("events", ()),
                day=state.round, loop=state.loop)
                if history_prior and force_history and coherent_history else None))
        if dark_bundle is None:
            return None
        state.pending = [Placement(*item) for item in dark_bundle]
        for actor, card, _ in dark_bundle:
            state.hands[actor].remove(card)
        state.face_up = False
        state.events = deepcopy(list(view.get("events", ())))
        game.known_roles = deepcopy(dict(view.get("known_roles", {})))
        game.known_culprits = {int(day): cid for day, cid in
                               view.get("known_culprits", {}).items()}
        game.known_plots = list(view.get("known_plots", ()))
        game.role_announcements = deepcopy(list(view.get("role_announcements", ())))
        game.protected = bool(view.get("protected", False))
        game.ex_gauge = int(view.get("ex_gauge", 0))
        game.board_ex = deepcopy(dict(view.get("board_ex", game.board_ex)))
        game._movement_locks = deepcopy(dict(view.get("movement_locks", {})))
        game._sealed_boards = [(item["board"], int(item["through"]))
                               for item in view.get("sealed_boards", ())]
        game.public_day_used = set(view.get("ability_day_used", ()))
        game.public_loop_used = set(view.get("ability_loop_used", ()))
        game.day_used = set(game.public_day_used)
        game.loop_used = set(game.public_loop_used)
        game.incident_records = deepcopy(list(view.get("incidents", ())))
        game._loop_initial_locations = {
            cid: str(character.get("initial_location", state.characters[cid].location))
            for cid, character in view["characters"].items()}
        game.winner = view.get("winner")
        # Game construction may open setup/loop-start choices for the sampled
        # script (for example Scholar).  They belong to the sampled world's
        # initial position, not to the observed mid-day root.  Keeping them
        # can later jump a rollout back to day_start with unresolved cards.
        game._queue = []
        game._pending = None
        game._request = None
        game._pending_source = None
        game._decision_actor = None
        game._decision_public_phase = None
        game._return_phase = None
        game._choice_actor_override = None
        game._timing_window = None
        game._trace_observation_stack = []
        return game


class PublicBeliefPlanner(JointCardDecisionProvider):
    """Common fair-information boundary; subclasses supply placement search."""

    def __init__(self, budget: SearchBudget | None = None, *,
                 particle_count: int = 16, rng_seed: int = 0,
                 survival_first: bool = False):
        if type(particle_count) is not int or particle_count < 1:
            raise ValueError("particle_count must be a positive integer")
        self.budget = budget or SearchBudget(node_limit=24, rollout_depth=12)
        self.particle_count = particle_count
        self.rng_seed = rng_seed
        self.survival_first = survival_first
        self.evaluator = ScenarioConditionedEvaluator()
        self.fallback = DefensiveProtagonistAgent(random.Random(rng_seed))
        self.sampler = ConstraintBeliefSampler()
        self.compiler = FsbtxWitnessCompiler()
        self.matcher = FsbtxWitnessMatcher()
        self.evidence_ledger = PublicEvidenceLedger()
        self.determinizer = PublicStateDeterminizer()
        self.belief = PersistentBeliefState(
            max_particles=particle_count, seed=rng_seed)
        self.factorized_belief = FactorizedBeliefState(
            capacity=max(192, particle_count * 8), seed=rng_seed)
        self._observation_viewer: str | None = None
        self._observation_records: tuple[tuple[int, str, CommandObservation | None], ...] = ()
        self._joint_plan: list[dict[str, Any]] = []
        self._joint_plan_position: tuple[int, int] | None = None
        self.last_trace: IsmctsTrace | None = None

    @property
    def controls_protagonist_team(self) -> bool:
        return True

    def remaining_card_commands(self):
        return tuple(deepcopy(command) for command in self._joint_plan)

    def clear_card_plan(self):
        self._joint_plan.clear()
        self._joint_plan_position = None

    def observe(self, *, viewer: str,
                records: Sequence[tuple[int, str, CommandObservation | None]]) -> None:
        """Receive server-owned public observation records for one AI seat."""
        if viewer not in {"a", "b", "c", "team"}:
            raise ValueError("viewer must be a protagonist seat or team")
        if any(observation is not None
               and not isinstance(observation, CommandObservation)
               for _, _, observation in records):
            raise ValueError("records must contain CommandObservation values")
        self._observation_viewer = viewer
        self._observation_records = tuple(
            (int(decision), str(digest),
             observation)
            for decision, digest, observation in records)

    @staticmethod
    def _apply_bundle(particle: Game, commands: Sequence[Mapping[str, Any]]
                      ) -> Game | None:
        world = particle
        for command in commands:
            legal = {_key(action): action
                     for action in world.search_actions(world.controller)}
            selected = legal.get(_key(command))
            if selected is None:
                return None
            world = world.search_transition(selected)
        return world

    def _fallback(self, participant: str, view: dict[str, Any],
                  offers: Sequence[dict[str, Any]], reason: str,
                  witnesses: int = 0) -> dict[str, Any]:
        chosen = self.fallback.choose_action(
            participant=participant, view=view, offers=offers)
        self.last_trace = IsmctsTrace(
            self.plan_name, self.rng_seed, str(view.get("module", "")), 0,
            witnesses, 0, self.budget.rollout_depth, reason, chosen["id"], ())
        return chosen

    def choose_action(self, *, participant: str, view: dict[str, Any],
                      offers: Sequence[dict[str, Any]]) -> dict[str, Any]:
        if not offers:
            raise ValueError("cannot choose from an empty action list")
        if participant == "m":
            raise ValueError("protagonist ISMCTS cannot control the mastermind")
        if (view.get("phase") == "final_guess" and len(offers) == 1
                and str(offers[0].get("type", offers[0].get("kind", "")))
                .removeprefix("core.") == "guess_all"):
            targets = list(view.get("guess_remaining", ()))
            known = view.get("known_roles", {})
            baseline = {
                target: (known.get(target, {}).get("role", "ordinary")
                         if isinstance(known.get(target, {}), dict) else "ordinary")
                for target in targets
            }
            if view.get("module") not in ("FS", "BTX"):
                chosen = {**offers[0], "arguments": {"guesses": baseline}}
                self.last_trace = IsmctsTrace(
                    self.plan_name, self.rng_seed, str(view.get("module", "")),
                    0, 0, 0, self.budget.rollout_depth,
                    "unsupported_module_joint_guess", offers[0]["id"], ())
                return chosen
            evidence = PublicEvidence.from_view(view)
            witnesses = self.evidence_ledger.update(view, self.compiler)
            solved = self.factorized_belief.exact_role_map(
                evidence, witnesses)
            ranked_roles = solved.ranked
            if not ranked_roles:
                chosen = {**offers[0], "arguments": {"guesses": baseline}}
                self.last_trace = IsmctsTrace(
                    self.plan_name, self.rng_seed, evidence.module, 0,
                    len(witnesses), 0, self.budget.rollout_depth,
                    "no_final_guess_particles", offers[0]["id"], ())
                return chosen
            marginals = {cid: Counter() for cid in evidence.characters}
            for world, weight in ranked_roles:
                roles = dict(world.roles)
                for cid in evidence.characters:
                    marginals[cid][roles[cid]] += weight
            belief_roles = tuple({
                "character": cid,
                "counts": dict(sorted(counts.items())),
            } for cid, counts in marginals.items())
            # Rank complete assignments using the same witness weights as
            # sampling. A finite draw can leave every BTX assignment unique;
            # then its empirical mode is just an arbitrary tie-break.
            selected_world, _ = max(
                ranked_roles,
                key=lambda pair: (pair[1], tuple(sorted(pair[0].roles))))
            belief_setups = tuple({
                "main_plot": getattr(world, "main_plot", ""),
                "subplots": list(getattr(world, "subplots", ())),
                "roles": dict(world.roles),
                "weight": weight,
            } for world, weight in sorted(
                ranked_roles,
                key=lambda pair: (pair[1], tuple(sorted(pair[0].roles))),
                reverse=True)[:8])
            roles = dict(selected_world.roles)
            guesses = {target: roles[target]
                       for target in view.get("guess_remaining", ())}
            chosen = {**offers[0], "arguments": {"guesses": guesses}}
            self.last_trace = IsmctsTrace(
                self.plan_name, self.rng_seed, evidence.module, 0,
                len(witnesses), 0, self.budget.rollout_depth,
                "simultaneous_map_guess", offers[0]["id"], (), belief_roles,
                "exact_joint_map", 0, self.evidence_ledger.hard_count,
                self.evidence_ledger.soft_count,
                role_candidates=solved.compatible_count,
                belief_setups=belief_setups)
            return chosen
        if view.get("module") not in ("FS", "BTX"):
            return self._fallback(participant, view, offers, "unsupported_module")
        if view.get("phase") != "protagonists" or not all(
                str(offer.get("type", offer.get("kind", ""))).removeprefix("core.") == "play"
                for offer in offers):
            return self._fallback(participant, view, offers, "unreconstructed_phase")

        return self._fallback(participant, view, offers, "placement_search_not_implemented")
