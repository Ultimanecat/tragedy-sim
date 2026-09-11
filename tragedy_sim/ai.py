"""Pluggable participant policies built on public service contracts."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Protocol, Sequence


class AgentPolicy(Protocol):
    """Choose one server-provided action from a participant's observation."""

    def choose_action(self, *, participant: str, view: dict[str, Any],
                      offers: Sequence[dict[str, Any]]) -> dict[str, Any]: ...


class RandomAgent:
    """Baseline agent that samples uniformly from currently legal actions."""

    def __init__(self, rng: random.Random | random.SystemRandom | None = None):
        self._rng = rng or random.SystemRandom()

    def choose_action(self, *, participant: str, view: dict[str, Any],
                      offers: Sequence[dict[str, Any]]) -> dict[str, Any]:
        del participant, view
        if not offers:
            raise ValueError("cannot choose from an empty action list")
        return self._rng.choice(offers)


@dataclass(frozen=True)
class _Plan:
    kind: str
    target: str | None = None
    culprit: str | None = None
    key: str | None = None
    killer: str | None = None
    incident_day: int | None = None


class FixedStrategyMastermindAgent:
    """A small playbook agent that commits to one applicable winning route.

    This is intentionally not a search agent.  It uses stable action parameters and
    private mastermind observations, then scores legal offers against its chosen plan.
    """

    PLOT_TARGETS = {
        "protect": ("board", "school"), "sealed": ("board", "shrine"),
        "sign": ("role", "key"), "bomb": ("role_board", "witch"),
        "avenger": ("role_board", "brain"), "mz_battle": ("role", "ninja"),
        "mc_dark_school": ("board", "school"), "wm_gospel": ("board", "shrine"),
        "wm_bomb": ("role_board", "witch"),
        "ahr_illusory_world": ("role", "obsessive"),
        "ll_sealed_end": ("board", "shrine"),
        "ll_treacherous_world": ("role", "key"),
        "ll_bomb_z": ("role_board", "witch"),
    }

    def __init__(self, rng: random.Random | random.SystemRandom | None = None,
                 forced_path: str | None = None):
        self._rng = rng or random.SystemRandom()
        self._forced_path = forced_path
        self._plan: _Plan | None = None

    @property
    def plan_name(self) -> str | None:
        return self._plan.kind if self._plan else None

    @staticmethod
    def _role_holder(secret: dict[str, Any], role: str) -> str | None:
        return next((character for character, assigned in secret.get("roles", {}).items()
                     if assigned == role), None)

    def _plans(self, view: dict[str, Any]) -> list[_Plan]:
        secret = view.get("secret", {})
        key = self._role_holder(secret, "key")
        killer = self._role_holder(secret, "killer")
        plans: list[_Plan] = []
        plot = secret.get("main_plot")
        if plot in self.PLOT_TARGETS:
            mode, value = self.PLOT_TARGETS[plot]
            holder = self._role_holder(secret, value) if mode != "board" else None
            target = (value if mode == "board" else holder if mode == "role"
                      else view.get("characters", {}).get(holder or "", {}).get("location"))
            if target:
                plans.append(_Plan("plot_intrigue", target=target, key=key, killer=killer))
        if key and killer:
            plans.append(_Plan("key_assassination", target=key, key=key, killer=killer))
        for incident in secret.get("incidents", []):
            culprit = incident.get("culprit")
            kind = incident.get("kind")
            culprit_role = secret.get("roles", {}).get(culprit)
            threatens_loss = (kind in {"murder", "serial_murder", "frenzied_murder",
                                       "impulsive_murder"}
                              or (kind == "suicide" and culprit_role in {"key", "friend"})
                              or (secret.get("main_plot") == "mc_event_web"))
            if (isinstance(culprit, str) and culprit in view.get("characters", {})
                    and threatens_loss):
                plans.append(_Plan("incident_pressure", culprit=culprit, key=key,
                                   killer=killer, incident_day=incident.get("day")))
        return plans or [_Plan("opportunistic", key=key, killer=killer)]

    def _select_plan(self, view: dict[str, Any]) -> _Plan:
        plans = self._plans(view)
        if self._forced_path:
            matching = [plan for plan in plans if plan.kind == self._forced_path]
            if matching:
                return matching[0]
        return self._rng.choice(plans)

    @staticmethod
    def _move_card(view: dict[str, Any], source: str, destination: str) -> str | None:
        coordinates = {"hospital": (0, 0), "shrine": (1, 0),
                       "city": (0, 1), "school": (1, 1)}
        characters = view.get("characters", {})
        if source not in characters or destination not in characters:
            return None
        origin = coordinates.get(characters[source].get("location"))
        goal = coordinates.get(characters[destination].get("location"))
        if origin is None or goal is None or origin == goal:
            return None
        dx, dy = origin[0] != goal[0], origin[1] != goal[1]
        return "d" if dx and dy else "h" if dx else "v"

    @classmethod
    def _alignment_action(cls, view: dict[str, Any], first: str,
                          second: str) -> tuple[str | None, str | None]:
        characters = view.get("characters", {})
        if first not in characters or second not in characters:
            return None, None
        first_location = characters[first].get("location")
        second_location = characters[second].get("location")
        if first_location == second_location:
            return None, None
        if second_location not in characters[first].get("forbidden", ()):
            return first, cls._move_card(view, first, second)
        if first_location not in characters[second].get("forbidden", ()):
            return second, cls._move_card(view, second, first)
        return None, None

    def _play_score(self, offer: dict[str, Any], view: dict[str, Any]) -> int:
        assert self._plan is not None
        card = offer.get("parameters", {}).get("card")
        target = offer.get("parameters", {}).get("target")
        characters = view.get("characters", {})
        score = 0
        if self._plan.kind == "plot_intrigue" and target == self._plan.target:
            score = {"i2": 120, "i1": 110}.get(card, 0)
        elif self._plan.kind == "key_assassination":
            key, killer = self._plan.key, self._plan.killer
            if target == key and key in characters and characters[key].get("intrigue", 0) < 2:
                score = {"i2": 125, "i1": 115}.get(card, 0)
            mover, move = self._alignment_action(view, killer or "", key or "")
            if target == mover and card == move:
                score = max(score, 105)
        elif self._plan.kind == "incident_pressure":
            culprit = self._plan.culprit
            if culprit in characters and target == culprit:
                current = characters[culprit].get("paranoia", 0)
                limit = characters[culprit].get("paranoia_limit", 99)
                if current < limit:
                    score = {"p1a": 125, "p1b": 124}.get(card, 0)
            if self._plan.key and culprit:
                move = self._move_card(view, self._plan.key, culprit)
                if target == self._plan.key and card == move:
                    score = max(score, 108)
        # Useful cover cards are preferred over counterproductive or random movement.
        if target in {self._plan.target, self._plan.key, self._plan.culprit}:
            score = max(score, {"fg": 45, "fp": 35}.get(card, 0))
        if card in {"fg", "fp", "p-1"}:
            score = max(score, 10)
        return score

    def _choice_score(self, offer: dict[str, Any]) -> int:
        assert self._plan is not None
        ui = offer.get("ui", {})
        target, effect = ui.get("target"), ui.get("effect")
        key = str(ui.get("choice_key", ""))
        if effect in {"kill", "heroes_die", "lose", "finish_loop"}:
            return 150 if target in (None, self._plan.key) else 130
        if self._plan.kind == "plot_intrigue" and target == self._plan.target:
            return 125
        if self._plan.kind == "incident_pressure" and target == self._plan.culprit:
            return 120
        if self._plan.kind == "key_assassination" and (
                key.startswith("killer:") or target == self._plan.key):
            return 140
        return 0

    def choose_action(self, *, participant: str, view: dict[str, Any],
                      offers: Sequence[dict[str, Any]]) -> dict[str, Any]:
        if participant != "m":
            raise ValueError("fixed mastermind strategy can only control seat m")
        if not offers:
            raise ValueError("cannot choose from an empty action list")
        if self._plan is None:
            self._plan = self._select_plan(view)
        scored = []
        for offer in offers:
            if offer.get("type") == "play":
                score = self._play_score(offer, view)
            elif offer.get("type") == "choose":
                score = self._choice_score(offer)
            elif offer.get("type") in {"next", "resolve"}:
                score = 1
            else:
                score = 0
            scored.append((score, offer))
        best = max(score for score, _ in scored)
        candidates = [offer for score, offer in scored if score == best]
        return self._rng.choice(candidates)
