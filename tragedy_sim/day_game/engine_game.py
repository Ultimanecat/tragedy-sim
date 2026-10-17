"""Immutable known-script FS payoff model, with the complete physical domains."""

from .cards import CompleteCardSpace
from .continuation import DayContinuationSolver
from .pure import commit_pair
from .zero_sum import RationalInterval
from .keys import audited_fs
from ..engine import Placement


def red_commands(plan):
    return tuple(dict(actor=p.actor, action="play", card=p.card, target=p.target) for p in plan)


def red_plan(commands):
    return tuple(Placement(c["actor"], c["card"], c["target"]) for c in commands)


class EngineDayGame:
    """Fixed black targets; root red plan common to every black face choice.

    Only post-reveal abilities observe the actual red/black cards. Continuation
    uses full engine state, including private usage flags; observation-consistent
    information sets are a separate gate. This is not a fair room policy.
    """
    action_domain_complete = True
    belief_domain_complete = True  # Exactly one known script, no sampled role worlds.
    scope = "FS-known-script/unknown-root-black-faces/full-engine-state-day-minimax"
    utility = RationalInterval(0, 1)

    def __init__(self, world, *, backend="cached", max_depth=256, cache_capacity=100000, edge_cache_capacity=0):
        if not audited_fs(world):
            raise ValueError("mixed payoff model currently requires the audited built-in FS Game")
        if backend not in {"reference", "cached", "compiled"}:
            raise ValueError("unknown day-game backend")
        if type(edge_cache_capacity) is not int or edge_cache_capacity < 0 or (backend == "reference" and edge_cache_capacity):
            raise ValueError("edge cache requires a cached/compiled backend and nonnegative capacity")
        self._root = world.clone()
        self._space = CompleteCardSpace(self._root)
        if self._space.prefix:
            raise ValueError("mixed simultaneous game requires an uncommitted full red bundle")
        self._columns = tuple(self._space.black_bundles())
        self._column_set = frozenset(self._columns)
        self.row_count, self.column_count = self._space.count_red(), len(self._columns)
        if not self.row_count or not self.column_count:
            raise ValueError("empty legal card domain")
        self.kernel = None
        if backend == "reference":
            self.continuation = DayContinuationSolver(max_depth=max_depth)
        else:
            from .cached import CachedDayContinuationSolver
            self.continuation = CachedDayContinuationSolver(max_depth=max_depth, capacity=cache_capacity,
                                                           compiled=backend == "compiled", edge_cache_capacity=edge_cache_capacity)
            self.kernel = self.continuation.kernel
        self.evaluations = 0
        self.card_transitions = 0
        self.continuation_nodes = 0
        self.continuation_transitions = 0
        self.continuation_reasons = set()

    def rows(self):
        for commands in self._space.red_bundles():
            yield red_plan(commands)

    def columns(self):
        return iter(self._columns)

    def contains_row(self, action):
        if not isinstance(action, tuple) or any(type(p) is not Placement for p in action):
            return False
        return self._space.contains(red_commands(action))

    def contains_column(self, action):
        return (isinstance(action, tuple)
                and all(type(p) is Placement and all(type(v) is str for v in (p.actor, p.card, p.target)) for p in action)
                and action in self._column_set)

    def plan(self, commands):
        if not self._space.contains(commands):
            raise ValueError("seed must be a complete engine-legal red card plan")
        return red_plan(commands)

    def evaluate(self, row, column, budget):
        if not self.contains_row(row) or not self.contains_column(column):
            raise ValueError("illegal joint card action")
        after = commit_pair(self._root, red_commands(row), column, kernel=self.kernel)
        result = self.continuation.solve(after, work=budget.work)
        self.evaluations += 1
        self.card_transitions += len(row)
        self.continuation_nodes += result.nodes
        self.continuation_transitions += result.transitions
        self.continuation_reasons.update(result.stop_reasons)
        return RationalInterval(result.bounds.lower, result.bounds.upper)
