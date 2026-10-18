"""Information-set root constraint generation with full-domain certificates.

Each restricted game optimizes both players' native ability policies. Full
responses evaluate frozen observable policy extensions, not scalar cell-wise
red clairvoyance. Global lower/upper bounds retain their own strategy witnesses.
"""

from dataclasses import dataclass
from fractions import Fraction as Q
from time import perf_counter

from .continuation import WorkLimit
from .frozen_information import FrozenBehavior, FrozenInformationStrategy, freeze_information_solution
from .information_game import build_root_information_tree, solve_information_tree
from .information_response import (BlackSkipCache, InformationResponse, black_information_response,
                                   red_information_response, _deadline)
from .matrix import MatrixLimit, rational
from .zero_sum import RationalInterval


@dataclass(frozen=True)
class InformationOracleIteration:
    number: int
    rows: int
    columns: tuple
    restricted_bounds: RationalInterval
    global_bounds: RationalInterval
    red_response: object
    black_responses: tuple
    added_row: bool
    added_columns: tuple


@dataclass(frozen=True)
class InformationOracleResult:
    bounds: RationalInterval
    lower_strategy: FrozenInformationStrategy
    upper_strategy: FrozenInformationStrategy
    epsilon: Q
    certified_optimal: bool
    certified_epsilon: bool
    belief_domain_complete: bool
    action_domain_complete: bool
    best_response_complete: bool
    restricted_rows: int
    restricted_columns: tuple
    iterations: tuple
    stop_reason: str
    engine_nodes: int
    engine_transitions: int
    elapsed_seconds: float
    scope: str
    skip_cache: dict
    horizon: str = "day"
    utility: str = "day-survival-v1"

    @property
    def red(self):
        return self.lower_strategy.red_cards


class InformationDoubleOracle:
    def __init__(self, model, *, seed_rows=(), seed_columns=None):
        self.model = model
        self.rows = list(dict.fromkeys(seed_rows)) or [next(model.rows())]
        if any(not model.contains_row(row) for row in self.rows):
            raise ValueError("illegal seed red card plan")
        supplied = (tuple(tuple(c) for c in seed_columns) if seed_columns is not None else
                    tuple((next(b.game.columns()),) for b in model.blocks))
        if len(supplied) != len(model.blocks):
            raise ValueError("one initial black column set per setup is required")
        self.columns = [list(dict.fromkeys(c)) for c in supplied]
        if any(not columns or any(not b.game.contains_column(c) for c in columns)
               for b, columns in zip(model.blocks, self.columns)):
            raise ValueError("illegal seed black card columns")
        initial = FrozenInformationStrategy(((self.rows[0], Q(1)),),
            tuple((b.label, ((c[0], Q(1)),)) for b, c in zip(model.blocks, self.columns)),
            FrozenBehavior("red"), FrozenBehavior("black"))
        self.lower_strategy = self.upper_strategy = initial
        self.lower, self.upper = Q(0), Q(1)
        self.responses_complete = False
        self.skip_cache = BlackSkipCache()

    def solve(self, *, work=None, epsilon="1/100", max_iterations=32, max_depth=128,
              tree_node_limit=10000, lp_cell_limit=2000000, pivot_limit=100000, response_candidate_limit=None):
        epsilon = rational(epsilon)
        if epsilon < 0 or type(max_iterations) is not int or max_iterations < 1:
            raise ValueError("epsilon must be nonnegative and iteration limit positive")
        work = WorkLimit(node_limit=100000) if work is None else work
        start_nodes, start_edges, started = work.nodes, work.transitions, perf_counter()
        trace, reason = [], "iteration_limit"
        model = self.model
        options = dict(max_depth=max_depth, tree_node_limit=tree_node_limit)
        for number in range(1, max_iterations+1):
            if self.upper-self.lower <= epsilon:
                reason = "proven_optimal" if self.upper == self.lower else "proven_epsilon"
                break
            if work.exhausted():
                reason = "/".join(sorted(work.reasons))
                break
            try:
                tree = build_root_information_tree(model, self.rows, self.columns, work=work, **options)
                solved = solve_information_tree(tree, deadline=_deadline(work), pivot_limit=pivot_limit,
                                                lp_cell_limit=lp_cell_limit)
            except MatrixLimit as error:
                reason = error.reason
                break
            strategy = freeze_information_solution(tree, solved)
            black = tuple(black_information_response(b, strategy, work, preferred=columns,
                          candidate_limit=response_candidate_limit, skip_cache=self.skip_cache, **options)
                          for b, columns in zip(model.blocks, self.columns))
            lower = sum(b.mass*r.bounds.lower for b, r in zip(model.blocks, black))
            if lower >= self.lower:
                self.lower, self.lower_strategy = lower, strategy
            if self.upper-model.missing_mass-self.lower <= epsilon:
                # A full black response already proves the represented mass
                # safe up to the existing global utility bound. Scanning all
                # red plans cannot improve that bound or remove missing mass.
                red = InformationResponse(None, RationalInterval(0, 1), RationalInterval(0, 1), (),
                                           0, model.row_count, False, False, "utility_range_bound")
            else:
                red = red_information_response(model, strategy, work, preferred=self.rows,
                                               candidate_limit=response_candidate_limit, **options)
            upper = red.bounds.upper
            if upper <= self.upper:
                self.upper, self.upper_strategy = upper, strategy
            if self.lower > self.upper:
                raise RuntimeError("information-set global bounds are inconsistent")
            self.responses_complete = red.complete and all(r.complete for r in black)
            add_row = red.action is not None and red.action not in self.rows
            additions = tuple(r.action is not None and r.action not in columns for r, columns in zip(black, self.columns))
            trace.append(InformationOracleIteration(number, len(self.rows), tuple(map(len, self.columns)), solved.bounds,
                         RationalInterval(self.lower, self.upper), red, black, add_row, additions))
            if self.upper-self.lower <= epsilon:
                reason = "proven_optimal" if self.upper == self.lower else "proven_epsilon"
                break
            # The missing mass alone prevents closure. Avoid adding equal-value
            # root plans after the represented game's bounds already meet.
            if model.missing_mass and self.upper-model.missing_mass-self.lower <= epsilon:
                reason = "unrepresented_mass"
                break
            if work.exhausted():
                reason = "/".join(sorted(work.reasons))
                break
            if add_row:
                self.rows.append(red.action)
            for columns, response, add in zip(self.columns, black, additions):
                if add:
                    columns.append(response.action)
            if not add_row and not any(additions):
                incomplete = [r.stop_reason for r in (red, *black) if r.stop_reason not in {"complete_domain", "proven_extreme"}]
                reason = incomplete[0] if incomplete else "incomplete_best_response"
                break
        full = model.action_domain_complete and model.belief_domain_complete and not model.missing_mass
        if not full and reason in {"proven_optimal", "proven_epsilon"}:
            reason = "finite_model_only"
        return InformationOracleResult(RationalInterval(self.lower, self.upper), self.lower_strategy, self.upper_strategy,
            epsilon, bool(full and self.lower == self.upper), bool(full and self.upper-self.lower <= epsilon),
            model.belief_domain_complete, model.action_domain_complete, self.responses_complete,
            len(self.rows), tuple(map(len, self.columns)), tuple(trace), reason,
            work.nodes-start_nodes, work.transitions-start_edges, perf_counter()-started,
            "FS/full-root-information-responses/observable-frozen-extensions/"+model.scope, self.skip_cache.stats())
