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
import random
from time import perf_counter
from typing import Any, Mapping, Sequence

from .ai import DefensiveProtagonistAgent, RiskAwareProtagonistAgent
from .belief import (CommandObservation, ConstraintBeliefSampler,
                     DarkCardBelief, FactorizedBeliefState,
                     PersistentBeliefState, PublicEvidence)
from .cards import ACTORS, COORDS, MOVES
from .engine import Character, Placement, RuleError
from .evaluation import ScenarioConditionedEvaluator
from .game import Game
from .search import SearchBudget
from .witness import (FsbtxWitnessCompiler, FsbtxWitnessMatcher,
                      PublicEvidenceLedger)


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
    survivals: int = 0

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
                    force_history: bool = False) -> Game | None:
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
        dark_bundle = DarkCardBelief.sample(
            view.get("pending", ()), state.hands, rng=rng,
            historical_weights=(DarkCardBelief.historical_weights(
                view.get("events", ()), day=state.round, loop=state.loop,
                days=int(view.get("days", 4)))
                if history_prior else None),
            force_history=force_history)
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


class IsmctsProtagonistAgent:
    """Root information-set MCTS over independently sampled FS/BTX worlds."""

    def __init__(self, budget: SearchBudget | None = None, *,
                 particle_count: int = 16, rng_seed: int = 0,
                 legacy_joint_search: bool = False,
                 survival_first: bool = False):
        if type(particle_count) is not int or particle_count < 1:
            raise ValueError("particle_count must be a positive integer")
        self.budget = budget or SearchBudget(node_limit=24, rollout_depth=12)
        self.particle_count = particle_count
        self.rng_seed = rng_seed
        self.legacy_joint_search = legacy_joint_search
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
    def plan_name(self) -> str:
        if self.legacy_joint_search:
            return "public_fs_btx_team_so_ismcts_legacy"
        if self.survival_first:
            return "public_fs_btx_team_survival_ismcts"
        return "public_fs_btx_team_so_ismcts"

    @property
    def controls_protagonist_team(self) -> bool:
        return True

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
            coordinated = (world.controller != "m"
                           and world.state.phase == "protagonists"
                           and all(action.get("action") == "play"
                                   for action in actions))
            if not coordinated:
                selected = rng.choice(actions)
            else:
                offers = [{
                    "id": _key(action), "actor": action["actor"],
                    "type": action["action"],
                    "parameters": {key: value for key, value in action.items()
                                   if key not in {"actor", "action"}},
                } for action in actions]
                chosen = DefensiveProtagonistAgent(rng).choose_action(
                    participant="team",
                    view=world.protagonist_team_view(), offers=offers)
                selected = actions[next(
                    index for index, offer in enumerate(offers)
                    if offer["id"] == chosen["id"])]
            world = world.search_transition(selected)
            new_events = world.state.events[event_cursor:]
            reached_boundary |= any(
                event.get("loop") == root_loop
                and event.get("round") == root_day
                and event.get("kind") in ("day_ended", "loop_lost")
                for event in new_events)
            # An immediate loss may advance into the next loop in the same
            # transition.  That is the failed day's stable boundary even
            # though the ordinary day_ended event is intentionally skipped.
            reached_boundary |= (world.state.loop != root_loop
                                 or world.state.round != root_day)
            event_cursor = len(world.state.events)
            if reached_boundary and (self.survival_first
                                     or depth + 1 >= self.budget.rollout_depth):
                break
        else:
            raise RuntimeError(
                "ISMCTS rollout did not reach a stable day-end boundary: "
                f"phase={world.state.phase} loop={world.state.loop} "
                f"day={world.state.round} controller={world.controller}")
        if world.winner is None and not reached_boundary:
            raise RuntimeError("ISMCTS rollout stopped before the current day ended")
        if world.winner is None and world.state.loop != root_loop:
            # Losing the current loop is an observed game setback, not an
            # information bonus.  A reset erases the dead board position, so
            # the ordinary state evaluator cannot recover this signal after
            # the transition into the next loop.
            return -1.0 if self.survival_first else -0.90
        reward = self._reward(world, self.evaluator)
        if self.survival_first and world.winner is None:
            # Day survival dominates the soft position estimate. Later days
            # are deliberately not simulated in this selectable mode.
            return 0.5 + 0.1 * reward
        return reward

    @staticmethod
    def _card_family(action: Mapping[str, Any]) -> str:
        card = action.get("card")
        return "movement" if card in {"h", "v", "d"} else str(card)

    @staticmethod
    def _tactical_rank(action: Mapping[str, Any], particle: Game,
                       view: Mapping[str, Any]) -> int:
        """Prioritize several distinct ways to keep a sampled key safe."""
        target, card = action.get("target"), action.get("card")
        characters = particle.state.characters
        threatened = {item.get("target") for item in view.get("pending", ())
                      if item.get("actor") == "m"}
        critical = {cid for cid, role in particle.roles.items()
                    if role in {"key", "friend"} and cid in characters
                    and characters[cid].alive}
        serial_locations = {characters[cid].location
                            for cid, role in particle.roles.items()
                            if role == "serial" and cid in characters
                            and characters[cid].alive}
        if card == "fm" and target in critical:
            return 120 if target in threatened else 75
        if card not in MOVES or target not in characters:
            return 0
        character = characters[target]
        dx, dy = MOVES[{"h": "horizontal", "v": "vertical",
                        "d": "diagonal"}[card]]
        x, y = COORDS[character.location]
        destination = next(board for board, point in COORDS.items()
                           if point == (x ^ dx, y ^ dy))
        if destination in character.forbidden:
            return 0
        if target in critical and target in threatened:
            return 110 if destination not in serial_locations else 40
        if (target not in critical and destination in serial_locations
                and any(cid in threatened for cid in critical)):
            return 85
        return 0

    def _candidate_bundle(self, particle: Game, view: Mapping[str, Any],
                          index: int, rng: random.Random
                          ) -> tuple[dict[str, Any], ...]:
        """Generate all three placements; no slot is delegated to a policy."""
        world = particle
        commands: list[dict[str, Any]] = []
        policy = RiskAwareProtagonistAgent(rng)
        families = ("fm", "fi", "movement", "p-1", "g2", "g1",
                    "p1", "other")
        reversals = policy._reverse_moves(dict(view))
        for slot in range(3):
            actions = [action for action in world.search_actions(world.controller)
                       if action.get("action") == "play"]
            if not actions:
                break
            ranked = sorted(actions, key=lambda action: (
                0 if not self.survival_first else
                (int(action["card"] == "p1") * 100
                 + int(action["card"] == "fi"
                       and action["target"] in view.get("locations", {})
                       and not any(item.get("actor") == "m"
                                   and item.get("target") == action["target"]
                                   for item in view.get("pending", ()))) * 80
                 + int(action["card"] == "g2") * 25),
                -policy._play_score({
                    "actor": action["actor"], "type": "play",
                    "parameters": {"card": action["card"],
                                   "target": action["target"]},
                }, dict(view), reversals), _key(action)))
            # A small prior supplies one strong candidate. Other candidates
            # rotate card families independently for every slot; in
            # particular, later slots are not fixed to goodwill cards.
            tactical = []
            if self.survival_first and index > 0 and slot == ((index - 1) // 8) % 3:
                tactical = sorted(
                    (action for action in actions
                     if self._tactical_rank(action, particle, view) > 0),
                    key=lambda action: (-self._tactical_rank(action, particle, view),
                                        _key(action)))
            if tactical:
                selected = tactical[((index - 1) % 8) % len(tactical)]
            elif index == 0:
                selected = ranked[0]
            else:
                family = families[(index - 1 + slot * 3) % len(families)]
                matching = [action for action in ranked
                            if self._card_family(action) == family]
                if not matching and family == "other":
                    matching = ranked
                options = matching or ranked
                selected = options[(index // len(families)) % min(3, len(options))]
            commands.append(dict(selected))
            world = world.search_transition(selected)
            if world.state.phase != "protagonists":
                break
        return tuple(commands)

    def _legacy_bundle(self, particle: Game, first: dict[str, Any],
                       rng: random.Random
                       ) -> tuple[tuple[dict[str, Any], ...], Game]:
        commands = []
        world = particle
        selected = first
        for _ in range(3):
            commands.append(dict(selected))
            world = world.search_transition(selected)
            if world.state.phase != "protagonists":
                break
            actions = [action for action in world.search_actions(world.controller)
                       if action.get("action") == "play"]
            if not actions:
                break
            offers = [{
                "id": _key(action), "actor": action["actor"],
                "type": action["action"],
                "parameters": {key: value for key, value in action.items()
                               if key not in {"actor", "action"}},
            } for action in actions]
            chosen = DefensiveProtagonistAgent(rng).choose_action(
                participant="team", view=world.protagonist_team_view(),
                offers=offers)
            selected = actions[next(index for index, offer in enumerate(offers)
                                    if offer["id"] == chosen["id"])]
        return tuple(commands), world

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
            ranked_roles = self.factorized_belief.role_posterior(
                evidence, witnesses)
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
                self.plan_name, self.rng_seed, evidence.module, len(ranked_roles),
                len(witnesses), 0, self.budget.rollout_depth,
                "simultaneous_map_guess", offers[0]["id"], (), belief_roles,
                "candidate_weights", 0, self.evidence_ledger.hard_count,
                self.evidence_ledger.soft_count,
                belief_setups=belief_setups)
            return chosen
        if view.get("module") not in ("FS", "BTX"):
            return self._fallback(participant, view, offers, "unsupported_module")
        if view.get("phase") != "protagonists" or not all(
                str(offer.get("type", offer.get("kind", ""))).removeprefix("core.") == "play"
                for offer in offers):
            return self._fallback(participant, view, offers, "unreconstructed_phase")

        evidence_started = perf_counter()
        evidence = PublicEvidence.from_view(view)
        witnesses = self.evidence_ledger.update(view, self.compiler)
        position = (int(view.get("loop", 0)), int(view.get("round", 0)))
        offers_by_key = {_key(_command(offer)): offer for offer in offers}
        if self._joint_plan_position != position:
            self._joint_plan = []
            self._joint_plan_position = None
        if self._joint_plan:
            planned = self._joint_plan[0]
            chosen = offers_by_key.get(_key(planned))
            if chosen is not None:
                self._joint_plan.pop(0)
                self.last_trace = IsmctsTrace(
                    self.plan_name, self.rng_seed, evidence.module, 0,
                    len(witnesses), 0, self.budget.rollout_depth,
                    "joint_plan_followup", chosen["id"], (), (),
                    "persistent", 0, self.evidence_ledger.hard_count,
                    self.evidence_ledger.soft_count,
                    (perf_counter() - evidence_started) * 1000, 0.0,
                    tuple(self._joint_plan))
                return chosen
            self._joint_plan = []
            self._joint_plan_position = None
        snapshot_hash = hashlib.sha256(json.dumps({
            "module": view.get("module"), "loop": view.get("loop"),
            "round": view.get("round"), "phase": view.get("phase"),
            "characters": view.get("characters"), "locations": view.get("locations"),
            "pending": view.get("pending")}, ensure_ascii=False, sort_keys=True,
            default=str).encode("utf-8")).hexdigest()[:16]
        rng = random.Random(f"{self.budget.seed}:{self.rng_seed}:{participant}:{snapshot_hash}")
        belief_source = "resampled"
        observation_updates = 0
        belief_failure = None
        factored = None
        particles: tuple[Game, ...] = ()
        if not self.legacy_joint_search:
            factored = self.factorized_belief.sample(
                evidence, witnesses, self.particle_count, rng=rng)
            particles = tuple(particle for index, hypothesis in enumerate(factored.worlds)
                              if (particle := self.determinizer.determinize(
                                  hypothesis, evidence, view, rng=rng,
                                  history_prior=self.survival_first,
                                  force_history=(self.survival_first
                                                 and index % 5 == 0))) is not None)
            belief_source = "factorized"
            belief_failure = factored.reason
            observation_updates = self.evidence_ledger.updates
        elif (self._observation_viewer == participant
                and self._observation_records):
            revealed = {
                (int(event["loop"]), int(event["round"])):
                tuple(event.get("cards", ()))
                for event in view.get("events", ())
                if event.get("kind") == "cards_revealed"
            }
            incident_outcomes = {
                (int(event["loop"]), int(event["round"])):
                bool(event["happened"])
                for event in view.get("events", ())
                if event.get("kind") == "incident_status"
            }
            synced = self.belief.sync(
                evidence, viewer=participant,
                observations=self._observation_records,
                witnesses=witnesses, sampler=self.sampler,
                revealed_placements=revealed,
                incident_outcomes=incident_outcomes)
            particles = tuple(synced.particles)
            observation_updates = synced.processed
            if particles:
                belief_source = "persistent"
            else:
                belief_failure = synced.reason
        if not particles and self.legacy_joint_search:
            hypotheses = self.sampler.sample(
                evidence, self.particle_count, rng=rng, witnesses=witnesses)
            particles = tuple(particle for hypothesis in hypotheses
                              if (particle := self.determinizer.determinize(
                                  hypothesis, evidence, view, rng=rng)) is not None)
        if not particles:
            return self._fallback(participant, view, offers, "no_particles",
                                  len(witnesses))
        marginals = {cid: Counter(particle.roles.get(cid)
                                  for particle in particles)
                     for cid in evidence.characters}
        belief_roles = tuple({
            "character": cid,
            "counts": dict(sorted(counts.items())),
        } for cid, counts in marginals.items())
        evidence_elapsed_ms = (perf_counter() - evidence_started) * 1000
        search_started = perf_counter()
        deadline = (None if self.budget.time_limit_ms is None else
                    evidence_started + self.budget.time_limit_ms / 1000)

        iterations = max(1, self.budget.node_limit)
        completed_iterations = 0
        bundle_commands: dict[str, tuple[dict[str, Any], ...]] = {}
        bundle_stats: dict[str, _RootStat] = {}
        if self.legacy_joint_search:
            first_keys = list(offers_by_key)
            rng.shuffle(first_keys)
            for iteration in range(iterations):
                if deadline is not None and perf_counter() >= deadline and bundle_stats:
                    break
                particle = particles[iteration % len(particles)]
                legal = {_key(action): action
                         for action in particle.search_actions(particle.controller)}
                available = [key for key in first_keys if key in legal]
                if not available:
                    continue
                first = legal[available[iteration % len(available)]]
                commands, successor = self._legacy_bundle(particle, first, rng)
                key = _key(commands)
                bundle_commands[key] = commands
                stat = bundle_stats.setdefault(key, _RootStat())
                stat.availability += 1
                stat.visits += 1
                value = self._rollout(successor, rng)
                stat.value_sum += value
                stat.survivals += value > 0
                completed_iterations += 1
        else:
            # Larger budgets widen the bounded pool only after preserving
            # several visits per complete bundle.
            candidate_limit = min(iterations, max(1, min(24, iterations // 8)))
            attempts = 0
            while (len(bundle_commands) < candidate_limit
                   and attempts < candidate_limit * 4):
                if deadline is not None and perf_counter() >= deadline and bundle_commands:
                    break
                commands = self._candidate_bundle(
                    particles[attempts % len(particles)], view, attempts, rng)
                attempts += 1
                if not commands or _key(commands[0]) not in offers_by_key:
                    continue
                bundle_commands.setdefault(_key(commands), commands)
            bundle_stats = {key: _RootStat() for key in bundle_commands}
            keys = tuple(bundle_commands)
            # Round-robin candidates over a shared particle batch.
            for iteration in range(iterations):
                if not keys:
                    break
                if deadline is not None and perf_counter() >= deadline and completed_iterations:
                    break
                key = keys[iteration % len(keys)]
                batch = iteration // len(keys)
                batches = (iterations + len(keys) - 1) // len(keys)
                particle = particles[(batch * len(particles)) // batches]
                successor = self._apply_bundle(particle, bundle_commands[key])
                if successor is None:
                    continue
                stat = bundle_stats[key]
                stat.availability += 1
                stat.visits += 1
                value = self._rollout(successor, rng)
                stat.value_sum += value
                stat.survivals += value > 0
                completed_iterations += 1

        viable = [key for key, stat in bundle_stats.items() if stat.visits]
        if not viable:
            return self._fallback(participant, view, offers,
                                  "no_common_legal_action", len(witnesses))
        if self.survival_first:
            selected = max(viable, key=lambda key: (
                bundle_stats[key].survivals / bundle_stats[key].visits,
                bundle_stats[key].mean - 0.02 * sum(
                    command.get("card") == "g2"
                    for command in bundle_commands[key]),
                bundle_stats[key].visits, bundle_stats[key].availability))
        else:
            selected = max(viable, key=lambda key: (
                bundle_stats[key].mean, bundle_stats[key].visits,
                bundle_stats[key].availability))
        selected_commands = bundle_commands[selected]
        chosen = offers_by_key[_key(selected_commands[0])]
        self._joint_plan = [dict(command)
                            for command in selected_commands[1:]]
        self._joint_plan_position = position if self._joint_plan else None
        root_actions = tuple({
            "bundle": [dict(command) for command in bundle_commands[key]],
            "visits": stat.visits, "availability": stat.availability,
            "mean_value": stat.mean, "day_survivals": stat.survivals,
        } for key, stat in bundle_stats.items())
        self.last_trace = IsmctsTrace(
            self.plan_name, self.rng_seed, evidence.module, len(particles),
            len(witnesses), completed_iterations, self.budget.rollout_depth, None,
            chosen["id"], root_actions, belief_roles, belief_source,
            observation_updates, self.evidence_ledger.hard_count,
            self.evidence_ledger.soft_count, evidence_elapsed_ms,
            (perf_counter() - search_started) * 1000,
            tuple(self._joint_plan), belief_failure,
            factored.role_candidates if factored is not None else 0,
            factored.culprit_options if factored is not None else ())
        return chosen


class LegacyIsmctsProtagonistAgent(IsmctsProtagonistAgent):
    """Selectable first-generation joint search baseline."""

    def __init__(self, budget: SearchBudget | None = None, *,
                 particle_count: int = 16, rng_seed: int = 0):
        super().__init__(budget, particle_count=particle_count,
                         rng_seed=rng_seed, legacy_joint_search=True)


class SurvivalIsmctsProtagonistAgent(IsmctsProtagonistAgent):
    """Selectable one-day, survival-first search with a public card prior."""

    def __init__(self, budget: SearchBudget | None = None, *,
                 particle_count: int = 16, rng_seed: int = 0):
        super().__init__(budget, particle_count=particle_count,
                         rng_seed=rng_seed, survival_first=True)
