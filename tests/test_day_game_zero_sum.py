"""Full-domain responses, unknown-cell intervals and Double Oracle certificates."""

from fractions import Fraction as Q
import random
import unittest

from tragedy_sim.day_game import WorkLimit
from tragedy_sim.day_game.matrix import solve_matrix
from tragedy_sim.day_game.zero_sum import (DoubleOracle, MatrixGame, PayoffCache, RationalInterval,
                                           SearchBudget, best_response)


class FullResponseTests(unittest.TestCase):
    def test_exact_responses_match_direct_weighted_full_domain_values(self):
        matrix = ((0, 1, 0), (1, 0, 1), (Q(1, 2), Q(3, 4), Q(1, 3)))
        game = MatrixGame(matrix)
        cache = PayoffCache(game)
        y = ((0, Q(1, 3)), (1, Q(1, 6)), (2, Q(1, 2)))
        x = ((0, Q(1, 5)), (1, Q(3, 5)), (2, Q(1, 5)))
        red = best_response(cache, "red", y, SearchBudget())
        black = best_response(cache, "black", x, SearchBudget())
        expected_red = max(sum(matrix[i][j] * p for j, p in y) for i in range(3))
        expected_black = min(sum(matrix[i][j] * p for i, p in x) for j in range(3))
        self.assertEqual(red.bounds, RationalInterval(expected_red, expected_red))
        self.assertEqual(black.bounds, RationalInterval(expected_black, expected_black))
        self.assertTrue(red.complete and black.complete)

    def test_unvisited_domain_remains_unknown_and_cannot_be_declared_safe(self):
        game = MatrixGame(((1, 0), (0, 1)))
        budget = SearchBudget(payoff_limit=1)
        red = best_response(PayoffCache(game), "red", ((0, Q(1, 2)), (1, Q(1, 2))), budget)
        self.assertEqual(red.bounds.lower, Q(1, 2))
        self.assertEqual(red.bounds.upper, 1)
        self.assertFalse(red.complete)
        self.assertFalse(red.domain_exhausted)
        black = best_response(PayoffCache(game), "black", ((0, Q(1, 2)), (1, Q(1, 2))), SearchBudget(payoff_limit=1), preferred=(1,))
        self.assertEqual(black.bounds, RationalInterval(0, Q(1, 2)))
        self.assertFalse(black.complete)

    def test_proved_partial_sum_pruning_does_not_change_response(self):
        game = MatrixGame(((1, 1, 0), (0, 0, 1), (0, 1, 1)))
        response = best_response(PayoffCache(game), "red", ((0, Q(3, 4)), (1, Q(1, 8)), (2, Q(1, 8))), SearchBudget())
        self.assertEqual(response.bounds, RationalInterval(Q(7, 8), Q(7, 8)))
        self.assertGreater(response.pruned, 0)
        self.assertLess(response.payoff_requests, 9)

    def test_utility_extremum_cuts_without_truncating_the_declared_domain(self):
        game = MatrixGame(((1, 1), (0, 0), (0, 1)))
        response = best_response(PayoffCache(game), "red", ((0, Q(1, 2)), (1, Q(1, 2))), SearchBudget())
        self.assertEqual(response.bounds, RationalInterval(1, 1))
        self.assertEqual(response.visited, 1)
        self.assertEqual(response.domain_size, 3)
        self.assertTrue(response.complete)
        self.assertFalse(response.domain_exhausted)

    def test_unknown_cells_are_not_saved_as_zero_and_can_be_retried(self):
        class Incomplete(MatrixGame):
            known = False

            def evaluate(self, row, column, budget):
                return super().evaluate(row, column, budget) if self.known else self.utility

        game = Incomplete(((1, 0), (0, 1)))
        cache = PayoffCache(game)
        self.assertEqual(cache.get(0, 0, SearchBudget()), RationalInterval(0, 1))
        self.assertFalse(cache.values)
        game.known = True
        self.assertEqual(cache.get(0, 0, SearchBudget()), RationalInterval(1, 1))
        self.assertEqual(len(cache.values), 1)

    def test_preferred_and_support_actions_are_validated_even_when_zero_or_unused(self):
        cache = PayoffCache(MatrixGame(((1, 0), (0, 1))))
        for distribution in (((0, 1), (99, 0)), ((0, Q(1, 3)),), ((0, -1), (1, 2))):
            with self.assertRaises(ValueError):
                best_response(cache, "red", distribution, SearchBudget())
        with self.assertRaises(ValueError):
            best_response(cache, "red", ((0, 1),), SearchBudget(), preferred=(0, 99))
        response = best_response(cache, "red", ((0, Q(1, 2)), (0, Q(1, 2))), SearchBudget())
        self.assertEqual(response.bounds.lower, 1)


class DoubleOracleTests(unittest.TestCase):
    def test_matching_game_grows_counterexamples_and_certifies_half(self):
        solver = DoubleOracle(MatrixGame(((1, 0), (0, 1))))
        result = solver.solve()
        self.assertTrue(result.certified_optimal)
        self.assertEqual(result.lower_bound, Q(1, 2))
        self.assertEqual(result.upper_bound, Q(1, 2))
        self.assertEqual(dict(result.red), {0: Q(1, 2), 1: Q(1, 2)})
        self.assertEqual(dict(result.black), dict(result.red))
        self.assertEqual(result.numeric_error_bound, 0)
        self.assertEqual((result.generated_rows, result.generated_columns), (2, 2))
        self.assertGreater(len(result.iterations), 1)
        again = solver.solve()
        self.assertEqual(again.lower_bound, Q(1, 2))
        self.assertFalse(again.iterations)
        self.assertTrue(again.best_response_complete)

    def test_all_small_fixed_seed_games_match_full_matrix_solution(self):
        for seed in range(10):
            rng = random.Random(seed)
            for m, n in ((2, 3), (3, 2), (3, 3), (4, 4)):
                matrix = tuple(tuple(rng.randrange(-2, 4) for _ in range(n)) for _ in range(m))
                result = DoubleOracle(MatrixGame(matrix)).solve(max_iterations=m+n+2)
                gold = solve_matrix(matrix)
                self.assertTrue(result.certified_optimal, (seed, m, n, result))
                self.assertEqual(result.lower_bound, gold.value)
                self.assertEqual(result.upper_bound, gold.value)
                self.assertEqual(sum(p for _, p in result.red), 1)
                self.assertEqual(sum(p for _, p in result.black), 1)
                self.assertTrue(all(sum(p*matrix[i][j] for i, p in result.red) >= result.lower_bound for j in range(n)))
                self.assertTrue(all(sum(p*matrix[i][j] for j, p in result.black) <= result.upper_bound for i in range(m)))

    def test_budget_and_iteration_limits_retain_global_bounds_and_can_resume(self):
        matrix = ((1, 0), (0, 1))
        solver = DoubleOracle(MatrixGame(matrix))
        early = solver.solve(budget=SearchBudget(payoff_limit=1))
        self.assertFalse(early.certified_optimal)
        self.assertLessEqual(early.lower_bound, Q(1, 2))
        self.assertGreaterEqual(early.upper_bound, Q(1, 2))
        self.assertEqual(early.stop_reason, "payoff_limit")
        later = solver.solve()
        self.assertTrue(later.certified_optimal)
        limited = DoubleOracle(MatrixGame(matrix)).solve(max_iterations=1)
        self.assertEqual(limited.stop_reason, "iteration_limit")
        self.assertFalse(limited.certified_optimal)
        timed = SearchBudget(work=WorkLimit(time_limit_ms=1))
        timed.work.started -= 1
        result = DoubleOracle(MatrixGame(matrix)).solve(budget=timed)
        self.assertEqual(result.stop_reason, "time_limit")
        self.assertFalse(result.certified_optimal)

    def test_incomplete_continuation_never_generates_false_matrix_optimum(self):
        class Unknown(MatrixGame):
            def evaluate(self, row, column, budget):
                return self.utility

        result = DoubleOracle(Unknown(((1, 0), (0, 1)))).solve()
        self.assertEqual(result.stop_reason, "continuation_incomplete")
        self.assertFalse(result.certified_optimal)
        self.assertEqual((result.lower_bound, result.upper_bound), (0, 1))
        response = best_response(PayoffCache(Unknown(((1, 0), (0, 1)))), "red", ((0, 1),), SearchBudget())
        self.assertTrue(response.domain_exhausted)
        self.assertFalse(response.complete)
        self.assertEqual(response.stop_reason, "continuation_incomplete")

    def test_incomplete_model_scope_and_invalid_configuration(self):
        class Sampled(MatrixGame):
            belief_domain_complete = False

        result = DoubleOracle(Sampled(((1, 0), (0, 1)))).solve()
        self.assertEqual(result.gap, 0)
        self.assertFalse(result.certified_optimal)
        self.assertFalse(result.certified_epsilon)
        self.assertEqual(result.stop_reason, "finite_model_only")
        for value in (True, 0, -1, 1.5):
            with self.assertRaises(ValueError):
                SearchBudget(payoff_limit=value)
            with self.assertRaises(ValueError):
                DoubleOracle(MatrixGame(((1,),))).solve(max_iterations=value)
        with self.assertRaises(ValueError):
            DoubleOracle(MatrixGame(((1,),)), seed_rows=(0, 2))
        with self.assertRaises(ValueError):
            DoubleOracle(MatrixGame(((1,),))).solve(epsilon=-1)
        limited = DoubleOracle(MatrixGame(((1, 0), (0, 1))), seed_rows=(0, 1), seed_columns=(0, 1)).solve(pivot_limit=1)
        self.assertEqual(limited.stop_reason, "pivot_limit")
        self.assertFalse(limited.certified_optimal)

    def test_payoff_cache_retains_exact_cells_under_lru_capacity(self):
        cache = PayoffCache(MatrixGame(((1, 0), (0, 1))), capacity=1)
        cache.get(0, 0, SearchBudget())
        cache.get(0, 0, SearchBudget())
        cache.get(0, 1, SearchBudget())
        self.assertEqual(cache.stats.hits, 1)
        self.assertEqual(cache.stats.evictions, 1)
        self.assertEqual(len(cache.values), 1)
        with self.assertRaises(ValueError):
            cache.get(-1, 0, SearchBudget())
        limited = SearchBudget(payoff_limit=1)
        cache.get(1, 0, limited)
        self.assertEqual(cache.get(1, 1, limited), RationalInterval(0, 1))
        self.assertEqual(cache.stats.budget_unknowns, 1)


if __name__ == "__main__":
    unittest.main()
