"""Tests for explicit, non-hook effect handler composition."""

import unittest

from tragedy_sim.effect_resolver import CORE_EFFECT_HANDLERS, EffectHandlerRegistry


class EffectHandlerRegistryTests(unittest.TestCase):
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
