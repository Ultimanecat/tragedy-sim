"""Saved final observations permit independent, repeatable evidence ablations."""

from copy import deepcopy
from dataclasses import asdict
import json
import unittest

from benchmarks.ai_factor_audit import reanalyze_final
from tragedy_sim import Game
from tragedy_sim.belief import HiddenWorldHypothesis
from tragedy_sim.effects.movement import move
from tragedy_sim.scenario_library import ScenarioLibrary


class FinalAuditTests(unittest.TestCase):
    def test_json_roundtrip_recompiles_view_and_uses_saved_truth(self):
        game = Game(ScenarioLibrary().get("official-btx-10-prologue"))
        move(game, {"target": "rich", "location": "shrine"})
        game._begin_night()
        report = json.loads(json.dumps({
            "scenario": "not-in-the-library",
            "decision_digest": "fixture",
            "truth_setup": asdict(HiddenWorldHypothesis.from_scenario(game.scenario)),
            "final_context": {"view": game.protagonist_team_view(),
                              "witnesses": [{"kind": "invalid-cached-inference"}]},
        }))
        original = deepcopy(report)
        enabled = reanalyze_final(report)
        disabled = reanalyze_final(report, disabled_witness_sources=(
            "public_btx_mandatory_serial_absence",))
        self.assertEqual(enabled["truth_source"], "saved_run")
        self.assertTrue(enabled["truth_hard_compatible"])
        self.assertIn("public_btx_mandatory_serial_absence", enabled["witness_sources"])
        self.assertNotIn("public_btx_mandatory_serial_absence", disabled["witness_sources"])
        self.assertNotEqual(enabled["guesses"].get("rich"), "serial")
        self.assertEqual(report, original)

    def test_old_report_without_final_view_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError, "no saved final protagonist view"):
            reanalyze_final({"scenario": "example", "final_context": {}})
