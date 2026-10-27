"""Observation branch snapshot tests."""

import unittest

from tests.test_day_game_two_day import next_day_start
from tragedy_sim.day_game.observation import (group_observation_snapshots,
                                              make_observation_branch)
from tragedy_sim.day_game.transition import advance_to_day_boundary


def nextish(game, actions):
    return next((item for item in actions
                 if item.get("action") in {"next", "resolve"}), actions[0])


class ObservationBranchTests(unittest.TestCase):
    def test_snapshot_rebuilds_public_evidence(self):
        result = advance_to_day_boundary(next_day_start(), nextish)
        branch = make_observation_branch(result)
        self.assertIsNotNone(branch)
        self.assertEqual(branch.position, result.end_position)
        self.assertIn("characters", branch.public_view)
        self.assertIsInstance(branch.witnesses, tuple)

    def test_same_public_observation_groups(self):
        first = make_observation_branch(advance_to_day_boundary(next_day_start(), nextish))
        second = make_observation_branch(advance_to_day_boundary(next_day_start(), nextish))
        grouped = group_observation_snapshots((first, second))
        self.assertEqual(len(grouped), 1)
        self.assertEqual(len(next(iter(grouped.values()))), 2)

    def test_missing_public_view_returns_none(self):
        result = advance_to_day_boundary(next_day_start(), nextish)
        empty = type(result)(result.state, result.start_position, result.end_position,
                             result.commands, result.new_events, result.terminal,
                             result.stop_reason, result.elapsed_seconds,
                             result.policy_name, None)
        self.assertIsNone(make_observation_branch(empty))


if __name__ == "__main__":
    unittest.main()
