"""State-returning day transition tests."""

import unittest

from tests.test_day_game_information_game import rescue_root
from tests.test_day_game_two_day import next_day_start
from tragedy_sim.day_game.transition import advance_to_day_boundary


def nextish(game, actions):
    return next((item for item in actions
                 if item.get("action") in {"next", "resolve"}), actions[0])


class DayTransitionTests(unittest.TestCase):
    def test_advance_returns_the_next_day_state(self):
        result = advance_to_day_boundary(next_day_start(), nextish)
        self.assertEqual(result.terminal, "survived_day")
        self.assertTrue(result.next_day)
        self.assertNotEqual(result.end_position, result.start_position)
        self.assertGreater(len(result.commands), 0)
        self.assertIsNotNone(result.state)

    def test_policy_stop_is_reported(self):
        result = advance_to_day_boundary(rescue_root(), lambda game, actions: None)
        self.assertEqual(result.terminal, "stopped")
        self.assertEqual(result.stop_reason, "policy_stop")
        self.assertEqual(result.commands, ())

    def test_illegal_policy_action_is_rejected(self):
        result = advance_to_day_boundary(rescue_root(),
                                         lambda game, actions: {"action": "bogus"})
        self.assertEqual(result.stop_reason, "illegal_policy_action")

    def test_command_limit_is_reported(self):
        result = advance_to_day_boundary(rescue_root(), nextish, max_commands=1)
        self.assertEqual(result.stop_reason, "command_limit")

    def test_invalid_game_is_rejected(self):
        with self.assertRaises(ValueError):
            advance_to_day_boundary(object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
