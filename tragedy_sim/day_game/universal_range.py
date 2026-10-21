"""All-native-action utility ranges, independent of either player's policy.

Only proven constants may replace an information subtree. An exact [0,1]
range requires witnesses for BOTH utilities; budget uncertainty is never
cached as a nonconstant proof. Scope is audited FS day-survival-v1 only.
"""

from collections import OrderedDict
from dataclasses import asdict, dataclass
from time import perf_counter

from .continuation import WorkLimit, day_boundary_value
from .kernel import FsTransitionKernel
from .keys import UnsupportedKey, audited_fs, rule_state_key


@dataclass(frozen=True)
class NativeRange:
    minimum: int = 0
    maximum: int = 1
    exact: bool = False

    @property
    def constant(self):
        return self.minimum if self.exact and self.minimum == self.maximum else None


UNKNOWN = NativeRange()
MIXED = NativeRange(0, 1, True)


@dataclass
class RangeStats:
    calls: int = 0
    hits: int = 0
    stores: int = 0
    evictions: int = 0
    nodes: int = 0
    transitions: int = 0
    constants: int = 0
    mixed: int = 0
    cutoffs: int = 0
    unsupported: int = 0
    cache_only_misses: int = 0
    bottom_up_stores: int = 0


class UniversalDayRange:
    version = "fs-all-native-actions/day-survival-v1"

    def __init__(self, *, capacity=20000, backend="cached"):
        if type(capacity) is not int or capacity < 1 or backend not in {"reference", "cached"}:
            raise ValueError("range cache needs positive capacity and a native/cached backend")
        self.capacity, self.backend = capacity, backend
        self.values, self.stats = OrderedDict(), RangeStats()
        self.kernel = FsTransitionKernel() if backend == "cached" else None

    def report(self):
        return dict(**asdict(self.stats), entries=len(self.values))

    def _store(self, key, result):
        if key is None or not result.exact:
            return
        if key in self.values and self.values[key] != result:
            raise RuntimeError("contradictory exact universal range certificates")
        self.values[key] = result
        self.values.move_to_end(key)
        self.stats.stores += 1
        if len(self.values) > self.capacity:
            self.values.popitem(last=False)
            self.stats.evictions += 1

    def _remember_constant(self, world, position, value):
        """Internal sink for the builder's all-native-child proof.

        A frozen opponent's selected path alone is NOT such a proof. The
        caller must carry full-native coverage through every child, including
        forced steps. This function never runs a policy or adds search work.
        """
        if value not in {0, 1} or not audited_fs(world):
            raise ValueError("invalid native constant proof")
        try:
            key = self.version, position, rule_state_key(world)
        except (UnsupportedKey, RecursionError):
            self.stats.unsupported += 1
            return
        self._store(key, NativeRange(int(value), int(value), True))
        self.stats.bottom_up_stores += 1

    def probe(self, world, *, position=None, work=None, node_limit=256, max_depth=128):
        if not audited_fs(world):
            raise ValueError("universal ranges require the audited native FS engine")
        if type(node_limit) is not int or node_limit < 0 or type(max_depth) is not int or max_depth < 1:
            raise ValueError("probe node limit must be nonnegative and depth positive")
        position = position or (world.state.loop, world.state.round)
        if (not isinstance(position, tuple) or len(position) != 2
                or any(type(n) is not int or n < 1 for n in position)):
            raise ValueError("range position must be a positive loop/day pair")
        if (world.state.loop, world.state.round) < position:
            raise ValueError("range root precedes the requested day")
        work = WorkLimit() if work is None else work
        self.stats.calls += 1
        start_nodes = self.stats.nodes

        def visit(current, depth):
            terminal = day_boundary_value(current, position)
            if terminal is not None:
                value = int(terminal)
                return NativeRange(value, value, True)
            if current.state.phase in {"mastermind", "protagonists", "day_start"}:
                # Card root decisions require their own nonanticipating model.
                return UNKNOWN
            if work.exhausted() or depth >= max_depth:
                self.stats.cutoffs += 1
                return UNKNOWN
            if not self.values and node_limit == 0:
                self.stats.cache_only_misses += 1
                return UNKNOWN
            try:
                key = (self.version, position, rule_state_key(current))
            except (UnsupportedKey, RecursionError):
                self.stats.unsupported += 1
                return UNKNOWN
            cached = self.values.get(key)
            if cached is not None:
                self.values.move_to_end(key)
                self.stats.hits += 1
                return cached
            if node_limit == 0:
                self.stats.cache_only_misses += 1
                return UNKNOWN
            if self.stats.nodes-start_nodes >= node_limit:
                self.stats.cutoffs += 1
                return UNKNOWN
            actions = current.legal_actions(current.controller)
            if not actions:
                raise ValueError("nonterminal range node has no legal actions")
            work.nodes += 1
            self.stats.nodes += 1
            constant = None
            for action in actions:
                if work.time_limit_ms is not None and (perf_counter()-work.started)*1000 >= work.time_limit_ms:
                    work.reasons.add("time_limit")
                    self.stats.cutoffs += 1
                    return UNKNOWN
                child = (current.transition(action).game if self.kernel is None else
                         self.kernel.transition(current, action))
                work.transitions += 1
                self.stats.transitions += 1
                result = visit(child, depth+1)
                if not result.exact:
                    return UNKNOWN
                if result.constant is None or (constant is not None and constant != result.constant):
                    # One mixed child, or two proven constant children with
                    # opposite utilities, witnesses both endpoints. Other
                    # unvisited children cannot widen the known [0,1] range.
                    self._store(key, MIXED)
                    return MIXED
                constant = result.constant
            result = NativeRange(constant, constant, True)
            self._store(key, result)
            return result

        result = visit(world, 0)
        if result.constant is not None:
            self.stats.constants += 1
        elif result.exact:
            self.stats.mixed += 1
        return result
