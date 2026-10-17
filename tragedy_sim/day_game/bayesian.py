"""Blocked Double Oracle preserving common red policies and posterior mass.

Each black response scans only its own world's legal face domain. Red scans
one common action domain against the weighted conditional black policies.
Unrepresented probability mass contributes the utility interval, never zero
and never a renormalized claim about the original posterior.
"""

from dataclasses import dataclass
from fractions import Fraction
from time import perf_counter

from .bayesian_matrix import solve_bayesian_matrix
from .matrix import MatrixLimit, rational
from .zero_sum import (PayoffCache, RationalInterval, SearchBudget, _first_action,
                       _unique_legal, best_response)


@dataclass(frozen=True)
class WorldBlock:
    label: str
    mass: Fraction
    game: object


class BayesianGame:
    """A fixed finite world collection with ORIGINAL, unconditioned masses.

    Input games certify equal row domains by a versioned row_domain_key.
    Complete posterior coverage additionally requires the caller's explicit
    assertion; equal sampled mass alone does not establish full coverage.
    """
    def __init__(self, blocks, *, belief_domain_complete=False, utility=RationalInterval(0, 1),
                 scope="finite-worlds/fixed-payoff-model"):
        self.blocks = tuple(WorldBlock(b.label, rational(b.mass), b.game) for b in blocks)
        if (not self.blocks or any(type(b.label) is not str or not b.label or b.mass <= 0 for b in self.blocks)
                or len({b.label for b in self.blocks}) != len(self.blocks)):
            raise ValueError("world labels must be unique and masses strictly positive")
        self.covered_mass = sum(b.mass for b in self.blocks)
        self.missing_mass = 1-self.covered_mass
        if self.missing_mass < 0 or (belief_domain_complete and self.missing_mass != 0):
            raise ValueError("original masses exceed one or asserted coverage is incomplete")
        if type(belief_domain_complete) is not bool or not isinstance(utility, RationalInterval):
            raise ValueError("explicit boolean coverage and a utility interval are required")
        base = self.blocks[0].game
        key = getattr(base, "row_domain_key", None)
        if key is None or any(getattr(b.game, "row_domain_key", None) != key for b in self.blocks):
            raise ValueError("worlds must certify a common red action domain")
        for b in self.blocks:
            if (type(b.game.row_count) is not int or b.game.row_count < 1
                    or b.game.row_count != base.row_count or type(b.game.column_count) is not int
                    or b.game.column_count < 1 or b.game.utility.lower < utility.lower
                    or b.game.utility.upper > utility.upper):
                raise ValueError("invalid world action counts or utility bounds")
        self.row_count, self.row_domain_key, self.utility = base.row_count, key, utility
        self.action_domain_complete = all(b.game.action_domain_complete for b in self.blocks)
        self.belief_domain_complete = belief_domain_complete and all(b.game.belief_domain_complete for b in self.blocks)
        self.scope = scope

    def rows(self):
        return self.blocks[0].game.rows()

    def contains_row(self, row):
        return all(b.game.contains_row(row) for b in self.blocks)


class _RedDomain:
    """Flatten only nonzero conditional support, not the black policy product."""
    def __init__(self, model):
        self.model = model
        self.row_count = model.row_count
        self.column_count = sum(b.game.column_count for b in model.blocks)
        self.utility = model.utility

    def rows(self):
        return self.model.rows()

    def contains_row(self, action):
        return self.model.contains_row(action)

    def contains_column(self, action):
        return (isinstance(action, tuple) and len(action) == 2 and type(action[0]) is int
                and 0 <= action[0] < len(self.model.blocks)
                and self.model.blocks[action[0]].game.contains_column(action[1]))


class _AggregateStats:
    def __init__(self, caches):
        self.caches = caches

    @property
    def requests(self):
        return sum(c.stats.requests for c in self.caches)


class _RedCache:
    def __init__(self, model, caches):
        self.game = _RedDomain(model)
        self.caches = caches
        self.stats = _AggregateStats(caches)

    def get(self, row, column, budget):
        index, action = column
        return self.caches[index].get(row, action, budget)


@dataclass(frozen=True)
class BayesianIteration:
    number: int
    rows: int
    columns_by_world: tuple[int, ...]
    restricted_covered_value: Fraction
    lp_pivots: int
    red_response: object
    black_responses: tuple
    lower_bound: Fraction
    upper_bound: Fraction
    added_row: bool
    added_columns: tuple[bool, ...]


@dataclass(frozen=True)
class BayesianResult:
    red: tuple
    black: tuple
    masses: tuple
    covered_mass: Fraction
    missing_mass: Fraction
    lower_bound: Fraction
    upper_bound: Fraction
    covered_lower_bound: Fraction
    covered_upper_bound: Fraction
    gap: Fraction
    epsilon: Fraction
    certified_optimal: bool
    certified_epsilon: bool
    best_response_complete: bool
    action_domain_complete: bool
    belief_domain_complete: bool
    model_scope: str
    restricted_covered_value: Fraction | None
    generated_rows: int
    columns_by_world: tuple[int, ...]
    iterations: tuple
    stop_reason: str
    elapsed_seconds: float
    numeric_error_bound: Fraction = Fraction(0)


class BayesianDoubleOracle:
    def __init__(self, model, *, seed_rows=(), seed_columns=None, payoff_cache_capacity=100000):
        self.model = model
        self.caches = tuple(PayoffCache(b.game, capacity=payoff_cache_capacity) for b in model.blocks)
        rows = _unique_legal(seed_rows, model.contains_row)
        self.rows = list(rows or (_first_action(model.rows),))
        if not model.contains_row(self.rows[0]):
            raise ValueError("common row factory emitted an illegal action")
        seed_columns = {} if seed_columns is None else dict(seed_columns)
        if any(label not in {b.label for b in model.blocks} for label in seed_columns):
            raise ValueError("black seeds contain an unknown world")
        self.columns = []
        for block in model.blocks:
            columns = _unique_legal(seed_columns.get(block.label, ()), block.game.contains_column)
            selected = list(columns or (_first_action(block.game.columns),))
            if not block.game.contains_column(selected[0]):
                raise ValueError("black factory emitted an illegal action")
            self.columns.append(selected)
        self.red = ((self.rows[0], Fraction(1)),)
        self.black = tuple(((columns[0], Fraction(1)),) for columns in self.columns)
        self.covered_lower = model.covered_mass*model.utility.lower
        self.covered_upper = model.covered_mass*model.utility.upper
        self.restricted = None
        self.responses_complete = False

    def solve(self, *, budget=None, epsilon=0, max_iterations=64, pivot_limit=100000):
        epsilon = rational(epsilon)
        if epsilon < 0 or type(max_iterations) is not int or max_iterations < 1:
            raise ValueError("epsilon must be nonnegative and iterations positive")
        if type(pivot_limit) is not int or pivot_limit < 1:
            raise ValueError("pivot_limit must be a positive integer")
        budget = budget if budget is not None else SearchBudget()
        model = self.model
        started, trace, reason = perf_counter(), [], "iteration_limit"
        residual_lo, residual_hi = (model.missing_mass*model.utility.lower, model.missing_mass*model.utility.upper)
        masses = tuple(b.mass for b in model.blocks)
        normalized = tuple(p/model.covered_mass for p in masses)  # LP scale only; results retain original mass.
        for number in range(1, max_iterations+1):
            if self.covered_upper-self.covered_lower+residual_hi-residual_lo <= epsilon:
                reason = "proven_optimal" if self.covered_upper+residual_hi == self.covered_lower+residual_lo else "proven_epsilon"
                break
            if budget.stopped():
                reason = budget.reason
                break
            matrices, incomplete = [], False
            for cache, columns in zip(self.caches, self.columns):
                matrix = []
                for row in self.rows:
                    values = []
                    for column in columns:
                        cell = cache.get(row, column, budget)
                        if not cell.exact:
                            incomplete = True
                            break
                        values.append(cell.lower)
                    if incomplete:
                        break
                    matrix.append(values)
                if incomplete:
                    break
                matrices.append(matrix)
            if incomplete:
                reason = budget.reason if budget.stopped() else "continuation_incomplete"
                break
            try:
                solution = solve_bayesian_matrix(matrices, normalized, pivot_limit=pivot_limit, deadline=budget.deadline)
            except MatrixLimit as limit:
                reason = limit.reason
                break
            self.restricted = model.covered_mass*solution.value
            red = tuple((r, p) for r, p in zip(self.rows, solution.red) if p)
            black = tuple(tuple((c, p) for c, p in zip(columns, policy) if p)
                          for columns, policy in zip(self.columns, solution.black))
            black_responses = tuple(best_response(cache, "black", red, budget, preferred=columns)
                                    for cache, columns in zip(self.caches, self.columns))
            lower = sum(p*r.bounds.lower for p, r in zip(masses, black_responses))
            if lower >= self.covered_lower:
                self.covered_lower, self.red = lower, red
            support = tuple(((h, c), mass*p) for h, (mass, policy) in enumerate(zip(normalized, black)) for c, p in policy)
            red_response = best_response(_RedCache(model, self.caches), "red", support, budget, preferred=self.rows)
            upper = model.covered_mass*red_response.bounds.upper
            if upper <= self.covered_upper:
                self.covered_upper, self.black = upper, black
            if self.covered_lower > self.covered_upper:
                raise RuntimeError("inconsistent Bayesian global bounds")
            self.responses_complete = red_response.complete and all(r.complete for r in black_responses)
            add_row = (red_response.action is not None and red_response.action not in self.rows
                       and red_response.bounds.lower > solution.value)
            additions = []
            for h, response in enumerate(black_responses):
                restricted_floor = min(sum(solution.red[i]*matrices[h][i][j] for i in range(len(self.rows)))
                                       for j in range(len(self.columns[h])))
                additions.append(response.action is not None and response.action not in self.columns[h]
                                 and response.bounds.upper < restricted_floor)
            trace.append(BayesianIteration(number, len(self.rows), tuple(map(len, self.columns)), self.restricted,
                                           solution.pivots, red_response, black_responses,
                                           self.covered_lower+residual_lo, self.covered_upper+residual_hi,
                                           add_row, tuple(additions)))
            if add_row:
                self.rows.append(red_response.action)
            for h, add in enumerate(additions):
                if add:
                    self.columns[h].append(black_responses[h].action)
            if self.covered_upper-self.covered_lower+residual_hi-residual_lo <= epsilon:
                reason = "proven_optimal" if self.covered_upper+residual_hi == self.covered_lower+residual_lo else "proven_epsilon"
                break
            if budget.stopped():
                reason = budget.reason
                break
            if not add_row and not any(additions):
                reason = "unrepresented_mass" if self.covered_upper == self.covered_lower and model.missing_mass else "incomplete_best_response"
                break
        lower, upper = self.covered_lower+residual_lo, self.covered_upper+residual_hi
        complete = model.action_domain_complete and model.belief_domain_complete and not model.missing_mass
        if not complete and reason in {"proven_optimal", "proven_epsilon"}:
            reason = "finite_model_only"
        return BayesianResult(self.red, tuple((b.label, p) for b, p in zip(model.blocks, self.black)),
                              tuple((b.label, b.mass) for b in model.blocks), model.covered_mass, model.missing_mass,
                              lower, upper, self.covered_lower, self.covered_upper, upper-lower, epsilon,
                              bool(complete and lower == upper), bool(complete and upper-lower <= epsilon),
                              self.responses_complete, model.action_domain_complete, model.belief_domain_complete,
                              model.scope, self.restricted, len(self.rows), tuple(map(len, self.columns)), tuple(trace),
                              reason, perf_counter()-started)
