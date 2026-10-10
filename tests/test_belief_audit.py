"""Developer belief logs are optional, stable and separate from inference."""
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch
import unittest

from benchmarks.ai_self_play import _policy_offer
from tragedy_sim.belief_audit import BeliefAuditTrail, describe_witness
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.search import SearchBudget
from tragedy_sim.witness import PublicEvidenceLedger, PublicWitness, WitnessStrength
from tests.test_particle_ensemble import protagonist_position


class BeliefAuditTests(unittest.TestCase):
    def test_projection_error_is_diagnostic_not_an_action_failure(self):
        trail = BeliefAuditTrail()
        view = {**self.view, "characters": {"girl": {}}, "schedule": []}
        with patch("tragedy_sim.belief_matrix.BeliefMatrixProjection.from_view",
                   side_effect=ValueError("conflicting evidence")):
            trail.record_samples(view, (), {}, 0)
        self.assertIn("conflicting evidence", trail.to_text())
        self.assertEqual(trail.entries[-1]["belief_matrix_error"], "conflicting evidence")

    def setUp(self):
        self.view = {"module": "BTX", "loop": 1, "round": 6,
                     "phase": "loop_end", "timing": "loop_end", "events": []}

    def test_public_fact_mirror_is_not_new_evidence_on_next_day(self):
        trail = BeliefAuditTrail()
        fact = PublicWitness("role_is", "girl", "friend", 1, 6,
                             "loop_end", "public_role_reveal")
        trail.observe(self.view, (fact,))
        trail.observe({**self.view, "loop": 2, "round": 1},
                      (replace(fact, loop=2, day=1, timing="protagonists"),))
        self.assertEqual(len(trail.entries), 1)
        self.assertIn("亲友", trail.to_text())
        self.assertIn("来源：public_role_reveal", trail.to_text())

    def test_repeated_soft_observation_and_removal_are_counted(self):
        trail = BeliefAuditTrail()
        fact = PublicWitness("role_pressure", "key", {"candidates": ("girl",)},
                             1, 6, "incident", "test", WitnessStrength.SOFT)
        trail.observe(self.view, (fact,))
        trail.observe(self.view, (fact, fact))
        self.assertEqual(trail.entries[-1]["changes"][0]["operation"], "confirmed")
        self.assertEqual(trail.entries[-1]["changes"][0]["observations"], 1)
        trail.observe(self.view, ())
        self.assertEqual(trail.entries[-1]["changes"][0]["operation"], "removed")
        self.assertEqual(trail.entries[-1]["changes"][0]["observations"], 2)
        self.assertIn("软", trail.to_text())

    def test_route_and_sample_text_preserve_uncertainty_and_snapshot(self):
        fact = PublicWitness("role_route_pressure", "immediate_death_loss",
                             {"key": ("girl",), "factor": ("girl",)},
                             1, 6, "incident", "public_btx_immediate_death_loss")
        description = describe_witness(fact)
        self.assertIn("或", description)
        self.assertIn("不安定因子", description)
        trail = BeliefAuditTrail()
        rows = [{"character": "girl", "counts": {"friend": 12}}]
        trail.record_samples(self.view, rows, {6: ("girl",)}, 12)
        rows[0]["counts"]["friend"] = 0
        self.assertIn("亲友 12", trail.to_text())
        self.assertIn("不是完整后验概率", trail.to_text())
        self.assertIn("第6天当事人硬约束候选", trail.to_text())

    def test_enabling_audit_does_not_change_fixed_work_action(self):
        game = protagonist_position()
        offers = [_policy_offer(game, action) for action in game.action_offers(game.controller)]
        choices = []
        for enabled in (False, True):
            agent = ParticleEnsembleProtagonistAgent(
                SearchBudget(node_limit=2, seed=4), particle_count=2, rng_seed=4)
            if enabled:
                agent.evidence_ledger.audit = BeliefAuditTrail()
            choices.append(agent.choose_action(participant="team",
                                              view=deepcopy(game.protagonist_team_view()),
                                              offers=offers))
        self.assertEqual(choices[0], choices[1])
        samples = [row for row in agent.evidence_ledger.audit.entries if "sampled_roles" in row]
        self.assertEqual(len(samples), 1)
        self.assertTrue(samples[0]["sampled_dark_cards"])
        self.assertTrue(samples[0]["sampled_culprits"])
        self.assertIn("roles", samples[0]["belief_matrix"])
        self.assertIn("信念矩阵", agent.evidence_ledger.audit.to_text())
        self.assertIsNone(PublicEvidenceLedger().audit)


if __name__ == "__main__":
    unittest.main()
