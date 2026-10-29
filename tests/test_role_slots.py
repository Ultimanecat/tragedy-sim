"""role_slots module-capability validation (code review follow-up)."""

import unittest

from tragedy_sim.engine import RuleError
from tragedy_sim.rulesets.scenario_roles import role_slot_pool
from tragedy_sim.scenario import example_scenario, validate_scenario
from tragedy_sim.scenario_library import ScenarioLibrary


class RoleSlotPoolTests(unittest.TestCase):
    def test_pool_is_module_data_driven(self):
        self.assertIn("friend", role_slot_pool("FS"))
        self.assertIn("curmudgeon", role_slot_pool("FS"))  # hideous adds 0-2
        self.assertNotIn("prophet", role_slot_pool("FS"))
        self.assertNotIn("prophet", role_slot_pool("BTX"))
        self.assertNotIn("magician", role_slot_pool("BTX"))
        self.assertIn("witch", role_slot_pool("BTX"))

    def test_module_specific_roles_stay_in_their_module(self):
        self.assertIn("magician", role_slot_pool("MZ"))
        self.assertIn("prophet", role_slot_pool("MZ"))
        self.assertIn("immortal", role_slot_pool("MZ"))
        self.assertIn("ahr_puppet", role_slot_pool("AHR"))
        self.assertNotIn("ahr_puppet", role_slot_pool("MZ"))
        self.assertIn("deep_one", role_slot_pool("WM"))

    def test_unknown_module_has_empty_pool(self):
        self.assertEqual(role_slot_pool("NOPE"), set())


class RoleSlotValidationTests(unittest.TestCase):
    def test_fs_script_cannot_declare_unimplemented_role(self):
        scenario = example_scenario("FS")
        scenario["role_slots"] = {"prophet": 1}
        with self.assertRaisesRegex(RuleError, "prophet"):
            validate_scenario(scenario)

    def test_btx_script_cannot_declare_other_module_role(self):
        scenario = example_scenario("BTX")
        scenario["role_slots"] = {"ahr_puppet": 1}
        with self.assertRaisesRegex(RuleError, "ahr_puppet"):
            validate_scenario(scenario)

    def test_official_scripts_using_role_slots_still_validate(self):
        library = ScenarioLibrary()
        for scenario_id in ("official-mc-10-unknowns-of-academic-city",
                            "official-mz-07-spinning-duplicate-spiral"):
            with self.subTest(scenario_id):
                scenario = library.get(scenario_id)
                self.assertIn("role_slots", scenario)
                validate_scenario(scenario)

    def test_ordinary_role_is_still_rejected(self):
        scenario = example_scenario("FS")
        scenario["role_slots"] = {"ordinary": 1}
        with self.assertRaisesRegex(RuleError, "非平民"):
            validate_scenario(scenario)


if __name__ == "__main__":
    unittest.main()
