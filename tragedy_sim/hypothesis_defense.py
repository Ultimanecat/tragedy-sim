"""Posterior-weighted tactical ordering with hypothesis-local dark attacks.

One group belongs to one original posterior draw. Extra dark attack scenes
within that group never increase its mass. These scores only order candidates;
the authoritative engine cross-evaluates each complete plan afterwards.
"""

import math

from .joint_defense_ranker import JointThreatRanker


class HypothesisThreatRanker:
    def __init__(self, groups, space, *, weights=None, cache_limit=32768):
        groups = tuple(tuple(group) for group in groups)
        if not groups or any(not group for group in groups):
            raise ValueError("nonempty posterior groups required")
        masses = (1,) * len(groups) if weights is None else tuple(weights)
        if (len(masses) != len(groups) or any(type(w) not in {int, float}
                or not math.isfinite(w) or w < 0 for w in masses)):
            raise ValueError("finite nonnegative posterior masses required")
        try:
            total = math.fsum(masses)
        except OverflowError as error:
            raise ValueError("finite positive posterior mass required") from error
        if not math.isfinite(total) or total <= 0:
            raise ValueError("finite positive posterior mass required")
        self.weights = tuple(w / total for w in masses)
        self.groups = tuple(JointThreatRanker(group, space, state_policy="worst", cache_limit=cache_limit)
                            for group in groups)

    @property
    def projections(self):
        return sum(group.projections for group in self.groups)

    def __call__(self, plan):
        rows = tuple(group(plan) for group in self.groups)
        # A group's safety estimate is conditional on all its tested attacks.
        # Cardinality is coverage, not the probability of that hypothesis.
        return (math.fsum(w * int(row[0] == 1) for w, row in zip(self.weights, rows)),
                math.fsum(w * row[1] for w, row in zip(self.weights, rows)),
                math.fsum(w * row[2] for w, row in zip(self.weights, rows)))
