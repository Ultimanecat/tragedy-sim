"""Developer belief logs are optional, stable and separate from inference."""
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch
import unittest

from benchmarks.ai_self_play import _policy_offer
from tragedy_sim.belief_audit import BeliefAuditTrail, describe_witness
from tragedy_sim.final_guess_probability import JointGuessProbabilitySolver
from tragedy_sim.belief import PublicEvidence
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.search import SearchBudget
from tragedy_sim.witness import PublicEvidenceLedger, PublicWitness, WitnessStrength
from tests.test_particle_ensemble import protagonist_position


class BeliefAuditTests(unittest.TestCase):
    def probability_view(self):
        return {"module": "BTX", "days": 2, "loops": 3, "round": 1, "loop": 1,
                "phase": "protagonists", "timing": "protagonists", "events": [],
                "characters": dict.fromkeys(("girl", "student", "doctor", "maiden"), {}),
                "schedule": []}

    def test_joint_probability_atomic_facts_removal_and_no_change(self):
        trail = BeliefAuditTrail(probability_solver=JointGuessProbabilitySolver())
        view = self.probability_view()
        before = deepcopy(view)
        trail.observe(view, ())
        first = trail.entries[-1]["guess_probability"]
        self.assertIsNone(first["before"])
        self.assertEqual(first["status"], "exact")
        guess = first["best_guess"]
        facts = tuple(PublicWitness("role_is", cid, role, 1, 1, "incident", "atomic")
                      for cid, role in guess.items())
        trail.observe(view, facts, context={"command_number": 3})
        second = trail.entries[-1]["guess_probability"]
        self.assertAlmostEqual(second["after"], 1)
        self.assertAlmostEqual(second["previous_guess_probability"], 1)
        self.assertAlmostEqual(second["delta"], 1 - first["after"])
        self.assertFalse(second["recommendation_changed"])
        self.assertEqual(len(trail.entries[-1]["changes"]), 4)
        self.assertEqual(trail.entries[-1]["context"]["command_number"], 3)
        with patch.object(trail.probability_solver, "solve", side_effect=AssertionError("must cache")):
            trail.observe({**view, "loop": 2, "round": 2}, facts)
        third = trail.entries[-1]["guess_probability"]
        self.assertTrue(third["cached"])
        self.assertEqual(third["delta"], 0)
        self.assertTrue(trail.entries[-1]["no_witness_changes"])
        trail.observe(view, ())
        self.assertEqual(trail.entries[-1]["guess_probability"]["after"], first["after"])
        self.assertLess(trail.entries[-1]["guess_probability"]["delta"], 0)
        self.assertEqual(view, before)
        self.assertIn("最优整套终猜概率", trail.to_text())
        self.assertEqual(trail.score_guess(first["best_guess"])["probability"], first["after"])

    def test_soft_multiplicity_changes_and_recommendation_switch(self):
        view = self.probability_view()
        trail = BeliefAuditTrail(probability_solver=JointGuessProbabilitySolver())
        trail.observe(view, ())
        old = trail.entries[-1]["guess_probability"]["best_guess"]
        # Exclude exactly the previous answer at one character.
        cid = "girl"
        fact = PublicWitness("role_not_in", cid, [old[cid]], 1, 1, "incident", "test")
        trail.observe(view, (fact,))
        result = trail.entries[-1]["guess_probability"]
        self.assertTrue(result["recommendation_changed"])
        self.assertEqual(result["previous_guess_probability"], 0)
        soft = PublicWitness("role_pressure", "brain", {"candidates": ["doctor"]},
                             1, 1, "incident", "soft", WitnessStrength.SOFT)
        trail.observe(view, (soft,))
        trail.observe(view, (soft, soft))
        result = trail.entries[-1]["guess_probability"]
        direct = trail.probability_solver.solve(PublicEvidence.from_view(view), (soft, soft))
        self.assertEqual(result["after"], direct.best_guess_probability)
        self.assertFalse(result["cached"])

    def test_private_knowledge_updates_without_witness_and_module_reset(self):
        view = self.probability_view()
        trail = BeliefAuditTrail(probability_solver=JointGuessProbabilitySolver())
        trail.observe(view, ())
        guess = trail.entries[-1]["guess_probability"]["best_guess"]
        trail.observe({**view, "protagonist_knowledge": {"initial_roles": guess}}, ())
        self.assertTrue(trail.entries[-1]["no_witness_changes"])
        self.assertEqual(trail.entries[-1]["guess_probability"]["after"], 1)
        trail.observe({**view, "module": "FS"}, ())
        self.assertTrue(trail.entries[-1]["module_reset"])
        self.assertIsNone(trail.entries[-1]["guess_probability"]["before"])

    def test_truth_query_does_not_enter_solver_or_recommendation(self):
        view = self.probability_view()
        solver = JointGuessProbabilitySolver()
        truth = dict.fromkeys(view["characters"], "brain")
        plain = BeliefAuditTrail(probability_solver=solver)
        diagnostic = BeliefAuditTrail(probability_solver=solver, offline_true_cast=truth)
        plain.observe(view, ())
        with patch.object(solver, "solve", wraps=solver.solve) as calls:
            diagnostic.observe(view, ())
        self.assertEqual(calls.call_args.args, (PublicEvidence.from_view(view), ()))
        row = diagnostic.entries[-1]["guess_probability"]
        self.assertEqual(row["offline_truth"]["after"], 0)
        self.assertNotIn("offline_truth", plain.entries[-1]["guess_probability"])
        self.assertEqual(row["best_guess"], plain.entries[-1]["guess_probability"]["best_guess"])
        self.assertEqual(row["after"], plain.entries[-1]["guess_probability"]["after"])

    def test_work_limit_and_diagnostic_failure_invalidate_deltas(self):
        view = self.probability_view()
        trail = BeliefAuditTrail(probability_solver=JointGuessProbabilitySolver(node_limit=1))
        trail.observe(view, ())
        self.assertEqual(trail.entries[-1]["guess_probability"]["status"], "work_limit")
        self.assertIsNone(trail.entries[-1]["guess_probability"]["after"])
        self.assertIsNone(trail.entries[-1]["guess_probability"]["delta"])
        with patch.object(trail.probability_solver, "solve", side_effect=RuntimeError("bad diagnostic")):
            trail.observe({**view, "module": "FS"}, ())
        self.assertEqual(trail.entries[-1]["guess_probability"]["status"], "diagnostic_error")
        self.assertIn("bad diagnostic", trail.to_text())
        trail.observe(view, ())
        self.assertIsNone(trail.entries[-1]["guess_probability"]["before"])

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
                agent.evidence_ledger.audit = BeliefAuditTrail(
                    probability_solver=JointGuessProbabilitySolver())
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
        probabilities = [row["guess_probability"] for row in agent.evidence_ledger.audit.entries
                         if "guess_probability" in row]
        self.assertTrue(probabilities)
        self.assertTrue(all(row["status"] == "exact" for row in probabilities))
        self.assertIsNone(PublicEvidenceLedger().audit)


if __name__ == "__main__":
    unittest.main()
