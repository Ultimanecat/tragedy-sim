"""T1 continuation-value interface tests."""

from copy import deepcopy
from fractions import Fraction as Q
import unittest

from tests.test_day_game_information_game import rescue_root
from tragedy_sim.day_game.continuation import day_boundary_value
from tragedy_sim.day_game.information_game import _Builder, build_ability_information_tree, solve_information_tree
from tragedy_sim.day_game.continuation import WorkLimit
from tragedy_sim.day_game.value import (BoundaryContext, DaySurvivalEvaluator, RandomRolloutEvaluator,
                                        UnknownEvaluator, ValueEstimate, boundary_context)


class ContinuationValueTests(unittest.TestCase):
    def test_day_survival_evaluator_matches_engine_boundaries(self):
        evaluator, position = DaySurvivalEvaluator(), (1, 3)
        for setup, expected in (("after_day", 1), ("next_loop", 0), ("loop_end", 0)):
            world = rescue_root()
            if setup == "after_day":
                world.state.round = 4
            elif setup == "next_loop":
                world.state.loop = 2
            else:
                world.state.phase = "loop_end"
            self.assertEqual(day_boundary_value(world, position), float(expected))
            estimate = evaluator.evaluate(boundary_context(world, position))
            self.assertEqual(estimate.lower, Q(expected))
            self.assertEqual(estimate.upper, Q(expected))
            self.assertTrue(estimate.certified)
            self.assertEqual(estimate.version, "day-survival-v1")

    def test_boundary_context_carries_remaining_days_and_loops(self):
        world = rescue_root()
        world.state.loop, world.state.round = 1, 2
        context = boundary_context(world, (1, 2))
        self.assertEqual(context.remaining_loops, 1)
        self.assertEqual(context.remaining_days, 2)
        self.assertEqual(context.utility_version, "day-survival-v1")
        self.assertEqual(context.scope, "known-world")

    def test_unknown_evaluator_is_never_a_certificate(self):
        estimate = UnknownEvaluator().evaluate(boundary_context(rescue_root(), (1, 3)))
        self.assertEqual((estimate.lower, estimate.upper), (Q(0), Q(1)))
        self.assertFalse(estimate.certified)
        self.assertIsNone(estimate.constant)

    def test_invalid_estimates_and_contexts_fail_closed(self):
        with self.assertRaises(ValueError):
            ValueEstimate(Q(1), Q(0), True, "x", "v")
        with self.assertRaises(ValueError):
            ValueEstimate(Q(-1, 2), Q(1), True, "x", "v")
        with self.assertRaises(ValueError):
            ValueEstimate(0.5, 0.5, True, "x", "v")
        with self.assertRaises(ValueError):
            BoundaryContext(rescue_root(), (0, 1), 0, 0)
        with self.assertRaises(ValueError):
            boundary_context(rescue_root(), (1,))

    def test_day_survival_evaluator_preserves_existing_tree_values(self):
        world = rescue_root()
        reference = build_ability_information_tree((("known", 1, world),), belief_domain_complete=True)
        evaluated = build_ability_information_tree((("known", 1, world),), belief_domain_complete=True,
                                                    boundary_evaluator=DaySurvivalEvaluator())
        self.assertEqual(solve_information_tree(reference).bounds, solve_information_tree(evaluated).bounds)
        self.assertEqual(reference.engine_nodes, evaluated.engine_nodes)
        self.assertEqual(reference.engine_transitions, evaluated.engine_transitions)
        self.assertEqual(reference.unknown_leaves, evaluated.unknown_leaves)

    def test_uncertified_boundary_values_keep_tree_unknown(self):
        world = rescue_root()
        tree = build_ability_information_tree((("known", 1, world),), belief_domain_complete=True,
                                              range_compression=False, boundary_evaluator=UnknownEvaluator())
        self.assertFalse(tree.continuation_complete)
        self.assertGreater(tree.unknown_leaves, 0)
        result = solve_information_tree(tree)
        self.assertEqual((result.bounds.lower, result.bounds.upper), (Q(0), Q(1)))
        self.assertFalse(result.certified_optimal)
        with self.assertRaises(ValueError):
            build_ability_information_tree((("known", 1, world),), belief_domain_complete=True,
                                           boundary_evaluator=UnknownEvaluator())

    def test_boundary_evaluator_requires_a_version_and_evaluate(self):
        class VersionOnly:
            version = "bad"

        with self.assertRaises(ValueError):
            _Builder(work=WorkLimit(), max_depth=8, tree_node_limit=100, boundary_evaluator=object())
        with self.assertRaises(ValueError):
            _Builder(work=WorkLimit(), max_depth=8, tree_node_limit=100, boundary_evaluator=VersionOnly())

    def test_random_rollout_is_deterministic_and_never_certified(self):
        world, context = rescue_root(), boundary_context(rescue_root(), (1, 3))
        evaluator = RandomRolloutEvaluator(rollouts=2, max_steps=1000, seed=7)
        first, second = evaluator.evaluate(context), evaluator.evaluate(context)
        self.assertEqual(first, second)
        self.assertFalse(first.certified)
        self.assertLessEqual(first.lower, first.upper)
        self.assertTrue(Q(0) <= first.lower <= first.upper <= Q(1))
        with self.assertRaises(ValueError):
            evaluator.evaluate(BoundaryContext(world, (1, 3), 1, 1, scope="team"))
        with self.assertRaises(ValueError):
            RandomRolloutEvaluator(rollouts=0)
        with self.assertRaises(ValueError):
            RandomRolloutEvaluator(max_steps=0)
        with self.assertRaises(ValueError):
            RandomRolloutEvaluator(seed=1.5)

    def test_random_rollout_returns_terminal_winner_exactly(self):
        world = rescue_root()
        world.winner = "protagonists"
        estimate = RandomRolloutEvaluator().evaluate(boundary_context(world, (1, 3)))
        self.assertEqual((estimate.lower, estimate.upper), (Q(1), Q(1)))
        self.assertTrue(estimate.certified)
        world.winner = "mastermind"
        estimate = RandomRolloutEvaluator().evaluate(boundary_context(world, (1, 3)))
        self.assertEqual((estimate.lower, estimate.upper), (Q(0), Q(0)))
        self.assertTrue(estimate.certified)


if __name__ == "__main__":
    unittest.main()
