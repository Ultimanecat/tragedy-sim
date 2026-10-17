"""Engine-backed, known-script minimax to the current day's boundary.

All legal optional abilities, ordering, refusals and targets are decisions.
Only the proven [0,1] utility bounds permit early termination. No playbooks,
heuristic cutoffs, state abstractions, policy RNG or transposition keys.
"""

from dataclasses import dataclass
from math import isfinite
from time import perf_counter

from ..game import Game


@dataclass(frozen=True)
class ValueBounds:
    lower: float
    upper: float

    def __post_init__(self):
        if not (isfinite(self.lower) and isfinite(self.upper)
                and 0 <= self.lower <= self.upper <= 1):
            raise ValueError("day utility bounds must satisfy 0 <= lower <= upper <= 1")

    @property
    def exact(self):
        return self.lower == self.upper


@dataclass
class WorkLimit:
    """Shared work accounting across payoff cells, not a per-cell allowance."""
    node_limit: int | None = 100_000
    time_limit_ms: int | None = None

    def __post_init__(self):
        for name in ("node_limit", "time_limit_ms"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 1):
                raise ValueError(f"{name} must be a positive integer or None")
        self.started = perf_counter()
        self.nodes = 0
        self.transitions = 0
        self.reasons = set()

    def exhausted(self):
        if self.time_limit_ms is not None and (perf_counter() - self.started) * 1000 >= self.time_limit_ms:
            self.reasons.add("time_limit")
            return True
        if self.node_limit is not None and self.nodes >= self.node_limit:
            self.reasons.add("node_limit")
            return True
        return False


@dataclass(frozen=True)
class DayResult:
    bounds: ValueBounds
    nodes: int
    transitions: int
    leaves: int
    max_depth: int
    principal_action: dict | None
    stop_reasons: tuple[str, ...]
    elapsed_seconds: float
    horizon: str = "day"
    utility: str = "day-survival-v1"
    information: str = "known-script-after-card-commitment"
    continuation: str = "all-engine-legal-decisions"


def day_boundary_value(world, position):
    """Loop loss is a failed survival day, even if a future loop could win."""
    if world.winner is not None:
        return float(world.winner == "protagonists")
    if world.state.phase in {"loop_end", "final_guess"}:
        return 0.0
    if world.state.loop != position[0]:
        return 0.0
    if world.state.round != position[1]:
        return 1.0
    return None


class DayContinuationSolver:
    def __init__(self, *, max_depth=256):
        if type(max_depth) is not int or max_depth < 1:
            raise ValueError("max_depth must be a positive integer")
        self.max_depth = max_depth

    def _transition(self, current, action):
        return current.transition(action).game

    def _cache_key(self, current, position):
        return None

    def _lookup(self, key):
        return None

    def _store(self, key, result):
        pass

    def solve(self, world, *, position=None, work=None):
        if not isinstance(world, Game) or world.module != "FS":
            raise ValueError("exact day continuation currently requires an FS Game")
        if world.state.phase in {"mastermind", "protagonists"}:
            raise ValueError("commit both card bundles before solving continuation")
        position = position or (world.state.loop, world.state.round)
        if (not isinstance(position, tuple) or len(position) != 2
                or any(type(n) is not int or n < 1 for n in position)):
            raise ValueError("position must be a positive (loop, day) tuple")
        if world.state.loop < position[0] or (world.state.loop == position[0] and world.state.round < position[1]):
            raise ValueError("world precedes the requested day")
        if world.state.phase == "day_start" and day_boundary_value(world, position) is None:
            raise ValueError("commit both card bundles before solving continuation")
        work = work if work is not None else WorkLimit()
        started, nodes_before, edges_before = perf_counter(), work.nodes, work.transitions
        leaves, deepest, local_reasons = 0, 0, set()

        def visit(current, depth):
            nonlocal leaves, deepest
            deepest = max(deepest, depth)
            terminal = day_boundary_value(current, position)
            if terminal is not None:
                leaves += 1
                return ValueBounds(terminal, terminal), None
            if work.exhausted():
                local_reasons.update(work.reasons)
                return ValueBounds(0, 1), None
            if depth >= self.max_depth:
                local_reasons.add("depth_limit")
                return ValueBounds(0, 1), None
            cache_key = self._cache_key(current, position)
            cached = self._lookup(cache_key)
            if cached is not None:
                return cached

            def finish(bounds, action):
                result = (bounds, action)
                self._store(cache_key, result)
                return result
            actor = current.controller
            if actor not in {"m", "a", "b", "c"}:
                raise RuntimeError("nonterminal day node has no legal controller")
            actions = current.legal_actions(actor)
            if not actions:
                raise RuntimeError("nonterminal day node has no legal actions")
            work.nodes += 1
            maximize = actor != "m"
            lower, upper = (0.0, 0.0) if maximize else (1.0, 1.0)
            best_action, best_bound = None, -1 if maximize else 2
            for index, action in enumerate(actions):
                # The current expansion already consumed its node. A node
                # cap applies to child expansion; time also bounds transitions.
                if work.time_limit_ms is not None and (perf_counter() - work.started) * 1000 >= work.time_limit_ms:
                    work.reasons.add("time_limit")
                    local_reasons.add("time_limit")
                    return (ValueBounds(lower, 1) if maximize else ValueBounds(0, upper)), best_action
                child = self._transition(current, action)
                work.transitions += 1
                bounds, _ = visit(child, depth + 1)
                if maximize:
                    lower, upper = max(lower, bounds.lower), max(upper, bounds.upper)
                    if bounds.lower > best_bound:
                        best_action, best_bound = dict(action), bounds.lower
                    if lower == 1:
                        return finish(ValueBounds(1, 1), best_action)
                else:
                    lower, upper = min(lower, bounds.lower), min(upper, bounds.upper)
                    if bounds.upper < best_bound:
                        best_action, best_bound = dict(action), bounds.upper
                    if upper == 0:
                        return finish(ValueBounds(0, 0), best_action)
                if work.exhausted() and index + 1 < len(actions):
                    local_reasons.update(work.reasons)
                    return (ValueBounds(lower, 1) if maximize else ValueBounds(0, upper)), best_action
            return finish(ValueBounds(lower, upper), best_action)

        bounds, action = visit(world, 0)
        return DayResult(bounds, work.nodes - nodes_before, work.transitions - edges_before,
                         leaves, deepest, action, tuple(sorted(local_reasons)), perf_counter() - started)
