from copy import deepcopy
import unittest

from tragedy_sim.belief_dark_constraints import dark_card_domains, has_distinct_assignment
from tragedy_sim.belief_matrix import BeliefContradiction, BeliefMatrixProjection, HardStatus


class DarkConstraintTests(unittest.TestCase):
    def setUp(self):
        self.view = {"module": "FS", "loop": 1, "round": 2,
                     "characters": {"girl": {}, "doctor": {}, "student": {}},
                     "pending": [{"actor": "m", "target": "girl"},
                                 {"actor": "m", "target": "hospital"},
                                 {"actor": "m", "target": "doctor"}],
                     "discarded": {"m": ["i2", "d"]}}

    def test_used_once_cards_are_never_but_ineffective_board_bluffs_remain(self):
        projection = BeliefMatrixProjection.from_view(self.view, ())
        self.assertEqual(projection.dark_cards["1"]["i2"].hard_status, HardStatus.NEVER)
        self.assertEqual(projection.dark_cards["1"]["h"].hard_status, HardStatus.UNKNOWN)
        self.assertEqual(projection.dark_targets["1"], "hospital")
        self.assertEqual(projection.dark_distinct_slots, ("0", "1", "2"))

    def test_visible_card_excludes_that_physical_card_in_other_slots(self):
        self.view["pending"][0]["card"] = "p1a"
        projection = BeliefMatrixProjection.from_view(self.view, ())
        self.assertEqual(projection.dark_cards["0"]["p1a"].hard_status, HardStatus.ALWAYS)
        self.assertEqual(projection.dark_cards["1"]["p1a"].hard_status, HardStatus.NEVER)
        self.assertEqual(projection.dark_cards["1"]["p1b"].hard_status, HardStatus.UNKNOWN)

    def test_hall_support_is_stronger_than_pairwise_card_exclusion(self):
        domains = {"0": {"a", "b"}, "1": {"a", "b"}, "2": {"a", "b", "c"}}
        self.assertTrue(has_distinct_assignment(domains))
        self.assertFalse(has_distinct_assignment(domains, {"2": "a"}))
        self.assertTrue(has_distinct_assignment(domains, {"2": "c"}))
        self.assertFalse(has_distinct_assignment({"0": {"a"}, "1": {"a"}}))

    def test_duplicate_visible_cards_and_disabled_cards_are_contradictions(self):
        self.view["pending"][0]["card"] = "h"
        self.view["pending"][1]["card"] = "h"
        with self.assertRaises(BeliefContradiction):
            dark_card_domains(self.view)
        self.view["pending"][1].pop("card")
        self.view["public_setup"] = {"special_rules": {"disabled_mastermind_cards": ["h"]}}
        with self.assertRaises(BeliefContradiction):
            dark_card_domains(self.view)

    def test_revealed_current_card_can_already_be_discarded(self):
        self.view["pending"][0]["card"] = "i2"
        projection = BeliefMatrixProjection.from_view(self.view, ())
        self.assertEqual(projection.dark_cards["0"]["i2"].hard_status, HardStatus.ALWAYS)
        self.assertEqual(projection.dark_cards["1"]["i2"].hard_status, HardStatus.NEVER)

    def test_new_day_and_loop_rebuild_slot_state(self):
        original = deepcopy(self.view)
        old = BeliefMatrixProjection.from_view(self.view, ())
        next_loop = {**self.view, "loop": 2, "round": 1, "discarded": {"m": []}}
        new = BeliefMatrixProjection.from_view(next_loop, ())
        self.assertEqual(old.dark_cards["0"]["i2"].hard_status, HardStatus.NEVER)
        self.assertEqual(new.dark_cards["0"]["i2"].hard_status, HardStatus.UNKNOWN)
        cleared = BeliefMatrixProjection.from_view({**self.view, "pending": []}, ())
        self.assertEqual(cleared.dark_cards, {})
        self.assertEqual(self.view, original)

    def test_empirical_probabilities_do_not_replace_distinct_constraint(self):
        projection = BeliefMatrixProjection.from_view(self.view, (),
            dark_counts=({"slot": 0, "counts": {"h": 10}},))
        self.assertEqual(projection.dark_cards["0"]["h"].approx_probability, 1)
        self.assertEqual(projection.dark_cards["0"]["h"].hard_status, HardStatus.UNKNOWN)
        self.assertEqual(projection.dark_cards["0"]["v"].approx_probability, 0)
        self.assertEqual(projection.dark_cards["0"]["v"].hard_status, HardStatus.UNKNOWN)
