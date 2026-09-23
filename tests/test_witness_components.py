import unittest

from tragedy_sim.game import Game
from tragedy_sim.scenario import example_scenario
from tragedy_sim.witness import (FsbtxWitnessCompiler,
                                 RulesetWitnessCompiler)
from tragedy_sim.witness_rules.common_incidents import (
    compile_direct_culprits, compile_effect_locations,
    compile_suicide_victims)
from tragedy_sim.witness_rules.common_public import (
    compile_goodwill_refusals, compile_incident_status,
    compile_public_reveals)
from tragedy_sim.witness_components import (RULESET_WITNESS_COMPONENTS,
                                             components_for,
                                             registered_sources)


class WitnessComponentRegistryTests(unittest.TestCase):
    def test_rulesets_explicitly_compose_shared_and_specific_components(self):
        fs = components_for("FS")
        btx = components_for("BTX")
        fs_by_id = {item.component_id: item for item in fs}
        btx_by_id = {item.component_id: item for item in btx}

        self.assertIs(fs_by_id["common.incident_status"],
                      btx_by_id["common.incident_status"])
        self.assertIn("fs.key_death", fs_by_id)
        self.assertNotIn("fs.key_death", btx_by_id)
        self.assertIn("btx.goodwill_forbid", btx_by_id)
        self.assertNotIn("btx.goodwill_forbid", fs_by_id)
        self.assertEqual(components_for("MZ"), ())

    def test_component_order_preserves_legacy_fs_and_btx_order(self):
        self.assertEqual(
            [item.component_id for item in components_for("FS")], [
                "fs.key_death", "common.intrigue_forbid",
                "common.day_end_hero_death", "common.accepted_goodwill",
                "common.suicide_victim", "common.suicide_prevented",
                "common.guru_incident", "common.effective_incident",
                "common.direct_incident_culprit",
                "common.incident_effect_location", "common.public_reveals",
                "common.goodwill_refusal", "common.incident_status",
                "common.death_clues", "common.loop_end_clues",
            ])
        self.assertEqual(
            [item.component_id for item in components_for("BTX")][:7], [
                "btx.goodwill_forbid", "btx.time_traveler_death_prevention",
                "btx.virus_reveal_thresholds", "btx.threads_loop_start",
                "common.intrigue_forbid", "common.day_end_hero_death",
                "btx.immediate_death_loss",
            ])

    def test_all_compiled_sources_are_declared_by_the_ruleset(self):
        for module in ("FS", "BTX"):
            view = Game(example_scenario(module)).view("a")
            view["known_roles"] = {"girl": {"role": "ordinary"}}
            view["known_culprits"] = {"2": "doctor"}
            view["known_plots"] = ["protect" if module == "FS" else "sealed"]
            compiled = RulesetWitnessCompiler().compile(view)
            self.assertTrue({item.source for item in compiled}
                            <= registered_sources(module))

    def test_component_can_be_disabled_without_disabling_its_sources(self):
        view = Game(example_scenario("BTX")).view("a")
        view["events"] = [{
            "kind": "incident_status", "loop": 1, "round": 2,
            "incident": "missing", "happened": True,
        }, {
            "kind": "character_moved", "loop": 1, "round": 2,
            "target": "doctor", "location": "city",
        }]
        source = "public_missing_moved_culprit"
        self.assertTrue(any(item.source == source for item in
                            FsbtxWitnessCompiler().compile(view)))
        disabled = FsbtxWitnessCompiler(disabled_components={
            "common.direct_incident_culprit"}).compile(view)
        self.assertFalse(any(item.source == source for item in disabled))

    def test_shared_components_compile_directly_in_both_rulesets(self):
        for module in ("FS", "BTX"):
            view = Game(example_scenario(module)).view("a")
            view["known_roles"] = {"student": {"role": "ordinary"}}
            view["known_culprits"] = {"2": "student"}
            view["events"] = [
                {"kind": "goodwill_refused", "source": "student",
                 "loop": 1, "round": 1},
                {"kind": "incident_status", "incident": "suicide",
                 "happened": False, "loop": 1, "round": 1},
            ]
            direct = [*compile_public_reveals(view),
                      *compile_goodwill_refusals(view),
                      *compile_incident_status(view)]
            source_set = {item.source for item in direct}
            via_registry = [
                item for item in RulesetWitnessCompiler().compile(view)
                if item.source in source_set]
            self.assertEqual(direct, via_registry)
            self.assertEqual(len(direct), 4)

    def test_every_registered_component_is_a_standalone_callable(self):
        for module in ("FS", "BTX"):
            for component in components_for(module):
                self.assertTrue(callable(component.compile),
                                component.component_id)

    def test_incident_components_are_reused_in_fs_and_btx(self):
        for module in ("FS", "BTX"):
            view = Game(example_scenario(module)).view("a")
            view["events"] = [
                {"kind": "incident_status", "incident": "suicide",
                 "happened": True, "loop": 1, "round": 2},
                {"kind": "character_died", "target": "student",
                 "loop": 1, "round": 2},
                {"kind": "incident_ended", "loop": 1, "round": 2},
                {"kind": "incident_status", "incident": "missing",
                 "happened": True, "loop": 1, "round": 3},
                {"kind": "character_moved", "target": "student",
                 "loop": 1, "round": 3},
            ]
            direct = [*compile_suicide_victims(view),
                      *compile_direct_culprits(view),
                      *compile_effect_locations(view)]
            self.assertEqual({item.source for item in direct}, {
                "public_suicide_victim", "public_missing_moved_culprit"})
            source_set = {item.source for item in direct}
            via_registry = [
                item for item in RulesetWitnessCompiler().compile(view)
                if item.source in source_set]
            self.assertEqual(direct, via_registry)

    def test_registry_has_no_duplicate_component_ids_per_ruleset(self):
        for module, components in RULESET_WITNESS_COMPONENTS.items():
            ids = [item.component_id for item in components]
            self.assertEqual(len(ids), len(set(ids)), module)


if __name__ == "__main__":
    unittest.main()
