"""P1/P2 defense value tests."""

import unittest

from tragedy_sim.day_game.defense_value import (
    DefenseValue, DefenseValueWeights, filter_hard_actions, satisficed_survival,
    score_defense_value)
from tragedy_sim.day_game.threats import ThreatAssessment


def threat(target="girl", *, hard=True, active=True):
    return ThreatAssessment(
        target=target, failure_kind="character_loss", role="key",
        confidence=1.0, severity=1.0, deadline=None, active_now=active,
        source="hard_role" if hard else "posterior_role", hard=hard)


class HardThreatFilterTests(unittest.TestCase):
    def test_no_hard_threat_keeps_all_actions(self):
        result = filter_hard_actions(["a", "b"], (threat(hard=False),),
                                     {"a": {"girl"}, "b": {"outsider"}})
        self.assertFalse(result.filtered)
        self.assertEqual(result.allowed, ("a", "b"))

    def test_only_actions_covering_required_target_survive(self):
        result = filter_hard_actions(["a", "b", "c"], (threat(),),
                                     {"a": {"girl"}, "b": {"outsider"},
                                      "c": {"girl", "rich"}})
        self.assertTrue(result.filtered)
        self.assertTrue(result.feasible)
        self.assertEqual(result.allowed, ("a", "c"))
        self.assertEqual(result.required_targets, frozenset({"girl"}))

    def test_inactive_hard_threat_is_not_filtered(self):
        result = filter_hard_actions(["a"], (threat(active=False),),
                                     {"a": {"outsider"}})
        self.assertFalse(result.filtered)
        self.assertEqual(result.allowed, ("a",))

    def test_no_feasible_defense_returns_all_actions(self):
        result = filter_hard_actions(["a"], (threat(),),
                                     {"a": {"outsider"}})
        self.assertTrue(result.filtered)
        self.assertFalse(result.feasible)
        self.assertEqual(result.allowed, ("a",))


class SurvivalSaturationTests(unittest.TestCase):
    def test_below_target_scales_linearly(self):
        self.assertAlmostEqual(satisficed_survival(0.4, 0.8), 0.5)

    def test_at_and_above_target_saturates(self):
        self.assertEqual(satisficed_survival(0.8, 0.8), 1.0)
        self.assertEqual(satisficed_survival(0.95, 0.8), 1.0)

    def test_invalid_values_are_rejected(self):
        with self.assertRaises(ValueError):
            satisficed_survival(1.1)
        with self.assertRaises(ValueError):
            satisficed_survival(0.5, 0)


class DefenseValueScoreTests(unittest.TestCase):
    def test_hard_constraint_dominates_soft_score(self):
        lucky = DefenseValue(True, 0.2, 0.0, 0.0, 0.0, 0.0)
        unsafe = DefenseValue(False, 1.0, 10.0, 10.0, 10.0, 0.0)
        self.assertGreater(score_defense_value(lucky), score_defense_value(unsafe))

    def test_extra_survival_above_target_has_no_extra_credit(self):
        base = DefenseValue(True, 0.9, 0.2, 0.1, 0.1, 0.0)
        better = DefenseValue(True, 1.0, 0.2, 0.1, 0.1, 0.0)
        self.assertEqual(score_defense_value(base), score_defense_value(better))

    def test_expected_loss_and_weights_apply(self):
        value = DefenseValue(True, 0.8, 0.5, 0.0, 0.0, 0.25)
        weights = DefenseValueWeights(survival=2, long_term=2, expected_loss=4,
                                      hard_bonus=100)
        expected = 100 + 2 * 1.0 + 2 * 0.5 - 4 * 0.25
        self.assertAlmostEqual(score_defense_value(value, weights), expected)


if __name__ == "__main__":
    unittest.main()
