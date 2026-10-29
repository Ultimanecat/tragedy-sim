"""Script-aware protagonist baselines with and without today's card faces.

These intentionally cheat about the *script*.  The blind-card variant must
only obtain the current mastermind cards from a protagonist projection.
Neither variant predicts cards on future days.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import random
from time import perf_counter
from typing import Any, Mapping, Sequence

from .ai import DefensiveProtagonistAgent, FixedStrategyMastermindAgent
from .ai_decisions import JointCardDecisionProvider
from .belief import HiddenWorldHypothesis, PublicEvidence
from .evaluation import ScenarioConditionedEvaluator
from .game import Game
from .belief_planner import PublicStateDeterminizer, _command, _key
from .engine import Placement
from .information_value import InformationOpportunityEvaluator
from .search import SearchBudget


@dataclass(frozen=True)
class OracleTrace:
    strategy: str
    scenarios: int
    candidates: int
    survivals: int
    elapsed_ms: float
    selected_bundle: tuple[dict[str, Any], ...]
    fallback: str | None = None
    rollout_horizon: str = "day"
    max_rollout_steps: int = 0
    terminal_samples: int = 0
    candidate_policy: str = "legacy"
    enumerated_bundles: int = 0
    evaluated_bundles: int = 0
    joint_space_fallback: str | None = None
    ranking_worlds: int = 0
    tactical_projections: int = 0
    policy_rollouts: int = 0
    counterexample_search: dict[str, Any] | None = None
    dark_state_policy: str = "mean"
    candidate_values: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self), ensure_ascii=False))


class OracleProtagonistAgent(JointCardDecisionProvider):
    """Team planner.  ``reveal_cards`` is the sole information boundary."""

    def remaining_card_commands(self):
        return tuple(dict(command) for command in self._plan)

    def clear_card_plan(self):
        self._plan.clear()
        self._position = None

    controls_protagonist_team = True
    uses_public_view = True

    @staticmethod
    def _evaluation_key(row):
        """Both raw survival dimensions precede state shaping/diversity."""
        return row[0], row[2], row[1], row[3]

    ROLLOUT_HORIZONS = frozenset({"day", "loop", "match"})

    def __init__(self, *, reveal_cards: bool, budget: SearchBudget | None = None,
                 scenario_count: int = 4, rng_seed: int = 0,
                 rollout_horizon: str = "day",
                 script_aware_rollout: bool = True,
                 candidate_policy: str = "legacy", skill_information: str = "script",
                 future_incident_policy: str = "legacy", dark_state_policy: str = "mean"):
        if type(dark_state_policy) is not str or dark_state_policy not in {"mean", "worst"}:
            raise ValueError("dark_state_policy must be mean or worst")
        self.dark_state_policy = dark_state_policy
        if type(future_incident_policy) is not str or future_incident_policy not in {"legacy", "impact"}:
            raise ValueError("future_incident_policy must be legacy or impact")
        self.future_incident_policy = future_incident_policy
        if type(skill_information) is not str or skill_information not in {"public", "script"}:
            raise ValueError("skill_information must be public or script")
        self.skill_information = skill_information
        if rollout_horizon not in self.ROLLOUT_HORIZONS:
            raise ValueError("rollout_horizon must be day, loop, or match")
        if type(candidate_policy) is not str or candidate_policy not in {"legacy", "joint_enumeration", "joint_threat", "joint_counterexample"}:
            raise ValueError("invalid oracle candidate_policy")
        self.reveal_cards = reveal_cards
        self.budget = budget or SearchBudget(node_limit=48, rollout_depth=24)
        self.scenario_count = max(1, scenario_count)
        self.rng_seed = rng_seed
        self.rollout_horizon = rollout_horizon
        self.script_aware_rollout = bool(script_aware_rollout)
        self.candidate_policy = candidate_policy
        self.evaluator = ScenarioConditionedEvaluator()
        self.determinizer = PublicStateDeterminizer()
        self.fallback = DefensiveProtagonistAgent(random.Random(rng_seed))
        self._plan: list[dict[str, Any]] = []
        self._position: tuple[int, int] | None = None
        self._loop_plans: dict[tuple[int, int, tuple[str, ...]],
                               tuple[str, ...]] = {}
        self.last_trace: OracleTrace | None = None
        self.skill_evaluations = 0

    @property
    def plan_name(self) -> str:
        return "oracle_cards" if self.reveal_cards else "oracle_script"

    @staticmethod
    def _offer(action: Mapping[str, Any], game: Game | None = None
               ) -> dict[str, Any]:
        offer = {"id": _key(action), "actor": action["actor"],
                 "type": action["action"],
                 "parameters": {key: value for key, value in action.items()
                                if key not in {"actor", "action"}}}
        if game is None or action.get("action") != "choose":
            return offer
        try:
            choice = game.options(str(action["actor"]))[int(action["index"]) - 1]
        except (IndexError, KeyError, TypeError, ValueError):
            return offer
        ui: dict[str, Any] = {}
        for source_field, ui_field in (
                ("key", "choice_key"), ("source", "source"),
                ("ability", "ability"), ("ability_kind", "ability_kind")):
            if isinstance(choice.get(source_field), str):
                ui[ui_field] = choice[source_field]
        for effect in choice.get("effects", ()):
            if not isinstance(effect, Mapping) or not isinstance(effect.get("kind"), str):
                continue
            ui["effect"] = effect["kind"]
            for field in ("target", "counter", "amount", "day", "excluded"):
                if isinstance(effect.get(field), (str, int)):
                    ui[field] = effect[field]
            break
        if ui:
            offer["ui"] = ui
        return offer

    @staticmethod
    def _plot_board(scenario: Mapping[str, Any], view: Mapping[str, Any]
                    ) -> str | None:
        """Return the board whose intrigue directly advances the main plot."""
        main = scenario["main_plot"]
        if main == "protect":
            return "school"
        if main == "sealed":
            return "shrine"
        if main == "bomb":
            witch = next((cid for cid, role in scenario["cast"].items()
                          if role == "witch"), None)
            character = view.get("characters", {}).get(witch, {})
            location = character.get("initial_location",
                                     character.get("location"))
            return (str(location)
                    if location in view.get("locations", {}) else None)
        return None

    @staticmethod
    def _rank(action: Mapping[str, Any], view: Mapping[str, Any],
              scenario: Mapping[str, Any]) -> float:
        card, target = action.get("card"), action.get("target")
        roles = scenario["cast"]
        character = view.get("characters", {}).get(target, {})
        critical = roles.get(target) in {"key", "friend", "time_traveler"}
        incident_distances = [
            int(item["day"]) - int(view["round"])
            for item in scenario.get("incidents", ())
            if item["culprit"] == target and int(item["day"]) >= int(view["round"])
        ]
        incident_distance = min(incident_distances, default=None)
        incident = incident_distance == 0
        at_risk = int(character.get("intrigue", 0)) >= 1 or critical
        if card == "fi":
            plot_board = OracleProtagonistAgent._plot_board(scenario, view)
            if roles.get(target) == "killer":
                # FS killers can end the loop at four intrigue.  Today's
                # public target is enough to prioritize a block even when
                # the mastermind card face remains hidden.
                targeted = any(item.get("actor") == "m"
                               and item.get("target") == target
                               for item in view.get("pending", ()))
                pressure = int(character.get("intrigue", 0))
                return 108 + 12 * pressure if targeted else 48 + 18 * pressure
            return (90 if target == plot_board else 76 if critical else
                    45 if target in view.get("locations", {}) else 12)
        if card == "fm":
            return 87 if critical else 30 if at_risk else 9
        if card == "p-1":
            future_urgency = (0 if incident_distance is None else
                              max(38, 85 - 18 * incident_distance))
            return max(future_urgency,
                       24 + 15 * int(character.get("paranoia", 0)))
        if card in {"h", "v", "d"}:
            return 72 if critical else 44 if roles.get(target) in {"serial", "killer"} else 18
        if card == "g1":
            if roles.get(target) == "time_traveler" and character.get("goodwill", 0) <= 2:
                return 92 if character.get("goodwill", 0) == 2 else 55
            return 35 if critical else 12
        if card == "g2":
            if roles.get(target) == "time_traveler" and character.get("goodwill", 0) <= 1:
                return 96
            return 21 if critical else 4
        if card == "p1":
            return -35 if incident_distance is not None or critical else 0
        return 0

    @staticmethod
    def remaining_placements(view: Mapping[str, Any]) -> int:
        """Count unplayed seats; an existing placement cannot be replaced."""
        order = set(view.get("protagonist_order", ("a", "b", "c")))
        played = {item.get("actor") for item in view.get("pending", ())}
        return len(order - played)

    @staticmethod
    def proposal_index(round_index: int, world_index: int = 0) -> int:
        """Retain the tactical prefix, then advance to new joint proposals."""
        order = (0, 1, 10, 2, 11, 3, 12, 4, 13, 5, 14, 6,
                 15, 7, 16, 8, 17, 9, 18, 19, 20, 21, 22, 23)
        cycle, offset = divmod(round_index + world_index, len(order))
        return order[offset] if cycle == 0 else cycle * len(order) + offset

    def _bundle(self, root: Game, view: Mapping[str, Any], index: int
                ) -> tuple[dict[str, Any], ...]:
        world = root
        result: list[dict[str, Any]] = []
        families = ("fi", "fm", "p-1", "h", "v", "d", "g1", "g2", "p1")
        scripted: dict[int, tuple[str, str]] = {}
        forbid_already_placed = any(item.get("card") == "fi" for item in view.get("pending", ()))
        plot_board = self._plot_board(root.scenario, view)
        cultists = [cid for cid, role in root.scenario["cast"].items()
                    if role == "cultist" and cid in view.get("characters", {})
                    and view["characters"][cid]["location"] == plot_board]
        travelers = [cid for cid, role in root.scenario["cast"].items()
                     if role == "time_traveler"
                     and root.state.characters[cid].goodwill <= 2]
        if root.module == "BTX" and travelers and index <= 4:
            # The optional last-day loss needs goodwill <= 2. Heroes cannot
            # target one character twice on the same day, so plan progress
            # over successive days: +2 from zero, then +1 on a later day.
            traveler = travelers[0]
            gain = "g2" if root.state.characters[traveler].goodwill <= 1 else "g1"
            scripted = {0: (gain, traveler)}
            today = next((incident for incident in root.scenario["incidents"]
                          if incident["day"] == view["round"]), None)
            if index == 0 and today is not None:
                scripted[1] = ("p-1", today["culprit"])
            elif index == 3:
                scripted = {0: ("g1", traveler)}
            elif index == 4:
                scripted = {0: ("g2", traveler)}
        elif (root.module == "BTX" and root.scenario["main_plot"] == "bomb"
              and 1 <= index <= 9 and plot_board):
            fi_slot = (index - 1) // 3
            scripted = {fi_slot: ("fi", plot_board)}
        elif 1 <= index <= 9 and plot_board and cultists:
            movement = ("h", "v", "d")[(index - 1) % 3]
            fi_slot = 0 if index <= 3 else 1 if index <= 6 else 2
            move_slot = 1 if fi_slot == 0 else 0
            scripted = {fi_slot: ("fi", plot_board),
                        move_slot: (movement, cultists[0])}
            today = next((incident for incident in root.scenario["incidents"]
                          if incident["day"] == view["round"]), None)
            if index >= 4 and today is not None:
                # Keep the first three goodwill variants; also propose the
                # conjunction that blocks the plot AND today's incident.
                # A default goodwill filler missed this three-card defense.
                spare_slot = next(slot for slot in range(3) if slot not in scripted)
                scripted[spare_slot] = ("p-1", today["culprit"])
        elif index >= 10:
            # Cover individual tactical defenses systematically before
            # spending the remaining budget on randomized combinations.
            # This list uses the script and public card targets only; it is
            # identical for two worlds with different hidden card faces.
            targets = [item.get("target") for item in view.get("pending", ())
                       if item.get("actor") == "m"]
            roles = root.scenario["cast"]
            key = next((cid for cid, role in roles.items() if role == "key"), None)
            killer = next((cid for cid, role in roles.items() if role == "killer"), None)
            defenses = []
            for target in targets:
                if target in {key, killer, plot_board}:
                    defenses.append(("fi", target))
            if killer:
                defenses.append(("fi", killer))
            if key:
                defenses.extend((card, key) for card in ("fm", "h", "v", "d"))
            for incident in root.scenario.get("incidents", ()):
                if incident["day"] >= view["round"]:
                    defenses.append(("p-1", incident["culprit"]))
            if plot_board:
                defenses.append(("fi", plot_board))
            defenses = list(dict.fromkeys(defenses))
            if defenses and (index < 24 or (index - 24) % 4 != 3):
                anchor = defenses[((index - 10) // 2) % len(defenses)]
                anchor_slot = (index - 10) % (2 if index < 24 else 3)
                scripted = {anchor_slot: anchor}
        for slot in range(3):
            actions = [action for action in world.search_actions(world.controller)
                       if action.get("action") == "play"
                       and (action.get("target") not in view.get("locations", {})
                            or action.get("card") == "fi")
                       and not (action.get("card") == "fi"
                                and (forbid_already_placed or any(previous["card"] == "fi"
                                        for previous in result)))]
            if not actions:
                break
            ranked = sorted(actions, key=lambda action: (
                -self._rank(action, view, root.scenario), _key(action)))
            if slot in scripted:
                card, target = scripted[slot]
                selected = next((action for action in actions
                                 if action["card"] == card and action["target"] == target),
                                None)
                if selected is None:
                    selected = ranked[0]
            elif index >= 24:
                # Later proposals vary BOTH companion cards of an anchored
                # defense. Every fourth proposal is fully exploratory. Draw
                # from all legal targets, keeping paranoia+1 a rare option.
                # Only the sampled script and authorized view guide ranking;
                # hidden card faces never enter this proposal distribution.
                draw = random.Random(f"{self.rng_seed}:{index}:{slot}")
                family = draw.choices(families, weights=(1,) * 8 + (0.05,))[0]
                pool = [action for action in ranked if action["card"] == family] or ranked
                selected = draw.choices(pool, weights=[
                    1 / (1 + offset) for offset in range(len(pool))])[0]
            elif scripted and 1 <= index <= 9:
                selected = next((action for action in ranked
                                 if action["card"] == "g1"), ranked[0])
            elif scripted:
                selected = ranked[0]
            elif index == 0:
                selected = ranked[0]
            else:
                # Independent deterministic draws cover joint combinations.
                # Rotating all slots together missed e.g. fi-school + p-1.
                draw = random.Random(f"{self.rng_seed}:{index}:{slot}")
                family = families[draw.randrange(len(families))]
                matching = [action for action in ranked if action["card"] == family]
                pool = matching or ranked
                selected = pool[draw.randrange(min(4, len(pool)))]
            result.append(dict(selected))
            world = world.search_transition(selected)
            if world.state.phase != "protagonists":
                break
        return tuple(result)

    def _worlds(self, game: Game, view: Mapping[str, Any],
                rng: random.Random) -> tuple[Game, ...]:
        if self.reveal_cards:
            return (game.search_clone(),)
        # Deliberately do not inspect state.pending, hands, or mastermind view.
        evidence = PublicEvidence.from_view(view)
        hypothesis = HiddenWorldHypothesis.from_scenario(game.scenario)
        worlds = []
        for _ in range(self.scenario_count):
            world = self.determinizer.determinize(
                hypothesis, evidence, view, rng=rng, history_prior=True)
            if world is not None:
                if self.script_aware_rollout:
                    # Deliberately script-informed oracle also retains the
                    # current runtime identities (e.g. resolved BTX virus).
                    # No pending faces or private mastermind hand are read.
                    world.roles = dict(game.roles)
                worlds.append(world)
        # Force a few script-relevant but publicly possible dark faces into
        # the comparison. Uniform draws can omit a rare one-use i2 entirely.
        if worlds:
            plot_board = ("school" if game.scenario["main_plot"] == "protect" else
                          "shrine" if game.scenario["main_plot"] == "sealed" else None)
            dangerous = {plot_board} if plot_board else set()
            dangerous.update(cid for cid, role in game.scenario["cast"].items()
                             if role in {"key", "killer"})
            targeted = [item.get("target") for item in view.get("pending", ())
                        if item.get("actor") == "m" and item.get("target") in dangerous]
            for target in dict.fromkeys(targeted):
                faces = ("i2", "i1", "h", "v", "d") if (
                    game.scenario["cast"].get(target) == "key") else ("i2", "i1")
                for face in faces:
                    forced = self._force_dark_card(worlds[0], target, face)
                    if forced is not None:
                        worlds.append(forced)
        return tuple(worlds)

    @staticmethod
    def _force_dark_card(source: Game, target: str, card: str) -> Game | None:
        if card in source.state.discarded["m"]:
            return None
        world = source.search_clone()
        pending = world.state.pending
        index = next((i for i, item in enumerate(pending)
                      if item.actor == "m" and item.target == target), None)
        if index is None:
            return None
        old = pending[index].card
        if old == card:
            return world
        if card in world.state.hands["m"]:
            world.state.hands["m"].remove(card)
            world.state.hands["m"].append(old)
        else:
            other = next((i for i, item in enumerate(pending)
                          if item.actor == "m" and item.card == card), None)
            if other is None:
                return None
            pending[other] = Placement("m", old, pending[other].target)
        pending[index] = Placement("m", card, target)
        return world

    def _rollout_action(self, world: Game,
                        actions: Sequence[Mapping[str, Any]],
                        mastermind: FixedStrategyMastermindAgent
                        ) -> Mapping[str, Any]:
        if world.state.phase == "final_guess":
            return {"actor": world.controller, "action": "guess_all",
                    "guesses": dict(world.scenario["cast"])}
        if world.controller == "m":
            offers = [self._offer(action, world) for action in actions]
            chosen = mastermind.choose_action(
                participant="m", view=world.view("m"), offers=offers)
            return actions[next(i for i, offer in enumerate(offers)
                                if offer["id"] == chosen["id"])]
        if (self.script_aware_rollout
                and world.state.phase == "protagonists"
                and all(action.get("action") == "play" for action in actions)):
            view = world.protagonist_team_view()
            # These two diagnostic agents deliberately know the script.  Their
            # future policy must preserve that premise; falling back to a
            # public-only one-card policy made every continuation miss known
            # future culprits and polluted the root comparison.
            return min(actions, key=lambda action: (
                -self._rank(action, view, world.scenario), _key(action)))
        offers = [self._offer(action, world) for action in actions]
        state_seed = hashlib.sha256(
            f"{self.rng_seed}:{self._policy_state_key(world)}".encode()
        ).hexdigest()
        policy = DefensiveProtagonistAgent(random.Random(state_seed))
        chosen = policy.choose_action(
            participant="team", view=self._skill_view(world, world.protagonist_team_view()),
            offers=self._skill_offers(world, offers))
        return actions[next(i for i, offer in enumerate(offers)
                            if offer["id"] == chosen["id"])]

    def _skill_view(self, world: Game, view: Mapping[str, Any]) -> Mapping[str, Any]:
        """Private oracle context; never published as public knowledge.

        Fair rollout helpers explicitly disable script_aware_rollout and
        retain exactly their authorized observation, including known roles.
        Current dark faces are never copied into this context.
        """
        if not self.script_aware_rollout or self.skill_information == "public":
            return view
        culprits = {}
        for incident in world.scenario["incidents"]:
            cid = self.evaluator.incident_culprit(world, incident["culprit"])
            culprits[str(incident["day"])] = cid
        return {**view, "known_roles": {cid: {"role": role} for cid, role in world.roles.items()},
                "known_culprits": culprits}

    def _skill_offers(self, world: Game, offers):
        """Rank relief targets by one real transition and existing value.

        Only the deliberately informed oracle does this. This reorders a
        continuation policy, not the legal engine or the joint search space.
        Keep ordered values and deterministic ties; no nested day rollouts.
        """
        if (not self.script_aware_rollout or self.skill_information == "public"
                or world.state.phase != "goodwill" or world.module not in {"FS", "BTX"}):
            return offers
        groups = {}
        for offer in offers:
            ui = offer.get("ui", {})
            if (ui.get("effect") == "counter" and ui.get("counter") in {"paranoia", "intrigue"}
                    and isinstance(ui.get("amount"), int) and ui["amount"] < 0):
                groups.setdefault(ui["counter"], []).append(offer)
        excluded = set()
        view = self._skill_view(world, world.protagonist_team_view())
        for group in groups.values():
            if len(group) < 2:
                continue
            scores = []
            for offer in group:
                after = world.search_transition(_command(offer))
                self.skill_evaluations += 1
                successors = [after]
                if after.state.phase == "refusal":
                    # Even an unrefusable/ordinary source first enters the
                    # explicit acceptance window. Apply the forced response;
                    # optional refusals get their pessimistic actual value.
                    responses = after.search_actions(after.controller)
                    successors = [after.search_transition(response) for response in responses]
                    self.skill_evaluations += len(successors)
                scores.append((min(self._cutoff_value(child, world.state.round) for child in successors),
                               self.fallback._choice_score(offer, view), offer))
            best = max(scores, key=lambda x: x[:2])[2]
            excluded.update(o["id"] for o in group if o["id"] != best["id"])
        return [offer for offer in offers if offer["id"] not in excluded]

    @staticmethod
    def _policy_state_key(world: Game) -> str:
        """Canonical private rollout state without difficulty-only metadata.

        Paired Standard/Easy scripts have the same hidden setup.  Total loop
        count may affect explicit long-horizon valuation, but it must not
        silently reshuffle random target choices inside an otherwise identical
        semantic rollout policy.
        """
        projection = dict(world.view("m"))
        projection.pop("events", None)
        for field in ("scenario_id", "title", "loops", "language",
                      "phase_name", "timepoint", "module_name", "labels"):
            projection.pop(field, None)
        return json.dumps(projection, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), default=str)

    @staticmethod
    def _saw_loop_loss(world: Game, event_cursor: int,
                       start_loop: int) -> bool:
        return any(event.get("kind") == "loop_lost"
                   and int(event.get("loop", start_loop)) == start_loop
                   for event in world.state.events[event_cursor:])

    def _horizon_reached(self, world: Game, event_cursor: int,
                         start_loop: int, start_day: int) -> bool:
        if world.winner is not None:
            return True
        if world.state.phase == "final_guess" and self.rollout_horizon != "match":
            # Exhausting the last loop is a failed survival rollout. Stop
            # before the oracle's diagnostic perfect guess can turn it into
            # a fictitious safe day for a fair particle planner.
            return True
        if self.rollout_horizon == "day":
            return (world.state.loop, world.state.round) != (start_loop, start_day)
        if self.rollout_horizon == "loop":
            return (world.state.loop != start_loop
                    or self._saw_loop_loss(world, event_cursor, start_loop))
        return False

    def _cutoff_value(self, world: Game, start_day: int) -> float:
        if world.winner == "protagonists":
            return 1.0
        if world.winner == "mastermind":
            return -1.0
        report = self.evaluator.evaluate(world)
        mastermind_value = report.value
        if self.rollout_horizon == "day":
            # loops_spent is constant across every bundle at this decision.
            # Keeping it inside tanh nevertheless changes relative distances,
            # and makes Standard/Easy choose different day plans in otherwise
            # identical states. Longer horizons still retain match progress.
            raw = sum(item.value for item in report.contributions
                      if item.key != "match:loops_spent")
            mastermind_value = max(-0.92, min(0.92, math.tanh(raw)))
        value = max(-1.0, min(1.0, -mastermind_value))
        if self.rollout_horizon != "day":
            return value
        danger_board = self._plot_board(
            world.scenario, world.protagonist_team_view())
        plot_pressure = (world.state.locations[danger_board]
                         if danger_board is not None else 0)
        killer_pressure = sum(
            c.intrigue for cid, c in world.state.characters.items()
            if c.present and c.alive and world.roles.get(cid) == "killer")
        key_pressure = sum(
            c.intrigue for cid, c in world.state.characters.items()
            if c.present and c.alive and world.roles.get(cid) == "key")
        living = [c for c in world.state.characters.values()
                  if c.present and c.alive]
        key_exposure = 0.0
        for cid, role in world.roles.items():
            if role != "key":
                continue
            key = world.state.characters.get(cid)
            if key is None or not key.alive or not key.present:
                continue
            company = [c for c in living if c.location == key.location]
            key_exposure += 0.10 if len(company) == 1 else (
                0.04 if len(company) == 2 else 0.0)
            if any(world.roles.get(c.id) == "killer" for c in company):
                key_exposure += 0.04 + 0.035 * key.intrigue
        incident_pressure = 0.0
        context = self.evaluator.context_for(world.scenario) if self.future_incident_policy == "impact" else None
        for incident in world.scenario.get("incidents", ()):
            if incident["day"] <= start_day:
                continue
            culprit_id = self.evaluator.incident_culprit(world, incident["culprit"])
            culprit = world.state.characters.get(culprit_id)
            if culprit is not None and culprit.alive and culprit.present:
                weight = (0.2 * self.evaluator.incident_impact(world, context, incident["kind"], culprit.id)
                          if context is not None else 0.035)
                incident_pressure += weight * culprit.paranoia / (
                    1 + incident["day"] - start_day)
        return (0.55 + 0.22 * value - 0.15 * plot_pressure
                - 0.06 * killer_pressure - 0.035 * key_pressure
                - key_exposure - incident_pressure)

    def _cutoff_value_with_events(self, world: Game, start_day: int,
                                  rollout_events: Sequence[dict[str, Any]]) -> float:
        """Override point for models that score the complete public rollout."""
        return self._cutoff_value(world, start_day)

    def _rollout_score(self, world: Game, start_loop: int,
                       start_day: int, *,
                       mastermind_strategy: str | None = None,
                       information_model: InformationOpportunityEvaluator | None = None
                       ) -> tuple[float, bool, int, bool, float, float, float,
                                  float, float]:
        root_events = len(world.state.events)
        rollout_events: list[dict[str, Any]] = []
        multiplier = {"day": 8, "loop": 32, "match": 128}[
            self.rollout_horizon]
        hard_limit = max(128, self.budget.rollout_depth * multiplier)
        seed_material = (
            f"rollout:{self.rng_seed}:{self._policy_state_key(world)}")
        if mastermind_strategy is not None:
            seed_material += f":{mastermind_strategy}"
        policy_seed = hashlib.sha256(seed_material.encode()).hexdigest()
        mastermind = FixedStrategyMastermindAgent(
            random.Random(policy_seed), forced_strategy=mastermind_strategy)
        steps = 0
        for steps in range(1, hard_limit + 1):
            if self._horizon_reached(
                    world, root_events, start_loop, start_day):
                steps -= 1
                break
            actions = world.search_actions(world.controller)
            if not actions:
                break
            previous_event = (world.state.events[-1]
                              if world.state.events else None)
            world = world.search_transition(
                self._rollout_action(world, actions, mastermind))
            # search clones retain one previous event and append this
            # transition's public events.
            inherited = int(previous_event is not None
                            and bool(world.state.events)
                            and world.state.events[0] == previous_event)
            rollout_events.extend(world.state.events[inherited:])
        reached = self._horizon_reached(
            world, root_events, start_loop, start_day)
        if not reached and self.rollout_horizon == "day":
            raise RuntimeError(
                "oracle day rollout stopped before a day boundary: "
                f"phase={world.state.phase} loop={world.state.loop} "
                f"day={world.state.round}")
        # Search transitions compact the event list. The original cursor is
        # no longer valid on the final clone; use our accumulated events.
        loop_lost = (world.state.loop != start_loop or any(
            event.get("kind") == "loop_lost"
            and int(event.get("loop", start_loop)) == start_loop
            for event in rollout_events))
        if self.rollout_horizon != "match" and world.state.phase == "final_guess":
            loop_lost = True
        score = self._cutoff_value_with_events(world, start_day, rollout_events)
        if self.rollout_horizon == "day" and world.module == "BTX" \
                and world.winner is None and not loop_lost \
                and world.state.phase != "final_guess":
            days_left = max(1, world.scenario["days"] - start_day)
            traveler_gap = sum(
                max(0, 3 - world.state.characters[cid].goodwill)
                for cid, role in world.scenario["cast"].items()
                if role == "time_traveler")
            # ``_cutoff_value`` already maps into [0.55, 0.77]; apply only the
            # BTX traveler penalty here so FS and BTX stay on one scale.
            score = score - 0.10 * traveler_gap / days_left
        survived = (world.winner == "protagonists" or
                    world.winner is None and not loop_lost)
        information = 0.0
        information_future = information_realized = information_refusal = 0.0
        threads_carryover_risk = 0.0
        if (information_model is not None and survived
                and world.winner is None and world.state.loop == start_loop):
            breakdown = information_model.evaluate_cutoff(
                world.protagonist_team_view(), rollout_events)
            information = breakdown.total
            information_future = breakdown.future_potential
            information_realized = breakdown.realized_information
            information_refusal = breakdown.refusal_witness
            threads_carryover_risk = breakdown.threads_carryover_risk
        return (score, survived, steps, world.winner is not None, information,
                information_future, information_realized, information_refusal,
                threads_carryover_risk)

    def _day_score(self, world: Game, start_loop: int,
                   start_day: int, *,
                   mastermind_strategy: str | None = None
                   ) -> tuple[float, bool]:
        original = self.rollout_horizon
        self.rollout_horizon = "day"
        try:
            score, survived, *_ = self._rollout_score(
                world, start_loop, start_day,
                mastermind_strategy=mastermind_strategy)
            return score, survived
        finally:
            self.rollout_horizon = original

    @staticmethod
    def _mastermind_strategy_options(world: Game) -> tuple[str, ...]:
        """Applicable private-information policies for one determinized world."""
        return FixedStrategyMastermindAgent().strategy_options(world.view("m"))

    def choose_game_action(self, *, participant: str, game: Game,
                           offers: Sequence[dict[str, Any]],
                           public_view: Mapping[str, Any] | None = None
                           ) -> dict[str, Any]:
        if participant == "m" or not offers:
            raise ValueError("oracle protagonist requires a legal protagonist offer")
        view = (public_view if public_view is not None
                else game.protagonist_team_view())
        position = (int(view["loop"]), int(view["round"]))
        if self._position != position:
            self._plan = []
            self._position = position
        keyed = {_key(_command(offer)): offer for offer in offers}
        if self._plan:
            chosen = keyed.get(_key(self._plan[0]))
            if chosen is not None:
                self._plan.pop(0)
                return chosen
            self._plan = []
        if (view.get("module") not in {"FS", "BTX"}
                or view.get("phase") != "protagonists"
                or not all(offer.get("type") == "play" for offer in offers)):
            if view.get("phase") == "final_guess":
                guesses = {cid: game.scenario["cast"][cid]
                           for cid in view.get("guess_remaining", ())}
                return {**offers[0], "arguments": {"guesses": guesses}}
            return self.fallback.choose_action(
                participant="team", view=self._skill_view(game, view), offers=self._skill_offers(game, offers))

        started = perf_counter()
        deadline = (None if self.budget.time_limit_ms is None else
                    started + self.budget.time_limit_ms / 1000)
        public_key = json.dumps(view, sort_keys=True, ensure_ascii=False,
                                default=str)
        rng = random.Random(f"{self.rng_seed}:{self.budget.seed}:"
                            f"{hashlib.sha256(public_key.encode()).hexdigest()}")
        worlds = self._worlds(game, view, rng)
        if not worlds:
            return self.fallback.choose_action(
                participant="team", view=view, offers=offers)
        root = worlds[0]
        candidates = None
        enumerated = 0
        joint_space_fallback = None
        ranker = None
        counterexample_stats = None
        separation_rollouts = 0
        if self.candidate_policy in {"joint_enumeration", "joint_threat", "joint_counterexample"}:
            from .joint_action_space import JointActionSpace, UnsupportedJointSpace
            try:
                space_view = view
                if self.reveal_cards:
                    # This explicitly cheating mode knows today's faces. The
                    # blind mode must always retain the authorized dark view.
                    faces = {p.target: p.card for p in root.state.pending if p.actor == "m"}
                    space_view = {**view, "pending": [
                        {**p, "card": faces[p["target"]]} if p.get("actor") == "m" else dict(p)
                        for p in view.get("pending", ())]}
                invariant = (root.module == "BTX" and "virus" not in root.scenario["subplots"])
                if invariant:
                    # Both oracles explicitly know the script. A fair caller
                    # needs a proved invariant over its entire support first.
                    space = JointActionSpace(space_view, offers, global_counter_mutation_excluded=True)
                else:
                    space = JointActionSpace(space_view, offers)
                if self.candidate_policy in {"joint_threat", "joint_counterexample"}:
                    from .joint_defense_ranker import JointThreatRanker
                    if not self.reveal_cards:
                        from .dark_attack_scenarios import marginal_dark_worlds, attack_dark_worlds
                        # Script-aware baseline: one known identity setup.
                        # Marginals cover unary faces; joint templates retain
                        # interactions. No true current black faces are read.
                        expanded = (*worlds, *marginal_dark_worlds(root, view), *attack_dark_worlds(root, view))
                        unique = {}
                        for w in expanded:
                            signature = tuple((p.target, p.card) for p in w.state.pending if p.actor == "m")
                            unique.setdefault(signature, w)
                        worlds = tuple(unique.values())
                    ranker = JointThreatRanker(worlds, space, state_policy=self.dark_state_policy)
                candidates, enumerated = space.ranked_bundles(
                    lambda action: self._rank(action, view, root.scenario), self.budget.node_limit,
                    joint_rank=ranker, distinct_effects=ranker is not None)
                if self.candidate_policy == "joint_counterexample" and not self.reveal_cards:
                    from .defense_counterexamples import refine_defense
                    def verify_loss(hypothesis, commands):
                        nonlocal separation_rollouts
                        after = hypothesis
                        for command in commands:
                            after = after.search_transition(command)
                        for route in self._mastermind_strategy_options(hypothesis):
                            separation_rollouts += 1
                            if not self._day_score(after, position[0], position[1], mastermind_strategy=route)[1]:
                                return True
                        return False
                    worlds, candidates, counterexample_stats = refine_defense(
                        root, view, space, worlds, candidates,
                        lambda action: self._rank(action, view, root.scenario), self.budget.node_limit,
                        verify_loss, deadline=deadline, ranker=ranker)
                    enumerated += counterexample_stats["enumerated_bundles"]
            except UnsupportedJointSpace as error:
                joint_space_fallback = str(error)
        if candidates is None:
            candidates = []
            for index in range(self.budget.node_limit):
                bundle = self._bundle(root, view, index)
                candidates.append(bundle)
        # Both proposal paths still use the authoritative first-seat offers.
        proposed = candidates
        candidates = []
        seen = set()
        for bundle in proposed:
            signature = tuple(_key(command) for command in bundle)
            if (len(bundle) == self.remaining_placements(view) and bundle
                    and signature not in seen and signature[0] in keyed):
                candidates.append(bundle)
                seen.add(signature)
        if not candidates:
            return self.fallback.choose_action(
                participant="team", view=view, offers=offers)
        evaluations = []
        policy_rollouts = separation_rollouts
        max_rollout_steps = terminal_samples = 0
        public_targets = tuple(sorted(str(item.get("target"))
                                      for item in view.get("pending", ())
                                      if item.get("actor") == "m"))
        for bundle in candidates:
            if deadline is not None and perf_counter() >= deadline and evaluations:
                break
            scores = []
            day_scores = []
            for root_world in worlds:
                if (deadline is not None and perf_counter() >= deadline
                        and scores and evaluations):
                    scores = []
                    day_scores = []
                    break
                world = root_world
                for command in bundle:
                    legal = {_key(action): action
                             for action in world.search_actions(world.controller)}
                    if _key(command) not in legal:
                        world = None
                        break
                    world = world.search_transition(legal[_key(command)])
                if world is not None:
                    routes = self._mastermind_strategy_options(root_world) if ranker is not None else (None,)
                    outcomes = [self._rollout_score(world, int(view["loop"]), int(view["round"]),
                                                    mastermind_strategy=route) for route in routes]
                    policy_rollouts += len(outcomes)
                    outcome = min(outcomes, key=lambda row: (row[1], row[0]))
                    scores.append(outcome[:2])
                    if self.rollout_horizon != "day":
                        day_scores.append(min((self._day_score(world, int(view["loop"]), int(view["round"]),
                                                               mastermind_strategy=route) for route in routes),
                                              key=lambda row: (row[1], row[0])))
                    max_rollout_steps = max(max_rollout_steps, *(o[2] for o in outcomes))
                    terminal_samples += sum(int(o[3]) for o in outcomes)
            if len(scores) == len(worlds):
                survival_rate = sum(survived for _, survived in scores) / len(scores)
                mean_score = sum(score for score, _ in scores) / len(scores)
                if self.dark_state_policy == "worst":
                    mean_score = min(score for score, _ in scores)
                day_survival = (sum(survived for _, survived in day_scores)
                                / len(day_scores) if day_scores else survival_rate)
                day_mean = (sum(score for score, _ in day_scores) / len(day_scores)
                            if day_scores else mean_score)
                if day_scores and self.dark_state_policy == "worst":
                    day_mean = min(score for score, _ in day_scores)
                # Save scarce one-use cards unless they actually improve
                # survival or the resulting board.  This matters across days.
                scarce = sum(command["card"] in {"fm", "g2", "p-1"}
                             for command in bundle)
                resource_value = -0.025 * scarce
                if self.rollout_horizon == "day":
                    mean_score += resource_value
                    day_mean = mean_score
                    resource_value = 0.0
                signature = tuple(_key(command) for command in bundle)
                repetitions = sum(
                    previous == signature
                    for (loop, day, targets), previous in self._loop_plans.items()
                    if loop < position[0] and day == position[1]
                    and targets == public_targets)
                # Prefer a different equally safe plan after a failed loop.
                # Never subtract shaping from either raw survival dimension:
                # a fixed penalty can outweigh a loss in a larger world batch.
                evaluations.append((survival_rate,
                                    mean_score - 0.12 * repetitions,
                                    day_survival, day_mean + resource_value,
                                    bundle, survival_rate))
        if not evaluations:
            return self.fallback.choose_action(
                participant="team", view=view, offers=offers)
        _, _, _, _, best, survival = max(
            evaluations, key=self._evaluation_key)
        self._plan = [dict(command) for command in best[1:]]
        self._loop_plans[(position[0], position[1], public_targets)] = tuple(
            _key(command) for command in best)
        self.last_trace = OracleTrace(self.plan_name, len(worlds), len(candidates),
                                      round(survival * len(worlds)),
                                      (perf_counter() - started) * 1000,
                                      tuple(dict(command) for command in best),
                                      rollout_horizon=self.rollout_horizon,
                                      max_rollout_steps=max_rollout_steps,
                                      terminal_samples=terminal_samples,
                                      candidate_policy=self.candidate_policy,
                                      enumerated_bundles=enumerated,
                                      evaluated_bundles=len(evaluations),
                                      joint_space_fallback=joint_space_fallback,
                                      ranking_worlds=len(worlds) if ranker is not None else 0,
                                      tactical_projections=ranker.projections if ranker is not None else 0,
                                      policy_rollouts=policy_rollouts,
                                      counterexample_search=counterexample_stats, dark_state_policy=self.dark_state_policy,
                                      candidate_values=tuple({
                                          "bundle": tuple(dict(command) for command in row[4]),
                                          "survival_rate": row[0], "day_survival_rate": row[2],
                                          "state_value": row[1], "day_state_value": row[3],
                                          "selection_key": self._evaluation_key(row),
                                          "selected": row[4] == best,
                                      } for row in evaluations))
        return keyed[_key(best[0])]


class FullCardOracleProtagonistAgent(OracleProtagonistAgent):
    def __init__(self, budget: SearchBudget | None = None, *, rng_seed: int = 0,
                 rollout_horizon: str = "day", candidate_policy: str = "legacy", skill_information: str = "script",
                 future_incident_policy: str = "legacy", dark_state_policy: str = "mean"):
        super().__init__(reveal_cards=True, budget=budget, rng_seed=rng_seed,
                         rollout_horizon=rollout_horizon, candidate_policy=candidate_policy, skill_information=skill_information,
                         future_incident_policy=future_incident_policy, dark_state_policy=dark_state_policy)


class HiddenCardOracleProtagonistAgent(OracleProtagonistAgent):
    def __init__(self, budget: SearchBudget | None = None, *,
                 scenario_count: int = 4, rng_seed: int = 0,
                 rollout_horizon: str = "day", candidate_policy: str = "legacy", skill_information: str = "script",
                 future_incident_policy: str = "legacy", dark_state_policy: str = "mean"):
        super().__init__(reveal_cards=False, budget=budget,
                         scenario_count=scenario_count, rng_seed=rng_seed,
                         rollout_horizon=rollout_horizon, candidate_policy=candidate_policy, skill_information=skill_information,
                         future_incident_policy=future_incident_policy, dark_state_policy=dark_state_policy)
