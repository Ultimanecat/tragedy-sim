"""Bounded two-day plan search on top of state-returning day transitions.

Known-world diagnostic only. Black and red card placements are explicit; the
second day uses a caller fallback policy. This is the first search layer above
``advance_day_with_plans`` and ``advance_two_days``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from ..game import Game
from .transition import TwoDayTransitionResult, advance_to_day_boundary, advance_two_days


Command = dict[str, Any]
Plan = tuple[Command, ...]


# Card count per day is a rule constant in FS/BTX; the bound and candidate caps
# are search budgets. They are named here and echoed in the result metadata.
DEFAULT_PLAN_LENGTH = 3
MAX_ADVANCE_STEPS = 64
DEFAULT_BLACK_PLAN_LIMIT = 4
DEFAULT_RED_PLAN_LIMIT = 4


@dataclass(frozen=True)
class TwoDaySearchResult:
    value: float
    red_plan: Plan
    black_plan: Plan
    red_plans: int
    black_plans: int
    evaluations: int
    terminal: str
    search: str = "known-world-bounded-two-day"
    plan_length: int = DEFAULT_PLAN_LENGTH
    day2_policy: str = "first_legal_baseline"


def _advance_to_mastermind(world: Game) -> Game | None:
    current = world
    seen = 0
    while current.winner is None and current.state.phase != "mastermind":
        if seen >= MAX_ADVANCE_STEPS:
            return None
        actions = current.legal_actions(current.controller)
        if not actions:
            return None
        action = next((item for item in actions
                       if item.get("action") == "next"), actions[0])
        current = current.transition(action).game
        seen += 1
    return current if current.winner is None else None


def _play_plans(world: Game, limit: int,
                plan_length: int = DEFAULT_PLAN_LENGTH) -> tuple[Plan, ...]:
    plans: list[Plan] = []

    def visit(current: Game, prefix: tuple[Command, ...]):
        if len(plans) >= limit:
            return
        if len(prefix) >= plan_length:
            plans.append(prefix)
            return
        if current.winner is not None:
            return
        actions = [item for item in current.legal_actions(current.controller)
                   if item.get("action") == "play"]
        for action in actions[:limit]:
            visit(current.transition(action).game, (*prefix, dict(action)))
            if len(plans) >= limit:
                return

    visit(world, ())
    return tuple(plans)


def black_day_plans(world: Game, *, limit: int = DEFAULT_BLACK_PLAN_LIMIT,
                    plan_length: int = DEFAULT_PLAN_LENGTH) -> tuple[Plan, ...]:
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer")
    mastermind = _advance_to_mastermind(world)
    if mastermind is None:
        return ()
    return _play_plans(mastermind, limit, plan_length)


def red_day_plans(world: Game, black_plan: Sequence[Mapping[str, Any]], *,
                  limit: int = DEFAULT_RED_PLAN_LIMIT,
                  plan_length: int = DEFAULT_PLAN_LENGTH) -> tuple[Plan, ...]:
    current = _advance_to_mastermind(world)
    if current is None:
        return ()
    for command in black_plan:
        current = current.transition(dict(command)).game
        if current.winner is not None:
            return ()
    if current.state.phase != "protagonists":
        return ()
    return _play_plans(current, limit, plan_length)


def evaluate_day1_pair(world: Game, black_plan: Sequence[Mapping[str, Any]],
                       red_plan: Sequence[Mapping[str, Any]], *,
                       leaf_value: Callable[[Game], float] | None = None
                       ) -> TwoDayTransitionResult:
    """Evaluate one forced day-1 pair.

    Day 2 is rolled out with the baseline first-legal policy, so the returned
    value is "day 1 plan plus day-2 baseline continuation", not a search over
    day-2 plans.
    """
    return advance_two_days(world, black_plan, red_plan, (), (),
                            leaf_value=leaf_value)


def search_two_day(world: Game, *, black_limit: int = 3, red_limit: int = 3,
                   plan_length: int = DEFAULT_PLAN_LENGTH,
                   leaf_value: Callable[[Game], float] | None = None
                   ) -> TwoDaySearchResult:
    """Known-world max/min over day-1 plans with a day-2 baseline rollout."""
    if type(black_limit) is not int or black_limit < 1:
        raise ValueError("black_limit must be a positive integer")
    if type(red_limit) is not int or red_limit < 1:
        raise ValueError("red_limit must be a positive integer")
    if type(plan_length) is not int or plan_length < 1:
        raise ValueError("plan_length must be a positive integer")
    mastermind = _advance_to_mastermind(world)
    if mastermind is None:
        return TwoDaySearchResult(0.0, (), (), 0, 0, 0, "no_day_to_plan")
    black_plans = black_day_plans(world, limit=black_limit,
                                  plan_length=plan_length)
    if not black_plans:
        return TwoDaySearchResult(0.0, (), (), 0, 0, 0, "no_black_plan")
    evaluations = 0
    red_plan_total = 0
    black_results = []
    for black in black_plans:
        red_plans = red_day_plans(mastermind, black, limit=red_limit,
                                  plan_length=plan_length)
        red_plan_total += len(red_plans)
        if not red_plans:
            continue
        scored = []
        for red in red_plans:
            outcome = evaluate_day1_pair(mastermind, black, red, leaf_value=leaf_value)
            evaluations += 1
            scored.append((red, outcome))
        best_red, best_outcome = max(scored, key=lambda item: item[1].value)
        black_results.append((black, best_red, best_outcome))
    if not black_results:
        return TwoDaySearchResult(0.0, (), (), red_plan_total, len(black_plans),
                                  evaluations, "no_red_plan")
    black_plan, red_plan, outcome = min(black_results, key=lambda item: item[2].value)
    return TwoDaySearchResult(
        outcome.value, tuple(red_plan), tuple(black_plan),
        red_plan_total, len(black_plans), evaluations,
        outcome.second.terminal if outcome.second else outcome.first.terminal,
        plan_length=plan_length)
