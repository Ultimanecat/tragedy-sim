"""FS exact-value transpositions, scoped to known-script day survival only."""

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass

from .continuation import DayContinuationSolver
from .kernel import FsTransitionKernel
from .keys import UnsupportedKey, rule_state_key


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    stores: int = 0
    evictions: int = 0
    fallbacks: int = 0


class CachedDayContinuationSolver(DayContinuationSolver):
    """Caches proven exact values only, never budget-limited unknown results.

    Complete known-world minimax with 0/1 day utility does not depend on which
    observations led to an identical rule state. No observation-conditioned
    policy, belief update, future-day evaluator or rollout RNG is used here.
    These keys/values cannot be reused for the later fair information-set game.
    """

    def __init__(self, *, max_depth=256, capacity=100000, compiled=False, edge_cache_capacity=0):
        super().__init__(max_depth=max_depth)
        if type(capacity) is not int or capacity < 1:
            raise ValueError("cache capacity must be a positive integer")
        self.capacity = capacity
        self.values = OrderedDict()
        self.stats = CacheStats()
        self.kernel = FsTransitionKernel(compiled=compiled, edge_cache_capacity=edge_cache_capacity)

    def _transition(self, current, action):
        return self.kernel.transition(current, action)

    def _cache_key(self, current, position):
        try:
            return ("known-script-day-survival-v1", position, rule_state_key(current))
        except (UnsupportedKey, RecursionError):
            self.stats.fallbacks += 1
            return None

    def _lookup(self, key):
        if key is None:
            return None
        result = self.values.get(key)
        if result is None:
            self.stats.misses += 1
        else:
            self.stats.hits += 1
            self.values.move_to_end(key)
        return deepcopy(result)

    def _store(self, key, result):
        if key is None or not result[0].exact:
            return
        self.values[key] = deepcopy(result)
        self.values.move_to_end(key)
        self.stats.stores += 1
        if len(self.values) > self.capacity:
            self.values.popitem(last=False)
            self.stats.evictions += 1
