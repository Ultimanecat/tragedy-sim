"""T2 scaffold: bounded known-world two-day day-survival search (FS).

This is a diagnostic scaffold, not a production policy. Card commitment is
modeled sequentially (black placements then red placements) because the
existing day solver has no simultaneous-hidden-card node yet. Action limits
make the result restricted, never certified.
"""

from dataclasses import dataclass
from time import perf_counter

from ..game import Game
from .continuation import ValueBounds, WorkLimit


@dataclass(frozen=True)
class TwoDayResult:
    bounds: ValueBounds
    nodes: int
    transitions: int
    leaves: int
    max_depth: int
    principal_action: dict | None
    stop_reasons: tuple[str, ...]
    elapsed_seconds: float
    action_limit: int
    restricted: bool
    horizon: str = "two-days"
    utility: str = "day-survival-v1"
    information: str = "known-world"
    model: str = "sequential-card-commitment"


class KnownWorldTwoDaySolver:
    """Two-day survival search with a per-node action cap for diagnosis."""

    def __init__(self, *, max_depth=128, action_limit=4):
        if type(max_depth) is not int or max_depth < 1:
            raise ValueError("max_depth must be a positive integer")
        if type(action_limit) is not int or action_limit < 1:
            raise ValueError("action_limit must be a positive integer")
        self.max_depth, self.action_limit = max_depth, action_limit

    def solve(self, world, *, work=None):
        if not isinstance(world, Game) or world.module != "FS":
            raise ValueError("two-day scaffold currently requires an FS Game")
        if world.winner is not None:
            value = 1.0 if world.winner == "protagonists" else 0.0
            return TwoDayResult(ValueBounds(value, value), 0, 0, 0, 0, None, (),
                                perf_counter(), self.action_limit, False)
        start_loop, start_round = world.state.loop, world.state.round
        target_round = start_round + 2
        if world.state.phase in {"final_guess", "game_over"}:
            raise ValueError("two-day search requires a live day")
        work = WorkLimit() if work is None else work
        started, nodes_before, edges_before = perf_counter(), work.nodes, work.transitions
        leaves, deepest, reasons = 0, 0, set()

        def terminal(current):
            if current.winner is not None:
                return 1.0 if current.winner == "protagonists" else 0.0
            if current.state.phase in {"loop_end", "final_guess", "game_over"}:
                return 0.0
            if current.state.loop != start_loop:
                return 0.0
            if current.state.round >= target_round:
                return 1.0
            return None

        def visit(current, depth):
            nonlocal leaves, deepest
            deepest = max(deepest, depth)
            value = terminal(current)
            if value is not None:
                leaves += 1
                return ValueBounds(value, value), None
            if work.exhausted():
                reasons.update(work.reasons)
                return ValueBounds(0, 1), None
            if depth >= self.max_depth:
                reasons.add("depth_limit")
                return ValueBounds(0, 1), None
            actor = current.controller
            if actor not in {"m", "a", "b", "c"}:
                raise RuntimeError("nonterminal two-day node has no legal controller")
            actions = current.legal_actions(actor)
            if not actions:
                raise RuntimeError("nonterminal two-day node has no legal actions")
            work.nodes += 1
            maximize = actor != "m"
            lower, upper = (0.0, 0.0) if maximize else (1.0, 1.0)
            best_action, best_bound = None, -1 if maximize else 2
            for index, action in enumerate(actions):
                if index >= self.action_limit:
                    reasons.add("action_limit")
                    break
                child = current.transition(action).game
                work.transitions += 1
                bounds, _ = visit(child, depth + 1)
                if maximize:
                    lower, upper = max(lower, bounds.lower), max(upper, bounds.upper)
                    if bounds.lower > best_bound:
                        best_action, best_bound = dict(action), bounds.lower
                    if lower == 1:
                        return ValueBounds(1, 1), best_action
                else:
                    lower, upper = min(lower, bounds.lower), min(upper, bounds.upper)
                    if bounds.upper < best_bound:
                        best_action, best_bound = dict(action), bounds.upper
                    if upper == 0:
                        return ValueBounds(0, 0), best_action
                if work.exhausted() and index + 1 < len(actions):
                    reasons.update(work.reasons)
                    return (ValueBounds(lower, 1) if maximize else ValueBounds(0, upper)), best_action
            return ValueBounds(lower, upper), best_action

        bounds, action = visit(world, 0)
        return TwoDayResult(bounds, work.nodes - nodes_before, work.transitions - edges_before,
                            leaves, deepest, action, tuple(sorted(reasons)), perf_counter() - started,
                            self.action_limit, True)
