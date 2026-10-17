"""Exact one-sided-type game: one common red distribution, black per type.

Restricted blocks have a common row domain and separate column domains.
The LP has R+2H constraints and 1+sum(C_h) variables, without a product of
black type-contingent policies. An exact feasible-slack reduction avoids
phase I, at the cost of two degenerate constraints per type.
"""

from dataclasses import dataclass
from fractions import Fraction

from .matrix import matrix_values, rational, solve_nonnegative_lp


def block_values(blocks, weights):
    try:
        blocks = tuple(matrix_values(block) for block in blocks)
        weights = tuple(map(rational, weights))
    except TypeError as error:
        raise ValueError("blocks and weights must be sequences") from error
    if (not blocks or len(blocks) != len(weights) or any(p <= 0 for p in weights)
            or sum(weights) != 1 or any(len(b) != len(blocks[0]) for b in blocks)):
        raise ValueError("blocks need common rows and positive weights summing to one")
    return blocks, weights


@dataclass(frozen=True)
class BayesianMatrixSolution:
    red: tuple[Fraction, ...]
    black: tuple[tuple[Fraction, ...], ...]
    value: Fraction
    pivots: int
    lp_constraints: int
    lp_variables: int
    numeric_error_bound: Fraction = Fraction(0)


def verify_bayesian_matrix(blocks, weights, solution):
    blocks, weights = block_values(blocks, weights)
    rows = len(blocks[0])
    if (len(solution.red) != rows or len(solution.black) != len(blocks)
            or any(type(p) is not Fraction or p < 0 for p in solution.red)
            or sum(solution.red) != 1):
        raise ValueError("invalid common red distribution")
    for block, policy in zip(blocks, solution.black):
        if (len(policy) != len(block[0]) or sum(policy) != 1
                or any(type(p) is not Fraction or p < 0 for p in policy)):
            raise ValueError("invalid conditional black distribution")
    lower = sum(p * min(sum(solution.red[i]*block[i][j] for i in range(rows))
                        for j in range(len(block[0]))) for p, block in zip(weights, blocks))
    upper = max(sum(p * sum(q*block[i][j] for j, q in enumerate(policy))
                    for p, block, policy in zip(weights, blocks, solution.black)) for i in range(rows))
    if (type(solution.value) is not Fraction or solution.numeric_error_bound != 0
            or lower != solution.value or upper != solution.value):
        raise ValueError("invalid Bayesian matrix saddle-point certificate")
    return True


def solve_bayesian_matrix(blocks, weights, *, pivot_limit=100000, deadline=None):
    blocks, weights = block_values(blocks, weights)
    row_count, type_count = len(blocks[0]), len(blocks)
    sizes = tuple(len(block[0]) for block in blocks)
    columns = sum(sizes)
    minimum = min(v for block in blocks for row in block for v in row)
    shift = 1 - minimum if minimum <= 0 else Fraction(0)
    # max t; sum_h,b p_h B_h[r,b] z_hb <= 1;
    # sum_b z_hb = t for every h; z,t >= 0.
    coefficients = [[p*(v+shift) for p, block in zip(weights, blocks) for v in block[i]] + [0]
                    for i in range(row_count)]
    offset = 0
    for size in sizes:
        equality = [Fraction(offset <= j < offset+size) for j in range(columns)] + [Fraction(-1)]
        coefficients.extend((equality, [-v for v in equality]))
        offset += size
    solved = solve_nonnegative_lp(coefficients, [1]*row_count + [0]*(2*type_count), [0]*columns + [1],
                                  pivot_limit=pivot_limit, deadline=deadline)
    t = solved.primal[-1]
    if t <= 0:
        raise RuntimeError("positive Bayesian game has a nonpositive packing solution")
    red = tuple(v/t for v in solved.dual[:row_count])
    black, offset = [], 0
    for size in sizes:
        black.append(tuple(v/t for v in solved.primal[offset:offset+size]))
        offset += size
    result = BayesianMatrixSolution(red, tuple(black), 1/t-shift, solved.pivots,
                                    row_count+2*type_count, columns+1)
    verify_bayesian_matrix(blocks, weights, result)
    return result
