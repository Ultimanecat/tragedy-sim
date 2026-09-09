"""Tests for explicit, non-hook effect handler composition."""

import unittest
import json
from copy import deepcopy

from tragedy_sim import Game, RuleError
from tragedy_sim.domain import LegacyEffect, RuleSource, SourcedEffect
from tragedy_sim.effects.vocabulary import op, option
from tragedy_sim.scenario import example_scenario

from tragedy_sim.effect_resolver import CORE_EFFECT_HANDLERS, EffectHandlerRegistry


class EffectHandlerRegistryTests(unittest.TestCase):
    def test_moving_ex_preserves_rule_source_and_serializable_trace(self):
        game = Game(example_scenario("MZ"))
        game.ex_cards["student"] = 1
        game._return_phase = "day_start"
        game._queue = [SourcedEffect(
            LegacyEffect("move_ex", {"source": "student", "target": "doctor"}),
            RuleSource("mz.ex_placement"),
        )]
        game._drain()
        trace = game.resolution_traces[-1].to_dict()
        self.assertEqual(trace["source"], "mz.ex_placement")
        self.assertEqual((game.ex_cards["student"], game.ex_cards["doctor"]), (0, 1))
        self.assertEqual(trace["observations"][0]["data"]["source"], "student")
        json.dumps(trace)
        self.assertNotIn("mz.ex_placement", json.dumps(game.view("a")))

    def test_unknown_followup_rolls_back_effects_and_traces_atomically(self):
        game = Game()
        game._return_phase = "goodwill"
        game._queue = [op("choice", options=[option("执行效果", [
            op("counter", target="student", counter="goodwill", amount=1),
            op("unknown_effect"),
        ])])]
        game._drain()
        before = deepcopy(game.__dict__)
        with self.assertRaisesRegex(RuleError, "不支持的内部效果"):
            game.dispatch("m", "choose", index=1)
        self.assertEqual(game.__dict__, before)

    def test_registry_is_immutable_and_extensions_are_explicit(self):
        calls = []
        extension = CORE_EFFECT_HANDLERS.extended({
            "test.effect": lambda game, effect: calls.append((game, effect["value"])),
        })
        marker = object()
        extension.resolve(marker, {"kind": "test.effect", "value": 3})
        self.assertEqual(calls, [(marker, 3)])
        self.assertFalse(CORE_EFFECT_HANDLERS.handles("test.effect"))
        with self.assertRaises(TypeError):
            extension.handlers["another"] = lambda game, effect: None
        with self.assertRaises(ValueError):
            CORE_EFFECT_HANDLERS.extended({"counter": lambda game, effect: None})

    def test_unknown_effect_fails_closed(self):
        registry = EffectHandlerRegistry({})
        with self.assertRaisesRegex(KeyError, "missing"):
            registry.resolve(object(), {"kind": "missing"})


if __name__ == "__main__":
    unittest.main()
