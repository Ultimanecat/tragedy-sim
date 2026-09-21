"""Script-aware protagonist baselines with and without today's card faces.

These intentionally cheat about the *script*.  The blind-card variant must
only obtain the current mastermind cards from a protagonist projection.
Neither variant predicts cards on future days.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import random
from time import perf_counter
from typing import Any, Mapping, Sequence

from .ai import DefensiveProtagonistAgent
from .belief import HiddenWorldHypothesis, PublicEvidence
from .evaluation import ScenarioConditionedEvaluator
from .game import Game
from .ismcts import PublicStateDeterminizer, _command, _key
from .engine import Placement
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

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self), ensure_ascii=False))


class OracleProtagonistAgent:
    """Team planner.  ``reveal_cards`` is the sole information boundary."""

    controls_protagonist_team = True
    uses_public_view = True

    def __init__(self, *, reveal_cards: bool, budget: SearchBudget | None = None,
                 scenario_count: int = 4, rng_seed: int = 0):
        self.reveal_cards = reveal_cards
        self.budget = budget or SearchBudget(node_limit=48, rollout_depth=24)
        self.scenario_count = max(1, scenario_count)
        self.rng_seed = rng_seed
        self.evaluator = ScenarioConditionedEvaluator()
        self.determinizer = PublicStateDeterminizer()
        self.fallback = DefensiveProtagonistAgent(random.Random(rng_seed))
        self._plan: list[dict[str, Any]] = []
        self._position: tuple[int, int] | None = None
        self._loop_plans: dict[tuple[int, int, tuple[str, ...]],
                               tuple[str, ...]] = {}
        self.last_trace: OracleTrace | None = None

    @property
    def plan_name(self) -> str:
        return "oracle_cards" if self.reveal_cards else "oracle_script"

    @staticmethod
    def _offer(action: Mapping[str, Any]) -> dict[str, Any]:
        return {"id": _key(action), "actor": action["actor"],
                "type": action["action"],
                "parameters": {key: value for key, value in action.items()
                               if key not in {"actor", "action"}}}

    @staticmethod
    def _rank(action: Mapping[str, Any], view: Mapping[str, Any],
              scenario: Mapping[str, Any]) -> float:
        card, target = action.get("card"), action.get("target")
        roles = scenario["cast"]
        character = view.get("characters", {}).get(target, {})
        critical = roles.get(target) in {"key", "friend", "time_traveler"}
        incident = any(item["day"] == view["round"]
                       and item["culprit"] == target
                       for item in scenario.get("incidents", ()))
        at_risk = int(character.get("intrigue", 0)) >= 1 or critical
        if card == "fi":
            plot_board = ("school" if scenario["main_plot"] == "protect" else
                          "shrine" if scenario["main_plot"] == "sealed" else None)
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
            return 85 if incident else 24 + 15 * int(character.get("paranoia", 0))
        if card in {"h", "v", "d"}:
            return 72 if critical else 44 if roles.get(target) in {"serial", "killer"} else 18
        if card == "g1":
            return 35 if critical else 12
        if card == "g2":
            return 21 if critical else 4
        if card == "p1":
            return -35 if incident or critical else 0
        return 0

    def _bundle(self, root: Game, view: Mapping[str, Any], index: int
                ) -> tuple[dict[str, Any], ...]:
        world = root
        result: list[dict[str, Any]] = []
        families = ("fi", "fm", "p-1", "h", "v", "d", "g1", "g2", "p1")
        scripted: dict[int, tuple[str, str]] = {}
        plot_board = ("school" if root.scenario["main_plot"] == "protect" else
                      "shrine" if root.scenario["main_plot"] == "sealed" else None)
        cultists = [cid for cid, role in root.scenario["cast"].items()
                    if role == "cultist" and cid in view.get("characters", {})
                    and view["characters"][cid]["location"] == plot_board]
        if 1 <= index <= 9 and plot_board and cultists:
            movement = ("h", "v", "d")[(index - 1) % 3]
            fi_slot = 0 if index <= 3 else 1 if index <= 6 else 2
            move_slot = 1 if fi_slot == 0 else 0
            scripted = {fi_slot: ("fi", plot_board),
                        move_slot: (movement, cultists[0])}
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
            if defenses:
                anchor = defenses[((index - 10) // 2) % len(defenses)]
                scripted = {(index - 10) % 2: anchor}
        for slot in range(3):
            actions = [action for action in world.search_actions(world.controller)
                       if action.get("action") == "play"
                       and (action.get("target") not in view.get("locations", {})
                            or action.get("card") == "fi")
                       and not (action.get("card") == "fi"
                                and any(previous["card"] == "fi"
                                        for previous in result))]
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

    def _day_score(self, world: Game, start_loop: int,
                   start_day: int) -> tuple[float, bool]:
        root_events = len(world.state.events)
        for _ in range(96):
            if world.winner is not None or (world.state.loop, world.state.round) != (start_loop, start_day):
                break
            actions = world.search_actions(world.controller)
            if not actions:
                break
            if world.controller == "m":
                # Mastermind choices are normally deterministic in FS; prefer
                # the choice whose immediate successor is worst for heroes.
                if len(actions) > 1 and all(a["action"] == "choose" for a in actions):
                    selected = max(actions, key=lambda a: self.evaluator(
                        world.search_transition(a)))
                else:
                    selected = actions[0]
            else:
                offers = [self._offer(action) for action in actions]
                chosen = self.fallback.choose_action(
                    participant="team", view=world.protagonist_team_view(),
                    offers=offers)
                selected = actions[next(i for i, offer in enumerate(offers)
                                        if offer["id"] == chosen["id"])]
            world = world.search_transition(selected)
        if (world.winner is None and
                (world.state.loop, world.state.round) == (start_loop, start_day)):
            raise RuntimeError(
                "oracle day rollout stopped before a day boundary: "
                f"phase={world.state.phase} loop={world.state.loop} "
                f"day={world.state.round}")
        failed = (world.winner == "mastermind" or
                  world.state.loop != start_loop or
                  any(event.get("kind") == "loop_lost"
                      for event in world.state.events[root_events:]))
        if failed:
            return -1.0, False
        if world.winner == "protagonists":
            return 1.0, True
        if world.module == "BTX":
            # BTX shares the legal day planner but has different plots and a
            # final guess. Keep the first vertical slice's day-boundary value
            # ruleset-neutral; FS-only board and role pressure below would
            # mis-score BTX positions. Long-horizon information value follows
            # once BTX terminal behavior has a measured baseline.
            value = max(-1.0, min(1.0, -self.evaluator(world)))
            return 0.55 + 0.22 * value, True
        # Survival dominates all position gains.  Stable position helps avoid
        # spending once-per-loop defenses when several safe bundles exist.
        value = max(-1.0, min(1.0, -self.evaluator(world)))
        plot = world.scenario["main_plot"]
        danger_board = "school" if plot == "protect" else (
            "shrine" if plot == "sealed" else None)
        plot_pressure = (world.state.locations[danger_board]
                         if danger_board is not None else 0)
        # A one-day rollout otherwise treats positions with accumulating
        # irreversible pressure as almost equal.  Penalize progress toward
        # known future loss routes before spending scarce one-use defenses.
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
            # A lone key can be paired with a serial killer by a single
            # movement next day.  This was the missed FS01 continuation.
            key_exposure += 0.10 if len(company) == 1 else (
                0.04 if len(company) == 2 else 0.0)
            if any(world.roles.get(c.id) == "killer" for c in company):
                key_exposure += 0.04 + 0.035 * key.intrigue
        incident_pressure = 0.0
        for incident in world.scenario.get("incidents", ()):
            if incident["day"] <= start_day:
                continue
            culprit = world.state.characters.get(incident["culprit"])
            if culprit is not None and culprit.alive:
                incident_pressure += 0.035 * culprit.paranoia / (
                    1 + incident["day"] - start_day)
        return (0.55 + 0.22 * value - 0.15 * plot_pressure
                - 0.06 * killer_pressure - 0.035 * key_pressure
                - key_exposure - incident_pressure), True

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
        if (view.get("module") != "FS" or view.get("phase") != "protagonists"
                or not all(offer.get("type") == "play" for offer in offers)):
            if view.get("phase") == "final_guess":
                guesses = {cid: game.scenario["cast"][cid]
                           for cid in view.get("guess_remaining", ())}
                return {**offers[0], "arguments": {"guesses": guesses}}
            return self.fallback.choose_action(
                participant="team", view=view, offers=offers)

        started = perf_counter()
        public_key = json.dumps(view, sort_keys=True, ensure_ascii=False,
                                default=str)
        rng = random.Random(f"{self.rng_seed}:{self.budget.seed}:"
                            f"{hashlib.sha256(public_key.encode()).hexdigest()}")
        worlds = self._worlds(game, view, rng)
        if not worlds:
            return self.fallback.choose_action(
                participant="team", view=view, offers=offers)
        root = worlds[0]
        candidates = []
        seen = set()
        for index in range(self.budget.node_limit):
            bundle = self._bundle(root, view, index)
            signature = tuple(_key(command) for command in bundle)
            if len(bundle) == 3 and signature not in seen and signature[0] in keyed:
                candidates.append(bundle)
                seen.add(signature)
        if not candidates:
            return self.fallback.choose_action(
                participant="team", view=view, offers=offers)
        evaluations = []
        public_targets = tuple(sorted(str(item.get("target"))
                                      for item in view.get("pending", ())
                                      if item.get("actor") == "m"))
        for bundle in candidates:
            scores = []
            for root_world in worlds:
                world = root_world
                for command in bundle:
                    legal = {_key(action): action
                             for action in world.search_actions(world.controller)}
                    if _key(command) not in legal:
                        world = None
                        break
                    world = world.search_transition(legal[_key(command)])
                if world is not None:
                    scores.append(self._day_score(
                        world, int(view["loop"]), int(view["round"])))
            if scores:
                survival_rate = sum(survived for _, survived in scores) / len(scores)
                mean_score = sum(score for score, _ in scores) / len(scores)
                # Save scarce one-use cards unless they actually improve
                # survival or the resulting board.  This matters across days.
                scarce = sum(command["card"] in {"fm", "g2", "p-1"}
                             for command in bundle)
                mean_score -= 0.025 * scarce
                signature = tuple(_key(command) for command in bundle)
                repetitions = sum(
                    previous == signature
                    for (loop, day, targets), previous in self._loop_plans.items()
                    if loop < position[0] and day == position[1]
                    and targets == public_targets)
                # A failed loop with the same public targets is evidence that
                # repeating an identical entire plan is inadequate.  Keep
                # immediate safety primary: this is smaller than one failed
                # world in the usual sampled set.
                evaluations.append((survival_rate - 0.06 * repetitions,
                                    mean_score - 0.12 * repetitions,
                                    bundle, survival_rate))
        if not evaluations:
            return self.fallback.choose_action(
                participant="team", view=view, offers=offers)
        _, _, best, survival = max(evaluations,
                                   key=lambda item: (item[0], item[1]))
        self._plan = [dict(command) for command in best[1:]]
        self._loop_plans[(position[0], position[1], public_targets)] = tuple(
            _key(command) for command in best)
        self.last_trace = OracleTrace(self.plan_name, len(worlds), len(candidates),
                                      round(survival * len(worlds)),
                                      (perf_counter() - started) * 1000,
                                      tuple(dict(command) for command in best))
        return keyed[_key(best[0])]


class FullCardOracleProtagonistAgent(OracleProtagonistAgent):
    def __init__(self, budget: SearchBudget | None = None, *, rng_seed: int = 0):
        super().__init__(reveal_cards=True, budget=budget, rng_seed=rng_seed)


class HiddenCardOracleProtagonistAgent(OracleProtagonistAgent):
    def __init__(self, budget: SearchBudget | None = None, *,
                 scenario_count: int = 4, rng_seed: int = 0):
        super().__init__(reveal_cards=False, budget=budget,
                         scenario_count=scenario_count, rng_seed=rng_seed)
