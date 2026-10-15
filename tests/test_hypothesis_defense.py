"""Dark coverage must not alter identity/culprit posterior mass."""

from copy import deepcopy
import unittest
from unittest.mock import Mock, patch

from tests.test_dark_attack_scenarios import threat_root
from tragedy_sim.hypothesis_defense import HypothesisThreatRanker
from tragedy_sim.joint_action_space import JointActionSpace


class HypothesisDefenseTests(unittest.TestCase):
    def test_weighted_hypotheses_are_not_global_worst_or_attack_frequencies(self):
        groups = ((object(),) * 20, (object(),))
        ranks = (Mock(return_value=(1., 0., .2)), Mock(return_value=(0., -3., -.8)))
        with patch("tragedy_sim.hypothesis_defense.JointThreatRanker", side_effect=ranks):
            ranker = HypothesisThreatRanker(groups, None, weights=(3, 1))
        result = ranker(())
        self.assertEqual(ranker.weights, (.75, .25))
        self.assertEqual(result[:2], (.75, -.75))
        self.assertAlmostEqual(result[2], -.05)

    def test_duplicate_attacks_preserve_mass_and_inputs(self):
        game = threat_root()
        other = game.search_clone()
        other.roles["girl"] = "ordinary"
        before = deepcopy(game.view("m"))
        space = JointActionSpace(game.protagonist_team_view(), game.search_actions(game.controller))
        plan = next(space.iter_plans())
        original = HypothesisThreatRanker(((game,), (other,)), space, weights=(3, 1))
        expanded = HypothesisThreatRanker(((game,) * 8, (other,)), space, weights=(3, 1))
        self.assertEqual(original(plan), expanded(plan))
        self.assertEqual(game.view("m"), before)
        self.assertEqual(expanded.weights, original.weights)

    def test_mixed_identities_allowed_between_groups_but_rejected_within(self):
        game = threat_root()
        other = game.search_clone()
        other.roles["girl"] = "ordinary"
        space = JointActionSpace(game.protagonist_team_view(), game.search_actions(game.controller))
        HypothesisThreatRanker(((game,), (other,)), space)
        with self.assertRaisesRegex(ValueError, "one identity"):
            HypothesisThreatRanker(((game, other),), space)

    def test_invalid_masses_and_empty_groups_are_rejected(self):
        for groups in ((), ((),)):
            with self.assertRaises(ValueError):
                HypothesisThreatRanker(groups, None)
        for masses in ((0,), (-1,), (True,), (float("nan"),), (float("inf"),), (), (1, 2)):
            with self.subTest(masses=masses), self.assertRaises(ValueError):
                HypothesisThreatRanker(((object(),),), None, weights=masses)


if __name__ == "__main__":
    unittest.main()
