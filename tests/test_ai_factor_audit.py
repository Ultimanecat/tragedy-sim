"""Saved final observations permit independent, repeatable evidence ablations."""

from copy import deepcopy
from dataclasses import asdict
import json
import unittest
from unittest.mock import patch

from benchmarks.ai_factor_audit import audit_match, reanalyze_final
from benchmarks.ai_self_play import MatchResult, _policy_offer
from tragedy_sim import Game
from tragedy_sim.belief import HiddenWorldHypothesis
from tragedy_sim.effects.movement import move
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.search import SearchBudget


class FinalAuditTests(unittest.TestCase):
    def test_action_world_capture_is_opt_in_and_preserves_decision(self):
        selected = []
        def short_play(scenario_id, seed, *args, **kwargs):
            game = Game(ScenarioLibrary().get(scenario_id))
            while game.state.phase != "protagonists":
                game = game.search_transition(game.search_actions(game.controller)[0])
            agent = ParticleEnsembleProtagonistAgent(
                SearchBudget(node_limit=2, seed=seed), particle_count=2)
            offer = agent.choose_action(
                participant="team", view=game.protagonist_team_view(),
                offers=[_policy_offer(game, action)
                        for action in game.action_offers(game.controller)])
            selected.append(offer)
            return MatchResult(scenario_id, "fixture", "FS", 1, "standard",
                               "fixed", "particle_ensemble", seed, "none", 1, 0,
                               2, 0.0, decision_digest="fixture")
        with patch("benchmarks.ai_factor_audit.play", short_play):
            plain = audit_match("official-fs-01-first-script", 1)
            captured = audit_match("official-fs-01-first-script", 1,
                                   capture_action_worlds=True)
        self.assertEqual(selected[0], selected[1])
        self.assertEqual(plain["action_contexts"], [])
        contexts = captured["action_contexts"]
        self.assertEqual(len(contexts), 1)
        self.assertEqual(len(contexts[0]["worlds"]), 2)
        self.assertTrue(all(item.get("card") is None
                            for item in contexts[0]["view"]["pending"]))
        self.assertTrue(all(item["card"] is not None
                            for world in contexts[0]["worlds"]
                            for item in world["pending"]))

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
