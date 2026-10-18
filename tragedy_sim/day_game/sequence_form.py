"""Exact perfect-recall extensive zero-sum games, without pure-policy products.

Tree validation builds realization flows. A positive-terminal-payoff
homogeneous LP has a feasible origin, reusing our rational slack simplex.
Returned flows and both original sequence-form saddle inequalities are
independently checked. Scope is the supplied finite tree, not omitted actions.
"""

from dataclasses import dataclass
from fractions import Fraction as Q
from math import isfinite
from time import perf_counter

from .matrix import MatrixLimit, rational, solve_nonnegative_lp


@dataclass(frozen=True)
class Terminal:
    value: object


@dataclass(frozen=True)
class Chance:
    outcomes: tuple  # (strictly positive probability, child)


@dataclass(frozen=True)
class Decision:
    player: str  # red maximizes; black minimizes
    information: str
    actions: tuple  # (action identity, child)


@dataclass(frozen=True)
class InformationSet:
    key: str
    parent: int
    actions: tuple
    sequences: tuple


@dataclass(frozen=True)
class PlayerForm:
    sequences: tuple  # empty sequence at index 0, then (parent, info, action)
    information_sets: tuple

    def flow(self):
        rows = [[Q(i == 0) for i in range(len(self.sequences))]]
        for info in self.information_sets:
            row = [Q(0)]*len(self.sequences)
            row[info.parent] = -1
            for index in info.sequences:
                row[index] = 1
            rows.append(row)
        return tuple(tuple(row) for row in rows)


@dataclass(frozen=True)
class SequenceGame:
    red: PlayerForm
    black: PlayerForm
    leaves: tuple  # (red sequence, black sequence, nature probability, utility)
    nodes: int

    def payoffs(self, shift=Q(0)):
        matrix = [[Q(0)]*len(self.black.sequences) for _ in self.red.sequences]
        for red, black, mass, value in self.leaves:
            matrix[red][black] += mass*(value+shift)
        return tuple(tuple(row) for row in matrix)


def build_sequence_game(root, *, node_limit=10000, max_depth=256, cell_limit=1000000, deadline=None):
    for limit in (node_limit, max_depth, cell_limit):
        if type(limit) is not int or limit < 1:
            raise ValueError("sequence tree budgets must be positive integers")
    if deadline is not None and (type(deadline) not in {int, float} or not isfinite(deadline)):
        raise ValueError("deadline must be a finite monotonic-clock value")
    sequences = {p: [(None, None, None)] for p in ("red", "black")}
    infos = {p: {} for p in sequences}
    leaves, path, nodes = [], set(), 0

    def visit(node, red, black, mass, depth):
        nonlocal nodes
        if deadline is not None and perf_counter() >= deadline:
            raise MatrixLimit("time_limit")
        if nodes >= node_limit:
            raise MatrixLimit("tree_node_limit")
        if depth > max_depth:
            raise MatrixLimit("tree_depth_limit")
        if id(node) in path:
            raise ValueError("cyclic extensive game")
        nodes += 1
        path.add(id(node))
        if type(node) is Terminal:
            leaves.append((red, black, mass, rational(node.value)))
        elif type(node) is Chance:
            if not isinstance(node.outcomes, tuple) or not node.outcomes:
                raise ValueError("chance needs nonempty probability/child pairs")
            try:
                outcomes = tuple((rational(p), child) for p, child in node.outcomes)
            except (TypeError, ValueError) as error:
                raise ValueError("invalid chance outcomes") from error
            if any(p <= 0 for p, _ in outcomes) or sum(p for p, _ in outcomes) != 1:
                raise ValueError("chance probabilities must be positive and sum to one")
            for p, child in outcomes:
                visit(child, red, black, mass*p, depth+1)
        elif type(node) is Decision:
            if type(node.player) is not str or node.player not in sequences or type(node.information) is not str or not node.information:
                raise ValueError("decision needs a player and a nonempty information identity")
            if not isinstance(node.actions, tuple) or not node.actions:
                raise ValueError("decision needs nonempty action/child pairs")
            try:
                names = tuple(name for name, _ in node.actions)
            except (TypeError, ValueError) as error:
                raise ValueError("invalid decision actions") from error
            if any(type(name) is not str or not name for name in names) or len(set(names)) != len(names):
                raise ValueError("action identities must be nonempty and distinct")
            parent = red if node.player == "red" else black
            old = infos[node.player].get(node.information)
            if old is None:
                start = len(sequences[node.player])
                old = InformationSet(node.information, parent, names, tuple(range(start, start+len(names))))
                infos[node.player][node.information] = old
                sequences[node.player].extend((parent, node.information, action) for action in names)
                if len(sequences["red"])*len(sequences["black"]) > cell_limit:
                    raise MatrixLimit("sequence_cell_limit")
            elif old.parent != parent:
                raise ValueError("information set violates perfect recall")
            elif set(old.actions) != set(names):
                raise ValueError("information set has inconsistent legal actions")
            by_action = dict(zip(old.actions, old.sequences))
            for action, child in node.actions:
                next_red = by_action[action] if node.player == "red" else red
                next_black = by_action[action] if node.player == "black" else black
                visit(child, next_red, next_black, mass, depth+1)
        else:
            raise ValueError("unrecognized extensive-game node")
        path.remove(id(node))

    visit(root, 0, 0, Q(1), 0)
    forms = [PlayerForm(tuple(sequences[p]), tuple(infos[p].values())) for p in ("red", "black")]
    return SequenceGame(*forms, tuple(leaves), nodes)


@dataclass(frozen=True)
class SequenceSolution:
    red: tuple
    black: tuple
    value: Q
    shift: Q
    red_upper_potential: tuple
    black_lower_potential: tuple
    pivots: int
    lp_constraints: int
    lp_variables: int
    numeric_error_bound: Q = Q(0)


def _flow_check(form, realization):
    if len(realization) != len(form.sequences) or any(type(x) is not Q or x < 0 for x in realization):
        raise ValueError("invalid nonnegative realization vector")
    if realization[0] != 1 or any(sum(realization[i] for i in info.sequences) != realization[info.parent]
                                  for info in form.information_sets):
        raise ValueError("realization flow is not normalized")


def verify_sequence_solution(game, solution):
    _flow_check(game.red, solution.red)
    _flow_check(game.black, solution.black)
    minimum = min(value for _, _, _, value in game.leaves)
    shift = 1-minimum if minimum <= 0 else Q(0)
    e, f = game.red.flow(), game.black.flow()
    u, v = solution.red_upper_potential, solution.black_lower_potential
    if (len(u) != len(e) or len(v) != len(f) or any(type(x) is not Q for x in (*u, *v))
            or type(solution.value) is not Q or solution.shift != shift or solution.numeric_error_bound != 0):
        raise ValueError("invalid sequence-form saddle certificate")
    matrix = game.payoffs(shift)
    upper = tuple(sum(a*y for a, y in zip(row, solution.black)) for row in matrix)
    lower = tuple(sum(solution.red[i]*matrix[i][j] for i in range(len(matrix))) for j in range(len(matrix[0])))
    if (any(upper[j] > sum(row[j]*price for row, price in zip(e, u)) for j in range(len(upper)))
            or any(lower[j] < sum(row[j]*price for row, price in zip(f, v)) for j in range(len(lower)))
            or u[0] != solution.value+shift or v[0] != solution.value+shift
            or sum(solution.red[i]*upper[i] for i in range(len(upper))) != solution.value+shift
            or sum(mass*value*solution.red[r]*solution.black[b] for r, b, mass, value in game.leaves) != solution.value):
        raise ValueError("sequence-form primal/dual saddle inequalities failed")
    return True


def solve_sequence_game(game, *, pivot_limit=100000, deadline=None, lp_cell_limit=2000000):
    if type(game) is not SequenceGame or type(lp_cell_limit) is not int or lp_cell_limit < 1:
        raise ValueError("a validated sequence game and positive LP cell cap are required")
    if deadline is not None and (type(deadline) not in {int, float} or not isfinite(deadline)):
        raise ValueError("deadline must be a finite monotonic-clock value")
    if deadline is not None and perf_counter() >= deadline:
        raise MatrixLimit("time_limit")
    nr, nb = len(game.red.sequences), len(game.black.sequences)
    er, fb = len(game.red.information_sets)+1, len(game.black.information_sets)+1
    constraints, variables = nr+2*fb+1, nb+1+2*er
    if (constraints+1)*(variables+constraints+1) > lp_cell_limit:
        raise MatrixLimit("sequence_lp_cell_limit")
    e, f = game.red.flow(), game.black.flow()
    minimum = min(value for _, _, _, value in game.leaves)
    shift = 1-minimum if minimum <= 0 else Q(0)
    matrix = game.payoffs(shift)
    # z=t*y; E' w >= Bz; Fz=t*f; e'w<=1; maximize t.
    # w is free, represented by w+ - w-. All RHS except the
    # final budget are zero, so the slack origin is feasible.
    coefficients = [list(matrix[j])+[0]+[-row[j] for row in e]+[row[j] for row in e] for j in range(nr)]
    for k, row in enumerate(f):
        equality = list(row)+[-int(k == 0)]+[0]*(2*er)
        coefficients.extend((equality, [-a for a in equality]))
    coefficients.append([0]*(nb+1)+[int(k == 0) for k in range(er)]+[-int(k == 0) for k in range(er)])
    solved = solve_nonnegative_lp(coefficients, [0]*(constraints-1)+[1], [0]*nb+[1]+[0]*(2*er),
                                  pivot_limit=pivot_limit, deadline=deadline)
    t = solved.primal[nb]
    if t <= 0 or solved.dual[-1] != t:
        raise RuntimeError("inconsistent positive sequence-game packing objectives")
    solution = SequenceSolution(tuple(v/t for v in solved.dual[:nr]), tuple(v/t for v in solved.primal[:nb]),
        1/t-shift, shift,
        tuple((solved.primal[nb+1+k]-solved.primal[nb+1+er+k])/t for k in range(er)),
        tuple(-(solved.dual[nr+2*k]-solved.dual[nr+2*k+1])/t for k in range(fb)),
        solved.pivots, constraints, variables)
    verify_sequence_solution(game, solution)
    return solution


def behavioral_policy(form, realization):
    """Legal conditional choices; unreachable own sequences use uniform play."""
    _flow_check(form, realization)
    return tuple((info.key, tuple((action, realization[index]/realization[info.parent]
                                  if realization[info.parent] else Q(1, len(info.actions)))
                                 for action, index in zip(info.actions, info.sequences)))
                 for info in form.information_sets)


@dataclass(frozen=True)
class SequenceBestResponse:
    value: Q
    realization: tuple
    potential: tuple


def sequence_best_response(game, player, opponent, *, deadline=None):
    """Sparse sequence-flow DP against a FROZEN opponent realization.

    Opponent/nature reach coefficients are independent of our own realization.
    Each own information set chooses one child; multiple information sets with
    the same parent add their counterfactual values. No policy product or LP.
    An independent sparse flow/dual certificate is checked before returning.
    """
    if player not in {"red", "black"} or type(game) is not SequenceGame:
        raise ValueError("a sequence game and valid response player are required")
    if deadline is not None and (type(deadline) not in {int, float} or not isfinite(deadline)):
        raise ValueError("deadline must be a finite monotonic-clock value")

    def check_time():
        if deadline is not None and perf_counter() >= deadline:
            raise MatrixLimit("time_limit")

    check_time()
    form, other = (game.red, game.black) if player == "red" else (game.black, game.red)
    _flow_check(other, opponent)
    coefficients = [Q(0)]*len(form.sequences)
    for red, black, mass, utility in game.leaves:
        check_time()
        own, opposing = (red, black) if player == "red" else (black, red)
        coefficients[own] += mass*utility*opponent[opposing]
    children = [[] for _ in form.sequences]
    for index, info in enumerate(form.information_sets):
        children[info.parent].append(index)
    values, choices, prices = list(coefficients), {}, [Q(0)]*(len(form.information_sets)+1)
    for parent in reversed(range(len(values))):
        check_time()
        for index in children[parent]:
            info = form.information_sets[index]
            choice = (max if player == "red" else min)(info.sequences, key=lambda s: values[s])
            choices[index] = choice
            prices[index+1] = values[choice]
            values[parent] += values[choice]
    realization = [Q(0)]*len(values)
    realization[0], prices[0] = Q(1), values[0]
    for index, info in enumerate(form.information_sets):
        realization[choices[index]] = realization[info.parent]
    _flow_check(form, realization)
    dual = [Q(0)]*len(values)
    dual[0] = prices[0]
    for info, price in zip(form.information_sets, prices[1:]):
        dual[info.parent] -= price
        for sequence in info.sequences:
            dual[sequence] += price
    if (any((d < c if player == "red" else d > c) for d, c in zip(dual, coefficients))
            or sum(x*c for x, c in zip(realization, coefficients)) != values[0]):
        raise RuntimeError("sequence best response failed original sparse flow/dual checks")
    check_time()
    return SequenceBestResponse(values[0], tuple(realization), tuple(prices))
