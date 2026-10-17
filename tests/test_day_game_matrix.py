"""Rational saddle certificates versus independent vertex enumeration."""

from dataclasses import replace
from fractions import Fraction as Q
from itertools import combinations
import random
from time import perf_counter
import unittest

from tragedy_sim.day_game.matrix import (MatrixLimit, MatrixSolution, rational,
                                         solve_matrix, verify_matrix_solution)


def gaussian(matrix, rhs):
    n = len(rhs)
    work = [[Q(x) for x in row] + [Q(b)] for row, b in zip(matrix, rhs)]
    for j in range(n):
        pivot = next((i for i in range(j, n) if work[i][j]), None)
        if pivot is None:
            return None
        work[j], work[pivot] = work[pivot], work[j]
        scale = work[j][j]
        work[j] = [v / scale for v in work[j]]
        for i in range(n):
            if i != j:
                scale = work[i][j]
                work[i] = [v - scale * p for v, p in zip(work[i], work[j])]
    return [row[-1] for row in work]


def vertex_value(matrix):
    """Enumerate primal vertices in (p_0,...,p_m-1,v), without simplex."""
    m, n = len(matrix), len(matrix[0])
    constraints = [[Q(i == j) for i in range(m)] + [Q(0)] for j in range(m)]
    constraints += [[Q(matrix[i][j]) for i in range(m)] + [Q(-1)] for j in range(n)]
    best = None
    for active in combinations(range(m + n), m):
        solution = gaussian([[Q(1)] * m + [Q(0)]] + [constraints[i] for i in active], [1] + [0] * m)
        if solution is None or any(p < 0 for p in solution[:-1]):
            continue
        value = solution[-1]
        if any(sum(Q(matrix[i][j]) * solution[i] for i in range(m)) < value for j in range(n)):
            continue
        best = value if best is None else max(best, value)
    if best is None:
        raise AssertionError("independent vertex enumeration found no optimum")
    return best


class ExactMatrixTests(unittest.TestCase):
    def test_matching_game_pure_zero_mixed_half(self):
        matrix = ((1, 0), (0, 1))
        self.assertEqual(max(min(row) for row in matrix), 0)
        solved = solve_matrix(matrix)
        self.assertEqual(solved.red, (Q(1, 2), Q(1, 2)))
        self.assertEqual(solved.black, solved.red)
        self.assertEqual(solved.value, Q(1, 2))
        self.assertEqual(solved.numeric_error_bound, 0)

    def test_negative_rectangular_degenerate_and_fractional_cases(self):
        cases = (((-2,),), ((0, 0, 0), (0, 0, 0)), ((1, 1),),
                 ((0, -1, 1), (1, 0, -1), (-1, 1, 0)),
                 ((Q(1, 3), Q(2, 3)), (Q(5, 7), Q(1, 7))),
                 ((2, 0, 2), (0, 2, 0), (0, 2, 0)))
        for matrix in cases:
            with self.subTest(matrix=matrix):
                solved = solve_matrix(matrix)
                self.assertEqual(solved.value, vertex_value(matrix))
                self.assertTrue(verify_matrix_solution(matrix, solved))

    def test_fixed_seeds_match_independent_primal_and_dual_vertices(self):
        for seed in range(10):
            rng = random.Random(seed)
            for m, n in ((2, 3), (3, 2), (3, 3), (4, 4)):
                matrix = tuple(tuple(rng.randrange(-2, 4) for _ in range(n)) for _ in range(m))
                solved = solve_matrix(matrix)
                self.assertEqual(solved.value, vertex_value(matrix), (seed, m, n))
                negative_transpose = tuple(tuple(-matrix[i][j] for i in range(m)) for j in range(n))
                self.assertEqual(solved.value, -vertex_value(negative_transpose))

    def test_certificate_rejects_wrong_probabilities_or_value(self):
        matrix = ((1, 0), (0, 1))
        solved = solve_matrix(matrix)
        for changed in (replace(solved, red=(Q(1), Q(0))), replace(solved, black=(Q(1), Q(0))),
                        replace(solved, value=Q(2, 3)), replace(solved, red=(Q(-1), Q(2))),
                        replace(solved, numeric_error_bound=Q(1, 100))):
            with self.assertRaises(ValueError):
                verify_matrix_solution(matrix, changed)

    def test_limits_and_invalid_input_never_return_unverified_tableau(self):
        for matrix in (None, "12", [1, 2], ["12"], (), ((),), ((1,), (1, 2)), ((float("nan"),),), ((True,),)):
            with self.assertRaises(ValueError):
                solve_matrix(matrix)
        with self.assertRaises(MatrixLimit) as limited:
            solve_matrix(((1, 0), (0, 1)), pivot_limit=1)
        self.assertEqual(limited.exception.reason, "pivot_limit")
        with self.assertRaises(MatrixLimit):
            solve_matrix(((1,),), deadline=perf_counter()-1)
        for value in (True, 0, -1, 1.5):
            with self.assertRaises(ValueError):
                solve_matrix(((1,),), pivot_limit=value)
        self.assertEqual(rational("1/3"), Q(1, 3))
        self.assertEqual(rational(0.1), Q(1, 10))


if __name__ == "__main__":
    unittest.main()
