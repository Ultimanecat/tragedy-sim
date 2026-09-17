"""Public-information SO-ISMCTS for FS/BTX protagonist decisions.

This first slice searches protagonist card placements, where a public state can
be reconstructed without copying the real game's hidden setup. Other phases
fall back to the deterministic public-information policy.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
import random
from typing import Any, Mapping, Sequence

from .ai import DefensiveProtagonistAgent
from .belief import ConstraintBeliefSampler, PublicEvidence
from .cards import ACTORS
from .engine import Character, Placement, RuleError
from .evaluation import ScenarioConditionedEvaluator
from .game import Game
from .search import SearchBudget
from .witness import FsbtxWitnessCompiler


def _command(offer: Mapping[str, Any]) -> dict[str, Any]:
    kind = str(offer.get("type", offer.get("kind", ""))).removeprefix("core.")
    return {"actor": offer["actor"], "action": kind,
            **deepcopy(dict(offer.get("parameters", {})))}


def _key(command: Mapping[str, Any]) -> str:
    return json.dumps(command, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


@dataclass
class _RootStat:
    visits: int = 0
    availability: int = 0
    value_sum: float = 0.0

    @property
    def mean(self) -> float:
        return self.value_sum / self.visits if self.visits else 0.0


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
                    view: Mapping[str, Any], *, rng: random.Random) -> Game | None:
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
                               if card not in state.discarded[actor]]
                       for actor in ACTORS}
        pending: list[Placement] = []
        for item in view.get("pending", ()):
            actor = str(item["actor"])
            card = item.get("card")
            available = state.hands[actor]
            if card is None:
                if not available:
                    return None
                card = rng.choice(available)
            if card not in available:
                return None
            available.remove(card)
            pending.append(Placement(actor, str(card), str(item["target"])))
        state.pending = pending
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


class IsmctsProtagonistAgent:
    """Root information-set MCTS over independently sampled FS/BTX worlds."""

    def __init__(self, budget: SearchBudget | None = None, *,
                 particle_count: int = 16, rng_seed: int = 0):
        if type(particle_count) is not int or particle_count < 1:
            raise ValueError("particle_count must be a positive integer")
        self.budget = budget or SearchBudget(node_limit=24, rollout_depth=12)
        self.particle_count = particle_count
        self.rng_seed = rng_seed
        self.evaluator = ScenarioConditionedEvaluator()
        self.fallback = DefensiveProtagonistAgent(random.Random(rng_seed))
        self.sampler = ConstraintBeliefSampler()
        self.compiler = FsbtxWitnessCompiler()
        self.determinizer = PublicStateDeterminizer()
        self.last_trace: IsmctsTrace | None = None

    @property
    def plan_name(self) -> str:
        return "public_fs_btx_so_ismcts"

    @staticmethod
    def _reward(game: Game, evaluator: ScenarioConditionedEvaluator) -> float:
        if game.winner == "protagonists":
            return 1.0
        if game.winner == "mastermind":
            return -1.0
        return -float(evaluator(game))

    def _rollout(self, game: Game, rng: random.Random) -> float:
        world = game
        root_loop, root_day = world.state.loop, world.state.round
        event_cursor = len(world.state.events)
        reached_boundary = False
        hard_limit = max(128, self.budget.rollout_depth * 8)
        for depth in range(hard_limit):
            if world.winner is not None:
                break
            actions = list(world.search_actions(world.controller))
            if not actions:
                break
            world = world.search_transition(rng.choice(actions))
            new_events = world.state.events[event_cursor:]
            reached_boundary |= any(
                event.get("loop") == root_loop
                and event.get("round") == root_day
                and event.get("kind") in ("day_ended", "loop_lost")
                for event in new_events)
            # An immediate loss may advance into the next loop in the same
            # transition.  That is the failed day's stable boundary even
            # though the ordinary day_ended event is intentionally skipped.
            reached_boundary |= world.state.loop != root_loop
            event_cursor = len(world.state.events)
            if reached_boundary and depth + 1 >= self.budget.rollout_depth:
                break
        else:
            raise RuntimeError("ISMCTS rollout did not reach a stable day-end boundary")
        if world.winner is None and not reached_boundary:
            raise RuntimeError("ISMCTS rollout stopped before the current day ended")
        return self._reward(world, self.evaluator)

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
            witnesses = self.compiler.compile(view)
            rng = random.Random(
                f"{self.budget.seed}:{self.rng_seed}:{participant}:final_guess")
            hypotheses = self.sampler.sample(
                evidence, max(128, self.particle_count * 4),
                rng=rng, witnesses=witnesses)
            if not hypotheses:
                chosen = {**offers[0], "arguments": {"guesses": baseline}}
                self.last_trace = IsmctsTrace(
                    self.plan_name, self.rng_seed, evidence.module, 0,
                    len(witnesses), 0, self.budget.rollout_depth,
                    "no_final_guess_particles", offers[0]["id"], ())
                return chosen
            marginals = {cid: Counter(dict(world.roles).get(cid)
                                      for world in hypotheses)
                         for cid in evidence.characters}

            def joint_score(world: Any) -> int:
                roles = dict(world.roles)
                return sum(marginals[cid][roles[cid]]
                           for cid in evidence.characters)

            selected_world = max(hypotheses, key=joint_score)
            roles = dict(selected_world.roles)
            guesses = {target: roles[target]
                       for target in view.get("guess_remaining", ())}
            chosen = {**offers[0], "arguments": {"guesses": guesses}}
            self.last_trace = IsmctsTrace(
                self.plan_name, self.rng_seed, evidence.module, len(hypotheses),
                len(witnesses), 0, self.budget.rollout_depth,
                "simultaneous_map_guess", offers[0]["id"], ())
            return chosen
        if view.get("module") not in ("FS", "BTX"):
            return self._fallback(participant, view, offers, "unsupported_module")
        if view.get("phase") != "protagonists" or not all(
                str(offer.get("type", offer.get("kind", ""))).removeprefix("core.") == "play"
                for offer in offers):
            return self._fallback(participant, view, offers, "unreconstructed_phase")

        evidence = PublicEvidence.from_view(view)
        witnesses = self.compiler.compile(view)
        snapshot_hash = hashlib.sha256(json.dumps({
            "module": view.get("module"), "loop": view.get("loop"),
            "round": view.get("round"), "phase": view.get("phase"),
            "characters": view.get("characters"), "locations": view.get("locations"),
            "pending": view.get("pending")}, ensure_ascii=False, sort_keys=True,
            default=str).encode("utf-8")).hexdigest()[:16]
        rng = random.Random(f"{self.budget.seed}:{self.rng_seed}:{participant}:{snapshot_hash}")
        hypotheses = self.sampler.sample(
            evidence, self.particle_count, rng=rng, witnesses=witnesses)
        particles = tuple(particle for hypothesis in hypotheses
                          if (particle := self.determinizer.determinize(
                              hypothesis, evidence, view, rng=rng)) is not None)
        if not particles:
            return self._fallback(participant, view, offers, "no_particles",
                                  len(witnesses))

        offers_by_key = {_key(_command(offer)): offer for offer in offers}
        stats = {key: _RootStat() for key in offers_by_key}
        # A node limit smaller than the root branching factor used to leave
        # most cards completely unexamined.  Treat the configured limit as a
        # minimum and visit every currently legal root action at least once.
        iterations = max(1, self.budget.node_limit, len(offers_by_key))
        for iteration in range(iterations):
            particle = particles[iteration % len(particles)]
            legal = {_key(action): action
                     for action in particle.search_actions(particle.controller)}
            available = [key for key in offers_by_key if key in legal]
            if not available:
                continue
            for key in available:
                stats[key].availability += 1
            unvisited = [key for key in available if stats[key].visits == 0]
            if unvisited:
                selected = rng.choice(unvisited)
            else:
                total = max(1, sum(stats[key].visits for key in available))
                selected = max(
                    available, key=lambda key: stats[key].mean
                    + self.budget.exploration
                    * math.sqrt(math.log(total + 1) / stats[key].visits))
            successor = particle.search_transition(legal[selected])
            reward = self._rollout(successor, rng)
            stats[selected].visits += 1
            stats[selected].value_sum += reward

        viable = [key for key, stat in stats.items() if stat.visits]
        if not viable:
            return self._fallback(participant, view, offers,
                                  "no_common_legal_action", len(witnesses))
        selected = max(viable, key=lambda key: (
            stats[key].visits, stats[key].mean, stats[key].availability))
        chosen = offers_by_key[selected]
        root_actions = tuple({
            "action_id": offers_by_key[key]["id"], "visits": stat.visits,
            "availability": stat.availability, "mean_value": stat.mean,
        } for key, stat in stats.items())
        self.last_trace = IsmctsTrace(
            self.plan_name, self.rng_seed, evidence.module, len(particles),
            len(witnesses), iterations, self.budget.rollout_depth, None,
            chosen["id"], root_actions)
        return chosen
