"""Offline causal audit preserves timing and information boundaries."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from benchmarks.ai_causal_audit import causal_evidence, compare_root
from tragedy_sim import Game
from tragedy_sim.belief import HiddenWorldHypothesis
from tragedy_sim.scenario_library import ScenarioLibrary
from tests.test_particle_ensemble import protagonist_position


class CausalAuditTests(unittest.TestCase):
    def test_suicide_identifies_culprit_and_friend_reveal_does_not_imply_key(self):
        game = Game(ScenarioLibrary().get("official-btx-04-young-womens-battlefield"))
        view = game.protagonist_team_view()
        view["round"] = 6
        view["characters"]["girl"]["paranoia"] = 3
        view["known_roles"] = {"girl": {"role": "friend"}}
        view["events"] = [
            {"kind": "loop_started", "loop": 1, "round": 1},
            {"kind": "incident_status", "incident": "suicide", "happened": True,
             "loop": 1, "round": 6},
            {"kind": "character_died", "target": "girl", "loop": 1, "round": 6},
            {"kind": "incident_ended", "loop": 1, "round": 6},
            {"kind": "day_ended", "loop": 1, "round": 6},
            {"kind": "role_revealed", "character": "girl", "role": "friend",
             "loop": 1, "round": 6},
            {"kind": "loop_lost", "loop": 1, "round": 6},
        ]
        result = causal_evidence(view, HiddenWorldHypothesis.from_scenario(game.scenario))
        self.assertEqual(result["culprit_options"][6], ("girl",))
        facts = result["causal_witnesses"]
        self.assertTrue(any(w["kind"] == "role_is" and w["value"] == "friend" for w in facts))
        self.assertFalse(any(w["source"] == "public_btx_immediate_death_loss" for w in facts))

    def test_immediate_death_retains_key_or_factor_routes_at_city_threshold(self):
        game = Game(ScenarioLibrary().get("official-btx-08-mirror-passcode"))
        for city in (0, 2):
            view = game.protagonist_team_view()
            view["events"] = [
                {"kind": "loop_started", "loop": 1, "round": 1},
                {"kind": "counter_changed", "target": "city", "counter": "intrigue",
                 "after": city, "loop": 1, "round": 1},
                {"kind": "character_died", "target": "girl", "loop": 1, "round": 1},
                {"kind": "loop_lost", "loop": 1, "round": 1},
            ]
            result = causal_evidence(view)
            fact = next(w for w in result["causal_witnesses"]
                        if w["source"] == "public_btx_immediate_death_loss")
            self.assertEqual(fact["value"]["key"], ("girl",))
            self.assertEqual("factor" in fact["value"], city >= 2)

    def test_same_root_probe_does_not_mutate_game_and_fair_input_is_authorized(self):
        game = protagonist_position()
        before = deepcopy(game.view("m"))
        fair_inputs = []
        from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
        original = ParticleEnsembleProtagonistAgent.choose_action

        def observe(self, *, participant, view, offers):
            fair_inputs.append(deepcopy(view))
            return original(self, participant=participant, view=view, offers=offers)

        with patch.object(ParticleEnsembleProtagonistAgent, "choose_action", observe):
            result = compare_root(game, nodes=2, worlds=2, time_limit_ms=10)
        self.assertEqual(game.view("m"), before)
        self.assertEqual(len(result["comparisons"]), 6)
        self.assertTrue(all(row["legal"] for row in result["comparisons"]))
        self.assertTrue(all(item["card"] is None for view in fair_inputs
                            for item in view["pending"] if item["actor"] == "m"))
        self.assertEqual({row["horizon"] for row in result["comparisons"]}, {"day", "loop"})


if __name__ == "__main__":
    unittest.main()
