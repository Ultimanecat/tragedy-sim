"""R3 acceptance tests for independently composed FS and BTX rulesets."""

import json
import unittest

from tragedy_sim import Game
from tragedy_sim.domain import ActionOffer, InformationState, ScriptDefinition
from tragedy_sim.rulesets.registry import get_ruleset
from tragedy_sim.scenario import example_scenario


class BasicRulesetMigrationTests(unittest.TestCase):
    def test_fs_and_btx_have_dedicated_definitions_and_basic_effects_only(self):
        for module in ("FS", "BTX"):
            with self.subTest(module=module):
                definition = get_ruleset(module)
                self.assertEqual(definition.id, module)
                self.assertIn(f"rulesets.{module.lower()}.scenario",
                              definition.validator.__module__)
                self.assertFalse(definition.effects.handles("wm_spell"))
                self.assertFalse(definition.effects.handles("ahr_world_shift"))
                self.assertTrue(all("rulesets.legacy" not in operation.__module__
                                    for operation in definition.operations.values()))
        self.assertFalse(get_ruleset("FS").final_guess)
        self.assertTrue(get_ruleset("BTX").final_guess)

    def test_script_definition_is_immutable_and_shared_by_search_clones(self):
        game = Game(example_scenario("BTX"))
        clone = game.clone()
        self.assertIsInstance(game.script, ScriptDefinition)
        self.assertIs(game.script, clone.script)
        self.assertIs(game.ruleset, clone.ruleset)
        with self.assertRaises(TypeError):
            game.script.cast["student"] = "ordinary"
        clone.state.characters["student"].goodwill += 1
        self.assertNotEqual(clone.state.characters["student"].goodwill,
                            game.state.characters["student"].goodwill)

    def test_information_state_is_detached_immutable_and_contains_no_private_trace(self):
        game = Game()
        info = game.information_state("a")
        self.assertIsInstance(info, InformationState)
        self.assertEqual(info.key, game.state_key("a"))
        with self.assertRaises(TypeError):
            info.projection["characters"]["student"]["goodwill"] = 99
        serialized = json.dumps(info.to_dict(), ensure_ascii=False)
        self.assertNotIn("resolution_traces", serialized)
        self.assertNotIn("activation_history", serialized)
        self.assertNotIn("secret", serialized)

    def test_typed_offer_uses_the_same_transition_as_command_dispatch(self):
        game = Game()
        offer = game.action_offers("m")[0]
        self.assertIsInstance(offer, ActionOffer)
        result = game.transition(offer)
        direct = game.simulate(**offer.command)
        self.assertEqual(result.game.state_key("m"), direct.game.state_key("m"))
        self.assertEqual(game.state.phase, "day_start")


if __name__ == "__main__":
    unittest.main()
