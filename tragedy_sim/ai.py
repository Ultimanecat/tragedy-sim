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


class BaselineProtagonistAgent:
    """A low-strength protagonist baseline using public information only.

    It tries to undo a successful mastermind movement on the following day.
    It also reserves Forbid Intrigue for the current leader so two protagonist
    copies cannot accidentally cancel each other.  Other decisions are random.
    """

    MOVEMENT_CARDS = frozenset({"h", "v", "d"})

    def __init__(self, rng: random.Random | random.SystemRandom | None = None):
        self._rng = rng or random.SystemRandom()

    @classmethod
    def _reverse_moves(cls, view: dict[str, Any]) -> list[tuple[str, str]]:
        day, loop = view.get("round"), view.get("loop")
        if type(day) is not int or day <= 1 or type(loop) is not int:
            return []
        events = [event for event in view.get("events", ())
                  if event.get("loop") == loop and event.get("round") == day - 1]
        moved = {event.get("character") for event in events
                 if event.get("kind") == "character_moved"}
        result: list[tuple[str, str]] = []
        for event in events:
            if event.get("kind") != "cards_revealed":
                continue
            for placement in event.get("cards", ()):
                target, card = placement.get("target"), placement.get("card")
                if (placement.get("actor") == "m" and target in moved
                        and card in cls.MOVEMENT_CARDS
                        and (card, target) not in result):
                    result.append((card, target))
        return result

    @staticmethod
    def _play_fields(offer: dict[str, Any]) -> tuple[str | None, str | None]:
        if offer.get("type") != "play":
            return None, None
        parameters = offer.get("parameters", {})
        return parameters.get("card"), parameters.get("target")

    def choose_action(self, *, participant: str, view: dict[str, Any],
                      offers: Sequence[dict[str, Any]]) -> dict[str, Any]:
        if participant == "m":
            raise ValueError("baseline protagonist strategy cannot control seat m")
        if not offers:
            raise ValueError("cannot choose from an empty action list")

        # An uninformed early final guess throws away the remaining loops and
        # was the main cause of the old baseline repeating one loss and then
        # guessing almost at random.  Preserve every remaining information-
        # gathering loop; exhaustion enters final_guess automatically.
        if view.get("phase") == "loop_end":
            continuations = [offer for offer in offers if offer.get("type") == "next"]
            if continuations:
                return self._rng.choice(continuations)

        playable = list(offers)
        leader = view.get("leader")
        without_illegal_convention = [
            offer for offer in playable
            if self._play_fields(offer)[0] != "fi" or offer.get("actor") == leader]
        if without_illegal_convention:
            playable = without_illegal_convention

        reversals = set(self._reverse_moves(view))
        reversing = [offer for offer in playable
                     if self._play_fields(offer) in reversals]
        if reversing:
            return self._rng.choice(reversing)

        forbids = [offer for offer in playable
                   if (self._play_fields(offer)[0] == "fi"
                       and offer.get("actor") == leader)]
        if forbids:
            characters = view.get("characters", {})
            locations = view.get("locations", {})

            def pressure(offer: dict[str, Any]) -> int:
                target = self._play_fields(offer)[1]
                if target in characters:
                    return int(characters[target].get("intrigue", 0))
                return int(locations.get(target, 0))

            highest = max(map(pressure, forbids))
            return self._rng.choice([offer for offer in forbids
                                     if pressure(offer) == highest])
        return self._rng.choice(playable)


class DefensiveProtagonistAgent(BaselineProtagonistAgent):
    """Public-information defense policy for a stronger protagonist baseline."""

    _DEFENSIVE_EFFECTS = {
        "protect": 170, "protection": 170, "reveal": 125,
        "culprit": 135, "revive": 150, "counter": 90,
    }

    @staticmethod
    def _known_role(view: dict[str, Any], target: str) -> str | None:
        known = view.get("known_roles", {}).get(target)
        return known.get("role") if isinstance(known, dict) else None

    @staticmethod
    def _known_culprit_urgency(view: dict[str, Any], target: str) -> int:
        day = int(view.get("round", 1))
        result = 0
        for raw_day, culprit in view.get("known_culprits", {}).items():
            try:
                incident_day = int(raw_day)
            except (TypeError, ValueError):
                continue
            if culprit != target or incident_day < day:
                continue
            result = max(result, 180 if incident_day == day
                         else max(100, 160 - 15 * (incident_day - day)))
        return result

    @classmethod
    def _ability_value(cls, character: dict[str, Any], amount: int) -> int:
        current = int(character.get("goodwill", 0))
        best = 0
        for ability in character.get("abilities", ()):
            threshold = ability.get("threshold")
            if type(threshold) is not int or not current < threshold <= current + amount:
                continue
            value = cls._DEFENSIVE_EFFECTS.get(str(ability.get("kind")), 65)
            if ability.get("counter") == "paranoia" and ability.get("amount", 0) < 0:
                value = max(value, 145)
            best = max(best, value)
        return best

    def _play_score(self, offer: dict[str, Any], view: dict[str, Any],
                    reversals: set[tuple[str, str]]) -> int:
        card, target = self._play_fields(offer)
        if card is None or target is None:
            return 0
        characters = view.get("characters", {})
        character = characters.get(target, {})
        role = self._known_role(view, target)
        score = 0
        if (card, target) in reversals:
            score = max(score, 130)
        if card == "p-1" and target in characters:
            score = max(score, self._known_culprit_urgency(view, target))
            paranoia = int(character.get("paranoia", 0))
            limit = max(1, int(character.get("paranoia_limit", 1)))
            score = max(score, 35 + round(80 * paranoia / limit))
        elif card == "fi" and offer.get("actor") == view.get("leader"):
            intrigue = (int(character.get("intrigue", 0)) if target in characters
                        else int(view.get("locations", {}).get(target, 0)))
            score = max(score, 90 + 20 * intrigue)
            if role in {"key", "friend"}:
                score += 35
        elif card == "fm" and target in characters:
            if role in {"key", "friend"}:
                score = max(score, 125)
            if int(character.get("intrigue", 0)) >= 2:
                score = max(score, 105)
        elif card in {"g1", "g2"} and target in characters:
            amount = 2 if card == "g2" else 1
            score = max(score, self._ability_value(character, amount))
            if role == "time_traveler":
                score = max(score, 190)
        elif card == "p1" and target in characters:
            if self._known_culprit_urgency(view, target):
                score -= 150
            if role in {"key", "friend", "time_traveler"}:
                score -= 70
        return score

    @classmethod
    def _choice_score(cls, offer: dict[str, Any]) -> int:
        if offer.get("type") != "choose":
            return 0
        ui = offer.get("ui", {})
        score = cls._DEFENSIVE_EFFECTS.get(str(ui.get("effect")), 20)
        if (ui.get("counter") == "paranoia"
                and isinstance(ui.get("amount"), int) and ui["amount"] < 0):
            score = max(score, 150)
        return score

    def choose_action(self, *, participant: str, view: dict[str, Any],
                      offers: Sequence[dict[str, Any]]) -> dict[str, Any]:
        if participant == "m":
            raise ValueError("defensive protagonist strategy cannot control seat m")
        if not offers:
            raise ValueError("cannot choose from an empty action list")
        if view.get("phase") == "loop_end":
            continuations = [offer for offer in offers if offer.get("type") == "next"]
            if continuations:
                return self._rng.choice(continuations)
        leader = view.get("leader")
        playable = [offer for offer in offers
                    if (self._play_fields(offer)[0] != "fi"
                        or offer.get("actor") == leader)]
        if not playable:
            playable = list(offers)
        reversals = set(self._reverse_moves(view))
        scored = [(self._play_score(offer, view, reversals)
                   if offer.get("type") == "play" else self._choice_score(offer), offer)
                  for offer in playable]
        best = max(score for score, _ in scored)
        return self._rng.choice([offer for score, offer in scored if score == best])


class RiskAwareProtagonistAgent(DefensiveProtagonistAgent):
    """Defensive policy that infers likely targets from public card history."""

    @staticmethod
    def _public_risk(view: dict[str, Any]) -> dict[str, dict[str, float]]:
        current_loop = int(view.get("loop", 1))
        current_day = int(view.get("round", 1))
        days = max(1, int(view.get("days", 1)))
        risk: dict[str, dict[str, float]] = {}
        for event in view.get("events", ()):
            if event.get("kind") != "cards_revealed":
                continue
            event_loop = int(event.get("loop", current_loop))
            event_day = int(event.get("round", current_day))
            age = max(0, (current_loop - event_loop) * days + current_day - event_day)
            decay = 0.82 ** age
            for placement in event.get("cards", ()):
                if placement.get("actor") != "m":
                    continue
                target, card = placement.get("target"), placement.get("card")
                if not isinstance(target, str):
                    continue
                scores = risk.setdefault(target, {
                    "intrigue": 0.0, "paranoia": 0.0, "movement": 0.0,
                })
                if card == "i2":
                    scores["intrigue"] += 5.0 * decay
                elif card == "i1":
                    scores["intrigue"] += 3.0 * decay
                elif card in {"p1a", "p1b"}:
                    scores["paranoia"] += 2.5 * decay
                elif card in {"h", "v", "d"}:
                    scores["movement"] += 1.5 * decay
        return risk

    def _play_score(self, offer: dict[str, Any], view: dict[str, Any],
                    reversals: set[tuple[str, str]]) -> int:
        score = super()._play_score(offer, view, reversals)
        card, target = self._play_fields(offer)
        if card is None or target is None:
            return score
        risk = self._public_risk(view).get(target, {})
        intrigue = float(risk.get("intrigue", 0.0))
        paranoia = float(risk.get("paranoia", 0.0))
        movement = float(risk.get("movement", 0.0))
        if card == "fi" and offer.get("actor") == view.get("leader"):
            score += round(32 * intrigue)
        elif card == "fm":
            score += round(22 * (movement + 0.5 * intrigue))
        elif card == "p-1":
            character = view.get("characters", {}).get(target, {})
            current_incident = any(item.get("day") == view.get("round")
                                   for item in view.get("schedule", ()))
            if int(character.get("paranoia", 0)) > 0 or current_incident:
                score += round(30 * paranoia)
        elif card == "p1":
            score -= round(20 * paranoia)
        return score


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
