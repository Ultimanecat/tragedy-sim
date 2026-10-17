"""Finite-domain Double Oracle with exact probabilities and rigorous bounds.

Rows maximize, columns minimize. Missing cells retain the model's utility
range. Best-response scans include the full declared domain, with only proved
partial-sum cuts; budget-limited scans retain bounds for unvisited actions.
"""

from collections import OrderedDict
from dataclasses import dataclass
from fractions import Fraction
from time import perf_counter

from .continuation import WorkLimit
from .matrix import MatrixLimit, matrix_values, rational, solve_matrix


@dataclass(frozen=True)
class RationalInterval:
    lower: Fraction
    upper: Fraction

    def __post_init__(self):
        object.__setattr__(self, "lower", rational(self.lower))
        object.__setattr__(self, "upper", rational(self.upper))
        if self.lower > self.upper:
            raise ValueError("lower bound exceeds upper bound")

    @property
    def exact(self):
        return self.lower == self.upper


class SearchBudget:
    """One engine node/time allowance and one uncached-cell allowance."""

    def __init__(self, *, work=None, payoff_limit=None):
        if payoff_limit is not None and (type(payoff_limit) is not int or payoff_limit < 1):
            raise ValueError("payoff_limit must be a positive integer or None")
        if work is not None and not isinstance(work, WorkLimit):
            raise ValueError("work must be a WorkLimit")
        self.work = work if work is not None else WorkLimit(node_limit=None)
        self.payoff_limit = payoff_limit
        self.payoffs = 0
        self.reasons = set()

    @property
    def deadline(self):
        return (None if self.work.time_limit_ms is None else
                self.work.started + self.work.time_limit_ms / 1000)

    def stopped(self):
        if self.work.exhausted():
            self.reasons.update(self.work.reasons)
            return True
        if self.payoff_limit is not None and self.payoffs >= self.payoff_limit:
            self.reasons.add("payoff_limit")
            return True
        return False

    def consume_payoff(self):
        if self.stopped():
            return False
        self.payoffs += 1
        return True

    @property
    def reason(self):
        return sorted(self.reasons)[0] if self.reasons else "budget_limit"


class MatrixGame:
    """Complete, explicit finite matrix; an independent full-matrix reference."""
    action_domain_complete = True
    belief_domain_complete = True
    scope = "given-finite-payoff-matrix"

    def __init__(self, matrix):
        self.values = matrix_values(matrix)
        self.row_count, self.column_count = len(self.values), len(self.values[0])
        self.row_domain_key = ("matrix-row-indices-v1", self.row_count)
        self.utility = RationalInterval(min(min(row) for row in self.values), max(max(row) for row in self.values))

    def rows(self):
        return iter(range(self.row_count))

    def columns(self):
        return iter(range(self.column_count))

    def contains_row(self, action):
        return type(action) is int and 0 <= action < self.row_count

    def contains_column(self, action):
        return type(action) is int and 0 <= action < self.column_count

    def evaluate(self, row, column, budget):
        return RationalInterval(self.values[row][column], self.values[row][column])


@dataclass
class PayoffStats:
    requests: int = 0
    hits: int = 0
    evaluations: int = 0
    unknowns: int = 0
    budget_unknowns: int = 0
    evictions: int = 0


class PayoffCache:
    def __init__(self, game, *, capacity=100000):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("payoff cache capacity must be a positive integer")
        self.game, self.capacity = game, capacity
        self.values = OrderedDict()
        self.stats = PayoffStats()

    def get(self, row, column, budget):
        if not self.game.contains_row(row) or not self.game.contains_column(column):
            raise ValueError("payoff action is outside the declared legal domain")
        self.stats.requests += 1
        key = row, column
        if key in self.values:
            self.stats.hits += 1
            self.values.move_to_end(key)
            return self.values[key]
        if not budget.consume_payoff():
            self.stats.budget_unknowns += 1
            return self.game.utility
        self.stats.evaluations += 1
        result = self.game.evaluate(row, column, budget)
        if not isinstance(result, RationalInterval):
            raise ValueError("payoff evaluator must return a RationalInterval")
        if result.lower < self.game.utility.lower or result.upper > self.game.utility.upper:
            raise ValueError("payoff lies outside the model's utility bounds")
        if result.exact:
            self.values[key] = result
            if len(self.values) > self.capacity:
                self.values.popitem(last=False)
                self.stats.evictions += 1
        else:
            self.stats.unknowns += 1
        return result


def _unique_legal(actions, contains):
    result, seen = [], set()
    for action in actions:
        if not contains(action):
            raise ValueError("preferred action is outside the complete legal domain")
        if action not in seen:
            seen.add(action)
            result.append(action)
    return tuple(result)


def _ordered_domain(factory, preferred):
    seen = set(preferred)
    yield from preferred
    for action in factory():
        if action not in seen:
            yield action


def _first_action(factory):
    try:
        return next(factory())
    except StopIteration as error:
        raise ValueError("action factory has an empty domain") from error


def _support(distribution, contains):
    probabilities = {}
    for action, weight in distribution:
        if not contains(action):
            raise ValueError("opponent support contains an illegal action")
        weight = rational(weight)
        if weight < 0:
            raise ValueError("mixed probabilities must be nonnegative")
        probabilities[action] = probabilities.get(action, Fraction(0)) + weight
    if not probabilities or sum(probabilities.values()) != 1:
        raise ValueError("mixed probabilities must sum exactly to one")
    return tuple((a, p) for a, p in probabilities.items() if p)


@dataclass(frozen=True)
class BestResponse:
    side: str
    action: object
    bounds: RationalInterval
    visited: int
    domain_size: int
    pruned: int
    payoff_requests: int
    complete: bool
    domain_exhausted: bool
    stop_reason: str


def best_response(cache, side, distribution, budget, *, preferred=()):
    game = cache.game
    if side not in {"red", "black"}:
        raise ValueError("best-response side must be red or black")
    maximize = side == "red"
    contains = game.contains_row if maximize else game.contains_column
    factory = game.rows if maximize else game.columns
    count = game.row_count if maximize else game.column_count
    if type(count) is not int or count < 1:
        raise ValueError("finite action counts must be positive integers")
    preferred = _unique_legal(preferred, contains)
    support = _support(distribution, game.contains_column if maximize else game.contains_row)
    umin, umax = game.utility.lower, game.utility.upper
    visited = pruned = 0
    calls_before = cache.stats.requests
    best_action = None
    lower, upper = (umin, umin) if maximize else (umax, umax)
    exhausted, reason = False, "complete_domain"
    for candidate in _ordered_domain(factory, preferred):
        if budget.stopped():
            reason = budget.reason
            break
        visited += 1
        if visited > count:
            raise ValueError("action factory exceeded its declared domain size")
        lo, hi = umin, umax
        for opponent, probability in support:
            if budget.deadline is not None and perf_counter() >= budget.deadline:
                budget.reasons.add("time_limit")
                break
            result = cache.get(candidate, opponent, budget) if maximize else cache.get(opponent, candidate, budget)
            lo += probability * (result.lower - umin)
            hi += probability * (result.upper - umax)
            if best_action is not None and ((maximize and hi <= lower) or (not maximize and lo >= upper)):
                pruned += 1
                break
        if maximize:
            if best_action is None or lo > lower:
                best_action = candidate
            lower, upper = max(lower, lo), max(upper, hi)
            extreme = lower == umax
        else:
            if best_action is None or hi < upper:
                best_action = candidate
            lower, upper = min(lower, lo), min(upper, hi)
            extreme = upper == umin
        if extreme:
            value = umax if maximize else umin
            return BestResponse(side, best_action, RationalInterval(value, value), visited, count, pruned,
                                cache.stats.requests-calls_before, True, visited == count, "utility_extremum")
    else:
        exhausted = True
        if visited != count:
            raise ValueError("action factory did not cover its declared domain size")
    if not exhausted:
        if maximize:
            upper = umax
        else:
            lower = umin
    bounds = RationalInterval(lower, upper)
    if not bounds.exact:
        reason = budget.reason if budget.stopped() else "continuation_incomplete"
    return BestResponse(side, best_action, bounds, visited, count, pruned, cache.stats.requests-calls_before,
                        bounds.exact, exhausted, reason)


@dataclass(frozen=True)
class OracleIteration:
    number: int
    matrix_rows: int
    matrix_columns: int
    restricted_value: Fraction
    lp_pivots: int
    red_response: BestResponse
    black_response: BestResponse
    lower_bound: Fraction
    upper_bound: Fraction
    payoffs: int
    added_row: bool
    added_column: bool


@dataclass(frozen=True)
class MixedResult:
    red: tuple
    black: tuple
    lower_bound: Fraction
    upper_bound: Fraction
    gap: Fraction
    epsilon: Fraction
    certified_optimal: bool
    certified_epsilon: bool
    best_response_complete: bool
    action_domain_complete: bool
    belief_domain_complete: bool
    model_scope: str
    restricted_value: Fraction | None
    matrix_shape: tuple[int, int]
    generated_rows: int
    generated_columns: int
    iterations: tuple[OracleIteration, ...]
    stop_reason: str
    elapsed_seconds: float
    numeric_error_bound: Fraction = Fraction(0)
    strategy_class: str = "mixed"


class DoubleOracle:
    """Resumable for one immutable model; restricted supports only grow."""

    def __init__(self, game, *, seed_rows=(), seed_columns=(), payoff_cache_capacity=100000):
        if (type(game.row_count) is not int or game.row_count < 1
                or type(game.column_count) is not int or game.column_count < 1):
            raise ValueError("finite model has an empty action domain")
        self.game = game
        self.cache = PayoffCache(game, capacity=payoff_cache_capacity)
        rows = _unique_legal(seed_rows, game.contains_row)
        columns = _unique_legal(seed_columns, game.contains_column)
        self.rows = list(rows or (_first_action(game.rows),))
        self.columns = list(columns or (_first_action(game.columns),))
        if not game.contains_row(self.rows[0]) or not game.contains_column(self.columns[0]):
            raise ValueError("action factory emitted an illegal initial action")
        self.lower, self.upper = game.utility.lower, game.utility.upper
        self.red = ((self.rows[0], Fraction(1)),)
        self.black = ((self.columns[0], Fraction(1)),)
        self.restricted_value = None
        self.matrix_shape = (0, 0)
        self.last_red = self.last_black = None

    def solve(self, *, budget=None, epsilon=0, max_iterations=64, pivot_limit=100000):
        epsilon = rational(epsilon)
        if epsilon < 0:
            raise ValueError("epsilon must be nonnegative")
        if type(max_iterations) is not int or max_iterations < 1:
            raise ValueError("max_iterations must be a positive integer")
        if type(pivot_limit) is not int or pivot_limit < 1:
            raise ValueError("pivot_limit must be a positive integer")
        budget = budget if budget is not None else SearchBudget()
        started = perf_counter()
        trace, reason = [], "iteration_limit"
        last_red, last_black = self.last_red, self.last_black
        for number in range(1, max_iterations + 1):
            if self.upper - self.lower <= epsilon:
                reason = "proven_optimal" if self.upper == self.lower else "proven_epsilon"
                break
            if budget.stopped():
                reason = budget.reason
                break
            matrix, incomplete = [], False
            for row in self.rows:
                values = []
                for column in self.columns:
                    interval = self.cache.get(row, column, budget)
                    if not interval.exact:
                        incomplete = True
                        break
                    values.append(interval.lower)
                if incomplete:
                    break
                matrix.append(values)
            if incomplete:
                reason = budget.reason if budget.stopped() else "continuation_incomplete"
                break
            try:
                equilibrium = solve_matrix(matrix, pivot_limit=pivot_limit, deadline=budget.deadline)
            except MatrixLimit as limit:
                reason = limit.reason
                break
            self.restricted_value = equilibrium.value
            self.matrix_shape = (len(self.rows), len(self.columns))
            red = tuple((a, p) for a, p in zip(self.rows, equilibrium.red) if p)
            black = tuple((a, p) for a, p in zip(self.columns, equilibrium.black) if p)
            last_black = best_response(self.cache, "black", red, budget, preferred=self.columns)
            if last_black.bounds.lower >= self.lower:
                self.lower, self.red = last_black.bounds.lower, red
            last_red = best_response(self.cache, "red", black, budget, preferred=self.rows)
            self.last_red, self.last_black = last_red, last_black
            if last_red.bounds.upper <= self.upper:
                self.upper, self.black = last_red.bounds.upper, black
            if self.lower > self.upper:
                raise RuntimeError("global mixed-game certificate has inconsistent bounds")
            add_row = (last_red.action is not None and last_red.action not in self.rows
                       and last_red.bounds.lower > equilibrium.value)
            add_column = (last_black.action is not None and last_black.action not in self.columns
                          and last_black.bounds.upper < equilibrium.value)
            trace.append(OracleIteration(number, *self.matrix_shape, equilibrium.value, equilibrium.pivots, last_red, last_black,
                                         self.lower, self.upper, budget.payoffs, add_row, add_column))
            if add_row:
                self.rows.append(last_red.action)
            if add_column:
                self.columns.append(last_black.action)
            if self.upper - self.lower <= epsilon:
                reason = "proven_optimal" if self.upper == self.lower else "proven_epsilon"
                break
            if budget.stopped():
                reason = budget.reason
                break
            if not add_row and not add_column:
                reason = "incomplete_best_response"
                break
        complete_model = self.game.action_domain_complete and self.game.belief_domain_complete
        if not complete_model and reason in {"proven_optimal", "proven_epsilon"}:
            reason = "finite_model_only"
        return MixedResult(self.red, self.black, self.lower, self.upper, self.upper-self.lower, epsilon,
                           complete_model and self.upper == self.lower,
                           complete_model and self.upper-self.lower <= epsilon,
                           bool(last_red and last_black and last_red.complete and last_black.complete),
                           self.game.action_domain_complete, self.game.belief_domain_complete, self.game.scope,
                           self.restricted_value, self.matrix_shape, len(self.rows), len(self.columns), tuple(trace),
                           reason, perf_counter()-started)
