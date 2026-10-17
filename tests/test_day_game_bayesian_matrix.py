"""Blocked LP versus independently expanded type-contingent black policies."""

from dataclasses import replace
from fractions import Fraction as Q
from itertools import product
import random
from time import perf_counter
import unittest

from tragedy_sim.day_game.bayesian_matrix import solve_bayesian_matrix, verify_bayesian_matrix
from tragedy_sim.day_game.matrix import MatrixLimit, solve_matrix, solve_nonnegative_lp


def expanded_matrix(blocks, weights):
    columns = tuple(product(*(range(len(block[0])) for block in blocks)))
    return tuple(tuple(sum(p*block[i][j] for p, block, j in zip(weights, blocks, choices))
                       for choices in columns) for i in range(len(blocks[0])))


class BayesianMatrixTests(unittest.TestCase):
    def test_red_uses_one_action_distribution_across_hidden_types(self):
        blocks = (((1,), (0,)), ((0,), (1,)))
        result = solve_bayesian_matrix(blocks, (Q(1, 2), Q(1, 2)))
        self.assertEqual(result.value, Q(1, 2))
        self.assertNotEqual(result.value, 1)  # Illegal world-wise red optimization.
        self.assertEqual(solve_bayesian_matrix(blocks, (Q(9, 10), Q(1, 10))).red, (Q(1), Q(0)))

    def test_black_can_choose_a_different_face_policy_for_each_type(self):
        blocks = (((1, 0), (1, 0)), ((0, 1), (0, 1)))
        result = solve_bayesian_matrix(blocks, (Q(1, 2), Q(1, 2)))
        self.assertEqual(result.value, 0)
        self.assertEqual(result.black, ((Q(0), Q(1)), (Q(1), Q(0))))
        self.assertEqual(solve_matrix(((Q(1, 2), Q(1, 2)),)*2).value, Q(1, 2))

    def test_fixed_seeds_match_full_policy_cartesian_product(self):
        for seed in range(10):
            rng = random.Random(seed)
            for rows, sizes in ((2, (2, 3)), (3, (1, 2, 2)), (4, (3, 2, 2))):
                blocks = tuple(tuple(tuple(Q(rng.randrange(-4, 5), 3) for _ in range(n))
                                     for _ in range(rows)) for n in sizes)
                masses = tuple(rng.randrange(1, 10) for _ in sizes)
                weights = tuple(Q(p, sum(masses)) for p in masses)
                result = solve_bayesian_matrix(blocks, weights)
                self.assertEqual(result.value, solve_matrix(expanded_matrix(blocks, weights)).value,
                                 (seed, rows, sizes))
                self.assertTrue(verify_bayesian_matrix(blocks, weights, result))

    def test_single_type_matches_ordinary_mixed_game_and_large_type_count_is_linear(self):
        matrix = ((1, 0), (0, 1))
        self.assertEqual(solve_bayesian_matrix((matrix,), (1,)).value, solve_matrix(matrix).value)
        result = solve_bayesian_matrix((matrix,)*12, (Q(1, 12),)*12)
        self.assertEqual(result.value, Q(1, 2))
        self.assertEqual(result.lp_constraints, 2+2*12)
        self.assertEqual(result.lp_variables, 1+2*12)
        self.assertLess(result.lp_variables, 2**12)

    def test_forged_probabilities_or_values_fail_original_block_verification(self):
        blocks, weights = (((1, 0), (0, 1)),), (1,)
        good = solve_bayesian_matrix(blocks, weights)
        for bad in (replace(good, red=(Q(1), Q(0))), replace(good, black=((Q(1), Q(0)),)),
                    replace(good, value=Q(2, 3)), replace(good, numeric_error_bound=Q(1, 100))):
            with self.assertRaises(ValueError):
                verify_bayesian_matrix(blocks, weights, bad)

    def test_limits_and_invalid_blocks_never_produce_an_unchecked_certificate(self):
        for blocks, weights in (((), ()), ((((1,),),), (0,)), ((((1,),),), (Q(1, 2),)),
                                ((((1,),), ((0,), (1,))), (Q(1, 2), Q(1, 2))),
                                (None, (1,)), ((((1,),),), None)):
            with self.assertRaises(ValueError):
                solve_bayesian_matrix(blocks, weights)
        for options in (dict(pivot_limit=1), dict(deadline=perf_counter()-1)):
            with self.assertRaises(MatrixLimit):
                solve_bayesian_matrix((((1, 0), (0, 1)),), (1,), **options)

    def test_shared_lp_handles_zero_rhs_degeneracy_and_checks_both_objectives(self):
        result = solve_nonnegative_lp(((1, 0), (1, 1)), (0, 1), (1, 1))
        self.assertEqual(result.primal, (0, 1))
        self.assertEqual(result.value, 1)
        self.assertEqual(result.dual, (0, 1))
        self.assertEqual(solve_nonnegative_lp(((1,),), (1,), (-1,)).value, 0)
        for matrix, rhs, objective in ((((1,),), (-1,), (1,)), (((1,),), (1,), (1, 2)),
                                       (((-1,),), (1,), (1,))):
            with self.assertRaises(ValueError):
                solve_nonnegative_lp(matrix, rhs, objective)


if __name__ == "__main__":
    unittest.main()
