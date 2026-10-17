"""Exact finite zero-sum matrix games using a rational packing-LP tableau.

The maximizing player chooses rows; the minimizing player chooses columns.
The result is independently checked against every original matrix inequality.
This small restricted-game solver does not certify an omitted action domain.
"""

from dataclasses import dataclass
from fractions import Fraction
from math import isfinite
from time import perf_counter


def rational(value):
    if type(value) is int or isinstance(value, Fraction):
        return Fraction(value)
    if type(value) is float and isfinite(value):
        return Fraction(str(value))
    if type(value) is str:
        try:
            return Fraction(value)
        except (ValueError, ZeroDivisionError) as error:
            raise ValueError("invalid rational value") from error
    raise ValueError("expected an integer, finite decimal, fraction or rational string")


def matrix_values(matrix):
    if isinstance(matrix, (str, bytes)):
        raise ValueError("payoff matrix must contain numeric rows")
    try:
        rows = tuple(matrix)
        if any(isinstance(row, (str, bytes)) for row in rows):
            raise ValueError("payoff rows must be numeric sequences")
        result = tuple(tuple(rational(v) for v in row) for row in rows)
    except TypeError as error:
        raise ValueError("payoff matrix must contain numeric rows") from error
    if not result or not result[0] or any(len(row) != len(result[0]) for row in result):
        raise ValueError("payoff matrix must be nonempty and rectangular")
    return result


class MatrixLimit(RuntimeError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class MatrixSolution:
    red: tuple[Fraction, ...]
    black: tuple[Fraction, ...]
    value: Fraction
    pivots: int
    numeric_error_bound: Fraction = Fraction(0)


def verify_matrix_solution(matrix, solution):
    """Exact primal/dual feasibility and a common saddle-point value."""
    values = matrix_values(matrix)
    rows, cols = len(values), len(values[0])
    if (len(solution.red) != rows or len(solution.black) != cols
            or any(type(p) is not Fraction or p < 0 for p in (*solution.red, *solution.black))
            or sum(solution.red) != 1 or sum(solution.black) != 1):
        raise ValueError("invalid mixed probability vectors")
    if type(solution.value) is not Fraction or solution.numeric_error_bound != 0:
        raise ValueError("exact matrix certificate requires a rational value and zero error")
    if any(sum(solution.red[i] * values[i][j] for i in range(rows)) < solution.value for j in range(cols)):
        raise ValueError("red strategy violates a column guarantee")
    if any(sum(values[i][j] * solution.black[j] for j in range(cols)) > solution.value for i in range(rows)):
        raise ValueError("black strategy violates a row guarantee")
    return True


@dataclass(frozen=True)
class LinearSolution:
    primal: tuple[Fraction, ...]
    dual: tuple[Fraction, ...]
    value: Fraction
    pivots: int


def solve_nonnegative_lp(matrix, rhs, objective, *, pivot_limit=100000, deadline=None):
    """Exact max c'x subject to Mx<=rhs, x>=0, with rhs>=0.

    A feasible slack start includes zero-RHS/degenerate constraints. Bland's
    rule prevents cycling. This helper deliberately has no phase-I solver.
    Every returned solution passes original primal/dual feasibility checks.
    """
    if type(pivot_limit) is not int or pivot_limit < 1:
        raise ValueError("pivot_limit must be a positive integer")
    if deadline is not None and (type(deadline) not in {int, float} or not isfinite(deadline)):
        raise ValueError("deadline must be a finite monotonic-clock value")

    def check_time():
        if deadline is not None and perf_counter() >= deadline:
            raise MatrixLimit("time_limit")

    check_time()
    values = matrix_values(matrix)
    m, n = len(values), len(values[0])
    try:
        rhs, objective = tuple(map(rational, rhs)), tuple(map(rational, objective))
    except TypeError as error:
        raise ValueError("LP rhs and objective must be numeric sequences") from error
    if len(rhs) != m or len(objective) != n or any(v < 0 for v in rhs):
        raise ValueError("LP dimensions must match and rhs must be nonnegative")
    table = []
    for i, row in enumerate(values):
        check_time()
        table.append(list(row) + [Fraction(i == k) for k in range(m)] + [rhs[i]])
    table.append([-v for v in objective] + [Fraction(0)] * (m + 1))
    basis, pivots = list(range(n, n + m)), 0
    while True:
        check_time()
        entering = next((j for j in range(n + m) if table[-1][j] < 0), None)
        if entering is None:
            break
        if pivots >= pivot_limit:
            raise MatrixLimit("pivot_limit")
        candidates = [i for i in range(m) if table[i][entering] > 0]
        if not candidates:
            raise ValueError("linear program is unbounded")
        leaving = min(candidates, key=lambda i: (table[i][-1] / table[i][entering], basis[i]))
        divisor = table[leaving][entering]
        pivot = [v / divisor for v in table[leaving]]
        table[leaving] = pivot
        for i in range(m + 1):
            if i != leaving and table[i][entering]:
                factor = table[i][entering]
                table[i] = [v - factor * p for v, p in zip(table[i], pivot)]
        basis[leaving] = entering
        pivots += 1
    primal = [Fraction(0)] * n
    for i, variable in enumerate(basis):
        if variable < n:
            primal[variable] = table[i][-1]
    dual = table[-1][n:n + m]
    value = sum(c*x for c, x in zip(objective, primal))
    if (any(x < 0 for x in primal) or any(y < 0 for y in dual)
            or any(sum(a*x for a, x in zip(row, primal)) > b for row, b in zip(values, rhs))
            or any(sum(dual[i]*values[i][j] for i in range(m)) < objective[j] for j in range(n))
            or value != sum(b*y for b, y in zip(rhs, dual)) or value != table[-1][-1]):
        raise RuntimeError("inconsistent exact primal/dual LP solution")
    check_time()
    return LinearSolution(tuple(primal), tuple(dual), value, pivots)


def solve_matrix(matrix, *, pivot_limit=100000, deadline=None):
    """Positive packing reduction; original matrix certificate is rechecked."""
    values = matrix_values(matrix)
    m, n = len(values), len(values[0])
    minimum = min(min(row) for row in values)
    shift = 1 - minimum if minimum <= 0 else Fraction(0)
    packed = solve_nonnegative_lp(tuple(tuple(v + shift for v in row) for row in values),
                                  [1]*m, [1]*n, pivot_limit=pivot_limit, deadline=deadline)
    column_scaled, row_scaled = packed.primal, packed.dual
    total = sum(column_scaled)
    if total <= 0 or total != sum(row_scaled) or total != packed.value:
        raise RuntimeError("inconsistent primal/dual packing objectives")
    solution = MatrixSolution(tuple(v / total for v in row_scaled), tuple(v / total for v in column_scaled),
                              1 / total - shift, packed.pivots)
    verify_matrix_solution(values, solution)
    return solution
