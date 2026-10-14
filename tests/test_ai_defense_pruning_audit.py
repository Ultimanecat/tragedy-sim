"""Do not turn apparently useless dark-card responses into unsafe pruning."""

from copy import deepcopy
import unittest

from benchmarks.ai_defense_pruning_audit import action_domains, audit_game, destination, enumerate_plans
from tests.test_dark_attack_scenarios import threat_root
from tragedy_sim.dark_attack_scenarios import with_dark_bundle
from tragedy_sim.engine import Placement
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent


class DefensePruningAuditTests(unittest.TestCase):
    def test_zero_paranoia_decrease_kept_when_black_can_increase(self):
        game = threat_root()
        game.state.characters["girl"].paranoia = 0
        action = ("a", "p-1", "girl")
        self.assertNotIn(action, action_domains(game, "literal")[0])
        self.assertIn(action, action_domains(game, "conditional")[0])
        game = with_dark_bundle(game, (Placement("m", "p1a", "girl"),
                                       Placement("m", "i1", "worker"), Placement("m", "h", "shrine")))
        plan = ({"actor": "a", "action": "play", "card": "p-1", "target": "girl"},
                {"actor": "b", "action": "play", "card": "fi", "target": "worker"},
                {"actor": "c", "action": "play", "card": "g1", "target": "doctor"})
        after = ParticleEnsembleProtagonistAgent._apply_bundle(game, plan)
        after.resolve()
        after._resolve_counters()
        self.assertEqual(after.state.characters["girl"].paranoia, 0)
        after = game.search_clone()
        after.dispatch("a", "play", card="g1", target="girl")
        after.dispatch("b", "play", card="fi", target="worker")
        after.dispatch("c", "play", card="g1", target="doctor")
        after.resolve()
        after._resolve_counters()
        self.assertEqual(after.state.characters["girl"].paranoia, 1)

    def test_forbidden_solo_destination_may_have_valid_combined_destination(self):
        game = threat_root()
        game.state.characters["girl"].forbidden = ("shrine",)
        action = ("a", "h", "girl")
        self.assertEqual(destination(game, "girl", ("h",)), "hospital")
        self.assertEqual(destination(game, "girl", ("h", "v")), "school")
        self.assertEqual(destination(game, "girl", ("h", "h")), "hospital")
        self.assertNotIn(action, action_domains(game, "literal")[0])
        self.assertIn(action, action_domains(game, "conditional")[0])
        game = with_dark_bundle(game, (Placement("m", "v", "girl"),
                                       Placement("m", "i1", "worker"), Placement("m", "h", "shrine")))
        plan = ({"actor": "a", "action": "play", "card": "h", "target": "girl"},
                {"actor": "b", "action": "play", "card": "fi", "target": "worker"},
                {"actor": "c", "action": "play", "card": "g1", "target": "doctor"})
        after = ParticleEnsembleProtagonistAgent._apply_bundle(game, plan)
        after.resolve()
        self.assertEqual(after.state.characters["girl"].location, "school")

    def test_untargeted_movement_forbid_and_board_actions_are_filtered(self):
        game = threat_root()
        domain = action_domains(game, "conditional")[0]
        self.assertNotIn(("a", "fm", "doctor"), domain)
        self.assertNotIn(("a", "fi", "school"), domain)
        self.assertIn(("a", "fi", "shrine"), domain)
        self.assertFalse(any(card != "fi" and target in game.state.locations for _, card, target in domain))

    def test_joint_enumeration_retains_distinct_seats_and_optional_forbid_limit(self):
        domains = ((("a", "fi", "girl"), ("a", "h", "worker")),
                   (("b", "fi", "worker"), ("b", "h", "girl")),
                   (("c", "g1", "doctor"),))
        self.assertEqual(len(list(enumerate_plans(domains))), 2)
        self.assertEqual(len(list(enumerate_plans(domains, forbid_limit=1))), 1)

    def test_measurement_does_not_change_game_and_rejects_unvalidated_echoes(self):
        game = threat_root()
        before = deepcopy(game.view("m"))
        report = audit_game(game, engine_samples=2, repeats=1)
        self.assertEqual(before, game.view("m"))
        self.assertEqual(report["engine"]["plans"], 2)
        self.assertGreater(report["modes"]["raw"]["joint_plans"], report["modes"]["conditional"]["joint_plans"])
        game.state.characters["doctor"].echo_board_actions = True
        with self.assertRaisesRegex(ValueError, "echo"):
            action_domains(game, "conditional")


if __name__ == "__main__":
    unittest.main()
