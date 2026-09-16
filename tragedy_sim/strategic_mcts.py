"""Scenario-aware rollout policy layered on the retained optimized MCTS baseline."""

from __future__ import annotations

import random
from typing import Any

from .cards import COORDS
from .catalog import CHARACTERS
from .optimized_mcts import OptimizedMctsMastermindAgent
from .search import SearchGame


class StrategicMctsMastermindAgent(OptimizedMctsMastermindAgent):
    """Optimized MCTS with a coherent mastermind rollout policy.

    The previous optimized agent deliberately keeps rollouts random.  This
    version is a separate selectable strategy: expansion and mastermind rollout
    actions share scenario-aware route priorities, while protagonist rollout
    actions remain random.  It therefore stays a full-information mastermind
    benchmark without pretending to model protagonist beliefs.
    """

    def __init__(self, *args: Any, rollout_randomness: float = 0.15, **kwargs: Any):
        if not 0 <= rollout_randomness <= 1:
            raise ValueError("rollout_randomness must be in [0, 1]")
        super().__init__(*args, **kwargs)
        self.rollout_randomness = rollout_randomness

    @property
    def plan_name(self) -> str:
        return "strategic_full_information_mcts"

    @staticmethod
    def _destination(location: str, card: str) -> str | None:
        if location not in COORDS or card not in {"h", "v", "d"}:
            return None
        dx, dy = {"h": (1, 0), "v": (0, 1), "d": (1, 1)}[card]
        x, y = COORDS[location]
        target = (x ^ dx, y ^ dy)
        return next((board for board, coords in COORDS.items() if coords == target), None)

    @staticmethod
    def _role_holder(game: SearchGame, role: str) -> str | None:
        return next((cid for cid, assigned in game.roles.items() if assigned == role), None)

    @classmethod
    def _plot_target(cls, game: SearchGame) -> str | None:
        main = game.scenario.get("main_plot")
        if main == "protect":
            return "school"
        if main == "sealed":
            return "shrine"
        if main == "sign":
            return cls._role_holder(game, "key")
        role = "brain" if main == "avenger" else "witch" if main == "bomb" else None
        holder = cls._role_holder(game, role) if role else None
        return CHARACTERS[holder].start if holder in CHARACTERS else None

    @classmethod
    def _movement_priority(cls, game: SearchGame, target: str, card: str) -> float:
        characters = game.state.characters
        moving = characters.get(target)
        if moving is None or not moving.present or not moving.alive:
            return 0.0
        destination = cls._destination(moving.location, card)
        if destination is None or destination in moving.forbidden:
            return -30.0
        score = 0.0
        key_id = cls._role_holder(game, "key")
        killer_id = cls._role_holder(game, "killer")
        if key_id in characters and killer_id in characters:
            key, killer = characters[key_id], characters[killer_id]
            if target == key_id and destination == killer.location:
                score += 110.0
            if target == killer_id and destination == key.location:
                score += 110.0

        serial_id = cls._role_holder(game, "serial")
        if serial_id in characters:
            serial = characters[serial_id]
            victims = {cid for cid, role in game.roles.items()
                       if role in {"key", "friend"}}
            if target in victims and destination == serial.location:
                occupants = [c for c in characters.values()
                             if c.present and c.alive and c.location == serial.location]
                if len(occupants) == 1:
                    score += 100.0
            if moving.location == serial.location and target not in victims | {serial_id}:
                occupants = [c for c in characters.values()
                             if c.present and c.alive and c.location == serial.location]
                if len(occupants) == 3 and any(c.id in victims for c in occupants):
                    score += 85.0

        for incident in game.scenario.get("incidents", ()):
            if incident.get("day", 0) < game.state.round:
                continue
            culprit = characters.get(incident.get("culprit"))
            if culprit is None:
                continue
            if target == key_id and incident.get("kind") == "murder" \
                    and destination == culprit.location:
                score += 65.0
        return score

    def _priority(self, game: SearchGame, action: dict[str, Any]) -> float:
        score = super()._priority(game, action)
        if action.get("action") != "play" or action.get("actor") != "m":
            return score
        card, target = str(action.get("card", "")), action.get("target")
        if not isinstance(target, str):
            return score
        plot_target = self._plot_target(game)
        role = game.roles.get(target)
        if card in {"i1", "i2"}:
            if target == plot_target:
                score += 100.0
            if role == "key":
                score += 80.0
            if role == "killer":
                score += 60.0
            score += 12.0 if card == "i2" else 0.0
        elif card in {"p1a", "p1b"}:
            future = [incident for incident in game.scenario.get("incidents", ())
                      if incident.get("culprit") == target
                      and incident.get("day", 0) >= game.state.round]
            if future:
                nearest = min(incident["day"] for incident in future)
                score += 85.0 / (1 + nearest - game.state.round)
        elif card in {"h", "v", "d"}:
            score += self._movement_priority(game, target, card)
        elif card in {"fp", "fg"} and target in {
                plot_target, self._role_holder(game, "key"),
                self._role_holder(game, "killer")}:
            score += 20.0
        return score

    def _rollout(self, game: SearchGame,
                 rng: random.Random) -> tuple[float, int]:
        world = game
        depth = 0
        while world.winner is None and depth < self.budget.rollout_depth:
            actions = world.search_actions(world.controller)
            self._candidate_actions += len(actions)
            if not actions:
                break
            if len(actions) == 1:
                action = actions[0]
                self._forced_transitions += 1
            elif world.controller == "m" and rng.random() >= self.rollout_randomness:
                priorities = [(self._priority(world, action), action) for action in actions]
                best = max(value for value, _ in priorities)
                action = rng.choice([item for value, item in priorities if value == best])
            else:
                action = rng.choice(actions)
            world = world.search_transition(action)
            depth += 1
        return self.evaluator(world), depth
