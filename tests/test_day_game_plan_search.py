"""Bounded two-day plan search tests."""

import unittest

from tests.test_day_game_information_game import rescue_root
from tests.test_day_game_two_day import next_day_start
from tragedy_sim.day_game.defense_value import DefenseLeafEstimator
from tragedy_sim.day_game.plan_search import (black_day_plans, red_day_plans,
                                              search_two_day)


class TwoDayPlanSearchTests(unittest.TestCase):
    def test_plan_enumeration_and_search(self):
        world = next_day_start()
        black = black_day_plans(world, limit=1)
        self.assertEqual(len(black), 1)
        self.assertEqual(len(black[0]), 3)
        red = red_day_plans(world, black[0], limit=1)
        self.assertEqual(len(red), 1)
        self.assertEqual(len(red[0]), 3)
        result = search_two_day(world, black_limit=1, red_limit=1)
        self.assertGreaterEqual(result.value, 0.0)
        self.assertLessEqual(result.value, 1.0)
        self.assertEqual(result.evaluations, 1)
        self.assertEqual(len(result.red_plan), 3)
        self.assertEqual(len(result.black_plan), 3)

    def test_finished_game_has_no_day_to_plan(self):
        world = rescue_root()
        world.winner = "protagonists"
        result = search_two_day(world)
        self.assertEqual(result.terminal, "no_day_to_plan")
        self.assertEqual(result.evaluations, 0)

    def test_defense_leaf_estimator_can_drive_two_day_search(self):
        world = next_day_start()
        result = search_two_day(world, black_limit=1, red_limit=1,
                                leaf_value=DefenseLeafEstimator())
        self.assertEqual(result.evaluations, 1)
        self.assertGreater(result.value, 0.0)

    def test_invalid_limits_are_rejected(self):
        with self.assertRaises(ValueError):
            search_two_day(next_day_start(), black_limit=0)
        with self.assertRaises(ValueError):
            search_two_day(next_day_start(), red_limit=0)


if __name__ == "__main__":
    unittest.main()
