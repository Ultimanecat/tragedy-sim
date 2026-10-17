"""Blocked best responses, original posterior mass, and shared red decisions."""

from fractions import Fraction as Q
import random
import unittest

from tests.test_day_game_bayesian_matrix import expanded_matrix
from tragedy_sim.day_game.bayesian import BayesianDoubleOracle, BayesianGame, WorldBlock
from tragedy_sim.day_game.matrix import solve_matrix
from tragedy_sim.day_game.zero_sum import MatrixGame, RationalInterval, SearchBudget


def model(blocks, weights, **options):
    return BayesianGame(tuple(WorldBlock(str(h), p, MatrixGame(b)) for h, (b, p) in enumerate(zip(blocks, weights))), **options)


class BayesianOracleTests(unittest.TestCase):
    def test_common_red_cannot_read_hidden_type_and_black_responds_per_type(self):
        worlds = model((((1,), (0,)), ((0,), (1,))), (Q(1, 2), Q(1, 2)), belief_domain_complete=True)
        result = BayesianDoubleOracle(worlds).solve()
        self.assertTrue(result.certified_optimal)
        self.assertEqual((result.lower_bound, result.upper_bound), (Q(1, 2), Q(1, 2)))
        adversarial = model((((1, 0), (1, 0)), ((0, 1), (0, 1))), (Q(1, 2), Q(1, 2)), belief_domain_complete=True)
        result = BayesianDoubleOracle(adversarial).solve()
        self.assertTrue(result.certified_optimal)
        self.assertEqual(result.lower_bound, 0)
        self.assertEqual(dict(result.black), {"0": ((1, Q(1)),), "1": ((0, Q(1)),)})

    def test_fixed_seeds_match_explicit_full_type_policy_product(self):
        for seed in range(10):
            rng = random.Random(seed)
            for rows, sizes in ((2, (2, 3)), (3, (1, 2, 2)), (4, (3, 2, 2))):
                blocks = tuple(tuple(tuple(rng.randrange(2) for _ in range(n)) for _ in range(rows)) for n in sizes)
                raw = tuple(rng.randrange(1, 10) for _ in sizes)
                masses = tuple(Q(p, sum(raw)) for p in raw)
                solver = BayesianDoubleOracle(model(blocks, masses, belief_domain_complete=True))
                result = solver.solve(max_iterations=32)
                expected = solve_matrix(expanded_matrix(blocks, masses)).value
                self.assertTrue(result.certified_optimal, (seed, sizes, result))
                self.assertEqual((result.lower_bound, result.upper_bound), (expected, expected))
                red = dict(result.red)
                self.assertEqual(sum(red.values()), 1)
                guarantee = sum(p*min(sum(red.get(i, 0)*block[i][j] for i in range(rows))
                                      for j in range(len(block[0]))) for p, block in zip(masses, blocks))
                self.assertEqual(guarantee, expected)

    def test_missing_posterior_mass_is_not_renormalized_away(self):
        worlds = model((((1,), (1,)),), (Q(9, 10),))
        result = BayesianDoubleOracle(worlds).solve()
        self.assertEqual(result.covered_mass, Q(9, 10))
        self.assertEqual(result.missing_mass, Q(1, 10))
        self.assertEqual((result.covered_lower_bound, result.covered_upper_bound), (Q(9, 10), Q(9, 10)))
        self.assertEqual((result.lower_bound, result.upper_bound), (Q(9, 10), 1))
        self.assertEqual(result.stop_reason, "unrepresented_mass")
        self.assertFalse(result.certified_optimal)
        self.assertFalse(result.certified_epsilon)
        with self.assertRaises(ValueError):
            model((((1,),),), (Q(9, 10),), belief_domain_complete=True)

    def test_mass_one_from_samples_does_not_prove_posterior_coverage(self):
        result = BayesianDoubleOracle(model((((1,),),), (1,))).solve()
        self.assertEqual(result.gap, 0)
        self.assertFalse(result.belief_domain_complete)
        self.assertFalse(result.certified_optimal)
        self.assertEqual(result.stop_reason, "finite_model_only")

    def test_unrepresented_mass_uses_declared_signed_utility_bounds(self):
        worlds = model((((-2,), (1,)),), (Q(1, 2),), utility=RationalInterval(-2, 3))
        result = BayesianDoubleOracle(worlds).solve()
        self.assertEqual((result.covered_lower_bound, result.covered_upper_bound), (Q(1, 2), Q(1, 2)))
        self.assertEqual((result.lower_bound, result.upper_bound), (Q(-1, 2), Q(2)))
        self.assertFalse(result.certified_optimal)

    def test_budget_interruption_preserves_bounds_and_resume_uses_exact_caches(self):
        worlds = model((((1, 0), (0, 1)),)*2, (Q(1, 3), Q(2, 3)), belief_domain_complete=True)
        solver = BayesianDoubleOracle(worlds)
        partial = solver.solve(budget=SearchBudget(payoff_limit=2))
        self.assertLessEqual(partial.lower_bound, Q(1, 2))
        self.assertGreaterEqual(partial.upper_bound, Q(1, 2))
        self.assertFalse(partial.certified_optimal)
        self.assertEqual(partial.stop_reason, "payoff_limit")
        result = solver.solve()
        self.assertTrue(result.certified_optimal)
        self.assertEqual(result.lower_bound, Q(1, 2))
        self.assertGreater(sum(c.stats.hits for c in solver.caches), 0)
        self.assertTrue(solver.solve().best_response_complete)

    def test_unknown_continuation_is_never_cached_or_assumed_zero(self):
        class Unknown(MatrixGame):
            def evaluate(self, row, column, budget):
                return self.utility
        worlds = BayesianGame((WorldBlock("h", 1, Unknown(((1, 0), (0, 1)))),), belief_domain_complete=True)
        solver = BayesianDoubleOracle(worlds)
        result = solver.solve()
        self.assertEqual(result.stop_reason, "continuation_incomplete")
        self.assertEqual((result.lower_bound, result.upper_bound), (0, 1))
        self.assertFalse(solver.caches[0].values)

    def test_full_black_response_scans_sum_of_domains_not_policy_product(self):
        worlds = model((((1, 0), (0, 1)),)*12, (Q(1, 12),)*12, belief_domain_complete=True)
        result = BayesianDoubleOracle(worlds).solve()
        self.assertTrue(result.certified_optimal)
        self.assertEqual(result.lower_bound, Q(1, 2))
        last = result.iterations[-1]
        self.assertLessEqual(sum(r.visited for r in last.black_responses), 24)
        self.assertEqual(last.columns_by_world, (2,)*12)

    def test_invalid_masses_domains_and_seeds_fail_before_search(self):
        for masses in ((0,), (-1,), (Q(11, 10),)):
            with self.assertRaises(ValueError):
                model((((1,),),), masses)
        with self.assertRaises(ValueError):
            model((((1,),), ((1,), (0,))), (Q(1, 2), Q(1, 2)))
        with self.assertRaises(ValueError):
            BayesianGame((WorldBlock("same", Q(1, 2), MatrixGame(((0,),))),)*2)
        worlds = model((((1, 0), (0, 1)),), (1,), belief_domain_complete=True)
        with self.assertRaises(ValueError):
            BayesianDoubleOracle(worlds, seed_columns={"other": (0,)})
        with self.assertRaises(ValueError):
            BayesianDoubleOracle(worlds, seed_columns={"0": (0, 99)})
        with self.assertRaises(ValueError):
            BayesianDoubleOracle(worlds, seed_rows=(0, 99))
        for options in (dict(epsilon=-1), dict(max_iterations=0), dict(pivot_limit=True)):
            with self.assertRaises(ValueError):
                BayesianDoubleOracle(worlds).solve(**options)
        stopped = BayesianDoubleOracle(worlds, seed_rows=(0, 1), seed_columns={"0": (0, 1)}).solve(pivot_limit=1)
        self.assertEqual(stopped.stop_reason, "pivot_limit")
        self.assertFalse(stopped.certified_optimal)


if __name__ == "__main__":
    unittest.main()
