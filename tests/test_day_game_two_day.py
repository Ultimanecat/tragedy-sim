"""T2 scaffold tests."""

import unittest

from tests.test_day_game_information_game import rescue_root
from tragedy_sim.day_game.continuation import WorkLimit
from tragedy_sim.day_game.two_day import KnownWorldTwoDaySolver


def next_day_start():
    world = rescue_root()
    for _ in range(64):
        if world.state.phase == "day_start" and world.state.round == 1 and world.state.loop == 2:
            return world
        actions = world.legal_actions(world.controller)
        if not actions:
            break
        action = next((item for item in actions if item.get("action") in {"next", "resolve"}), actions[0])
        world = world.transition(action).game
    raise RuntimeError("could not reach the next day start")


class TwoDayScaffoldTests(unittest.TestCase):
    def test_finished_game_is_exact(self):
        world = rescue_root()
        world.winner = "protagonists"
        result = KnownWorldTwoDaySolver().solve(world)
        self.assertEqual((result.bounds.lower, result.bounds.upper), (1.0, 1.0))
        world.winner = "mastermind"
        result = KnownWorldTwoDaySolver().solve(world)
        self.assertEqual((result.bounds.lower, result.bounds.upper), (0.0, 0.0))

    def test_bounded_search_returns_a_restricted_result(self):
        world = next_day_start()
        result = KnownWorldTwoDaySolver(max_depth=6, action_limit=1).solve(world, work=WorkLimit(node_limit=20))
        self.assertTrue(result.restricted)
        self.assertLessEqual(result.bounds.lower, result.bounds.upper)
        self.assertIn(result.stop_reasons, {("node_limit",), ("depth_limit",), ("action_limit",),
                                            ("action_limit", "node_limit"), ("action_limit", "depth_limit")})
        self.assertEqual(result.horizon, "two-days")

    def test_invalid_limits_are_rejected(self):
        with self.assertRaises(ValueError):
            KnownWorldTwoDaySolver(max_depth=0)
        with self.assertRaises(ValueError):
            KnownWorldTwoDaySolver(action_limit=0)


if __name__ == "__main__":
    unittest.main()
