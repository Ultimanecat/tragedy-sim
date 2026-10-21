"""Full physical root domains against immutable information-set strategies.

Red optimizes ONE policy across types/faces. Black chooses a face bundle before
red's private draw; only post-reveal abilities respond to the revealed draw.
Unknown candidates keep [0,1], and fixed behavior is extended legally outside
the restricted tree. No per-world red skill optimization is averaged.
"""

from dataclasses import dataclass
from fractions import Fraction as Q
from itertools import chain

from .frozen_information import FrozenBehavior, FrozenInformationStrategy
from .information_game import _Builder, _key, _remember, column_identity
from .engine_game import red_commands
from .fair_engine import FixedPolicyDayGame, HistoryDayGame
from .matrix import MatrixLimit
from .pure import commit_pair
from .sequence_form import Chance, behavioral_policy, sequence_best_response
from .zero_sum import RationalInterval, SearchBudget


@dataclass(frozen=True)
class CandidateValue:
    bounds: RationalInterval
    behavior: tuple = ()


@dataclass(frozen=True)
class InformationResponse:
    action: object
    bounds: RationalInterval
    action_bounds: RationalInterval
    behavior: tuple
    checked: int
    domain_size: int
    domain_exhausted: bool
    complete: bool
    stop_reason: str


def _deadline(work):
    return None if work.time_limit_ms is None else work.started+work.time_limit_ms/1000


def _root_parts(block, column):
    if isinstance(block.game, HistoryDayGame):
        return block.game.variants[column[0]]._root, column[1]
    return block.game._root, column


class BlackSkipCache:
    """Audited exact fast path for the EMPTY next-first red behavior table.

    The concrete public skip-v2 policy is identical at every legal menu. Its
    existing scalar day cache is therefore reusable here. A learned policy,
    a subclass, or any nonempty table uses the full information tree instead.
    This cache is scoped to one immutable root model, never a mutable game.
    """
    def __init__(self):
        self.models = {}
        self.evaluations = 0

    @staticmethod
    def supports(policy):
        return type(policy) is FrozenBehavior and policy.player == "red" and not policy.table

    def evaluate(self, block, row, column, work, *, max_depth):
        root, faces = _root_parts(block, column)
        key = id(root), max_depth
        if key not in self.models:
            self.models[key] = FixedPolicyDayGame(root, backend="cached", max_depth=max_depth)
        work.nodes += 1
        work.transitions += len(row)
        self.evaluations += 1
        return self.models[key].evaluate(row, faces, SearchBudget(work=work))

    def stats(self):
        return dict(roots=len(self.models), evaluations=self.evaluations,
                    hits=sum(m.continuation.stats.hits for m in self.models.values()),
                    entries=sum(len(m.continuation.values) for m in self.models.values()))


def _committed(block, row, column, work):
    root, faces = _root_parts(block, column)
    work.nodes += 1
    after = commit_pair(root, red_commands(row), faces)
    work.transitions += len(row)
    recall = (_remember("", "r/root-cards", _key(red_commands(row))),
              _remember("", "m/root-faces/"+block.label, column_identity(column)))
    return after, (root.state.loop, root.state.round), recall


def _solve_response_tree(builder, lower, upper, player):
    tree = builder.finish(lower, upper, root_complete=True, belief_complete=False)
    low = sequence_best_response(tree.lower, player, (Q(1),), deadline=_deadline(builder.work))
    high = (low if tree.upper is tree.lower else
            sequence_best_response(tree.upper, player, (Q(1),), deadline=_deadline(builder.work)))
    # Maximizer's lower policy guarantees the lower value; minimizer's upper
    # policy attains an upper bound. Both are legal complete policy extensions.
    policy_model, policy_solution = ((tree.lower, low) if player == "red" else (tree.upper, high))
    form = policy_model.red if player == "red" else policy_model.black
    behavior = behavioral_policy(form, policy_solution.realization)
    return CandidateValue(RationalInterval(low.value, high.value), behavior)


def red_candidate_value(model, row, strategy, work, *, max_depth=128, tree_node_limit=10000,
                          range_analyzer=None, range_compression=True, range_probe_nodes=256,
                          boundary_evaluator=None):
    if not model.contains_row(row):
        raise ValueError("illegal common red response")
    black_cards = dict(strategy.black_cards)
    if set(black_cards) != {b.label for b in model.blocks}:
        raise ValueError("frozen black strategy belongs to a different type domain")
    builder = _Builder(work=work, max_depth=max_depth, tree_node_limit=tree_node_limit,
                       fixed_behavior=strategy.black_policy, range_analyzer=range_analyzer,
                       range_compression=range_compression, range_probe_nodes=range_probe_nodes,
                       boundary_evaluator=boundary_evaluator)
    builder.account()  # nature over types and the fixed conditional black draw
    lower, upper = [], []
    for block in model.blocks:
        for column, probability in black_cards[block.label]:
            if not block.game.contains_column(column):
                raise ValueError("frozen black root strategy contains an illegal column")
            if work.exhausted():
                lo, hi = builder.unknown_leaf("/".join(sorted(work.reasons)))
            else:
                after, position, recall = _committed(block, row, column, work)
                lo, hi = builder.visit(after, position, recall)
            mass = block.mass*probability
            lower.append((mass, lo))
            upper.append((mass, hi))
    if model.missing_mass:
        lo, hi = builder.unknown_leaf("unrepresented_mass")
        lower.append((model.missing_mass, lo))
        upper.append((model.missing_mass, hi))
    return _solve_response_tree(builder, Chance(tuple(lower)), Chance(tuple(upper)), "red")


def black_candidate_value(block, column, strategy, work, *, max_depth=128, tree_node_limit=10000, skip_cache=None,
                           range_analyzer=None, range_compression=True, range_probe_nodes=256,
                           boundary_evaluator=None):
    if not block.game.contains_column(column) or any(not block.game.contains_row(row) for row, _ in strategy.red_cards):
        raise ValueError("illegal black column or frozen red root strategy")
    if boundary_evaluator is not None and getattr(boundary_evaluator, "version", "") != "day-survival-v1":
        # The empty-policy fast path is scoped to day-survival-v1.
        skip_cache = None
    lower, upper = Q(0), Q(0)
    for row, probability in strategy.red_cards:
        if work.exhausted():
            upper += probability
            continue
        if skip_cache is not None and skip_cache.supports(strategy.red_policy):
            cell = skip_cache.evaluate(block, row, column, work, max_depth=max_depth)
            lower += probability*cell.lower
            upper += probability*cell.upper
            continue
        builder = _Builder(work=work, max_depth=max_depth, tree_node_limit=tree_node_limit,
                           fixed_behavior=strategy.red_policy, range_analyzer=range_analyzer,
                           range_compression=range_compression, range_probe_nodes=range_probe_nodes,
                           boundary_evaluator=boundary_evaluator)
        after, position, recall = _committed(block, row, column, work)
        lo, hi = builder.visit(after, position, recall)
        cell = _solve_response_tree(builder, lo, hi, "black").bounds
        lower += probability*cell.lower
        upper += probability*cell.upper
    # Post-reveal black choices may distinguish these root rows, since the
    # native reveal is forced before any nontrivial ability decision. The
    # root column above is fixed across the entire private red draw.
    return CandidateValue(RationalInterval(lower, upper))


def _scan(domain, size, contains, evaluate, work, maximize, preferred=(), candidate_limit=None):
    if candidate_limit is not None and (type(candidate_limit) is not int or candidate_limit < 1):
        raise ValueError("candidate limit must be positive or None")
    preferred = tuple(preferred)
    if any(not contains(a) for a in preferred):
        raise ValueError("preferred response must belong to the complete domain")
    seen, checked, chosen, behavior = set(), 0, None, ()
    lower, upper = (Q(0), Q(0)) if maximize else (Q(1), Q(1))
    action_bounds, best = RationalInterval(0, 1), Q(-1) if maximize else Q(2)
    reason = "complete_domain"
    for action in chain(preferred, domain):
        if action in seen:
            continue
        if work.exhausted():
            reason = "/".join(sorted(work.reasons))
            break
        if candidate_limit is not None and checked >= candidate_limit:
            reason = "candidate_limit"
            break
        seen.add(action)
        try:
            result = evaluate(action)
        except MatrixLimit as error:
            reason = error.reason
            break
        checked += 1
        lower = (max if maximize else min)(lower, result.bounds.lower)
        upper = (max if maximize else min)(upper, result.bounds.upper)
        criterion = result.bounds.lower if maximize else result.bounds.upper
        if (criterion > best if maximize else criterion < best):
            chosen, best, action_bounds, behavior = action, criterion, result.bounds, result.behavior
        if (lower == 1 if maximize else upper == 0):
            reason = "proven_extreme"
            break
    exhausted = checked == size
    if not exhausted:
        if maximize:
            upper = Q(1)
        else:
            lower = Q(0)
    # A proven utility extremum also certifies the unvisited part.
    if maximize and lower == 1:
        upper = Q(1)
    if not maximize and upper == 0:
        lower = Q(0)
    return InformationResponse(chosen, RationalInterval(lower, upper), action_bounds, behavior,
                               checked, size, exhausted, lower == upper, reason)


def red_information_response(model, strategy, work, *, preferred=(), candidate_limit=None, **tree_options):
    if not isinstance(strategy, FrozenInformationStrategy):
        raise ValueError("a frozen complete strategy is required")
    return _scan(model.rows(), model.row_count, model.contains_row,
        lambda row: red_candidate_value(model, row, strategy, work, **tree_options), work, True, preferred, candidate_limit)


def black_information_response(block, strategy, work, *, preferred=(), candidate_limit=None, skip_cache=None, **tree_options):
    if not isinstance(strategy, FrozenInformationStrategy):
        raise ValueError("a frozen complete strategy is required")
    skip_cache = BlackSkipCache() if skip_cache is None else skip_cache
    return _scan(block.game.columns(), block.game.column_count, block.game.contains_column,
        lambda column: black_candidate_value(block, column, strategy, work, skip_cache=skip_cache, **tree_options), work, False,
        preferred, candidate_limit)
