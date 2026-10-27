"""Ability defense chain tests."""

import unittest

from tragedy_sim.day_game.defense_capabilities import (
    counter_reduction_capabilities, plan_counter_defense, scenario_capabilities)
from tragedy_sim.scenario_library import ScenarioLibrary


def btx01():
    return ScenarioLibrary().get("official-btx-01-machina-solar-cogwheel")


def view(**characters):
    return {"characters": characters}


class DefenseCapabilityTests(unittest.TestCase):
    def test_btx01_has_forensic_transfer(self):
        capabilities = counter_reduction_capabilities(btx01())
        transfers = [item for item in capabilities if item.kind == "transfer"]
        self.assertTrue(any(item.actor == "forensic" for item in transfers))

    def test_plan_sets_up_goodwill_movement_and_transfer(self):
        plan = plan_counter_defense(
            btx01(),
            view(forensic={"alive": True, "present": True, "location": "city",
                           "goodwill": 0, "paranoia_limit": 3},
                 rich={"alive": True, "present": True, "location": "school",
                       "paranoia": 2, "paranoia_limit": 1},
                 class_rep={"alive": True, "present": True, "location": "school",
                            "paranoia": 0, "paranoia_limit": 2},
                 outsider={"alive": True, "present": True, "location": "school",
                           "paranoia": 0, "paranoia_limit": 2}),
            target="rich", need=2)
        self.assertIsNotNone(plan.capability)
        kinds = [step.kind for step in plan.steps]
        self.assertIn("setup_goodwill", kinds)
        self.assertIn("move", kinds)
        self.assertIn("use_transfer", kinds)

    def test_ready_forensic_needs_only_transfer(self):
        plan = plan_counter_defense(
            btx01(),
            view(forensic={"alive": True, "present": True, "location": "school",
                           "goodwill": 2},
                 rich={"alive": True, "present": True, "location": "school",
                       "paranoia": 1, "paranoia_limit": 1},
                 class_rep={"alive": True, "present": True, "location": "school",
                            "paranoia": 0, "paranoia_limit": 2},
                 outsider={"alive": True, "present": True, "location": "school",
                           "paranoia": 0, "paranoia_limit": 2}),
            target="rich", need=1)
        self.assertEqual([step.kind for step in plan.steps], ["use_transfer"])

    def test_fs_scenario_has_no_transfer_chain(self):
        scenario = ScenarioLibrary().get("official-fs-01-first-script")
        plan = plan_counter_defense(
            scenario,
            view(rich={"alive": True, "present": True, "location": "school",
                       "paranoia": 1}),
            target="rich", need=1)
        self.assertIsNone(plan.capability)
        self.assertIn("no transfer", plan.blocked_reason or "")


if __name__ == "__main__":
    unittest.main()
