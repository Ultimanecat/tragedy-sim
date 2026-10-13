"""Main fair-policy defaults and explicit historical ablations agree end to end."""

from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch

from benchmarks import ai_mastermind_matrix, ai_self_play
from benchmarks.ai_self_play import MatchResult, _policy_offer, play
from tragedy_sim.belief import FactorizedBeliefState
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.search import SearchBudget
from tests.test_particle_ensemble import protagonist_position


class MatrixDefaultTests(unittest.TestCase):
    def test_main_defaults_and_explicit_legacy_are_separate(self):
        current = ParticleEnsembleProtagonistAgent().factorized_belief
        legacy = ParticleEnsembleProtagonistAgent(
            matrix_proposals=False, joint_culprits=False).factorized_belief
        self.assertTrue(current.matrix_proposals_enabled)
        self.assertTrue(current.joint_culprits_enabled)
        self.assertEqual(current.matrix_variant_policy, "prior")
        self.assertFalse(legacy.matrix_proposals_enabled)
        self.assertFalse(legacy.joint_culprits_enabled)
        # Historical ISMCTS/raw diagnostic state retains its baseline.
        raw = FactorizedBeliefState()
        self.assertFalse(raw.matrix_proposals_enabled)
        self.assertFalse(raw.joint_culprits_enabled)

    def test_default_plan_equals_explicit_matrix_on_exact_and_sampled_roots(self):
        for sid in ("official-fs-01-first-script", "official-tragic-aiplay-btx-01g"):
            with self.subTest(scenario=sid):
                game = protagonist_position(sid)
                view = game.protagonist_team_view()
                offers = [_policy_offer(game, a) for a in game.action_offers(game.controller)]
                budget = SearchBudget(node_limit=2, rollout_depth=4, seed=7)
                agents = [ParticleEnsembleProtagonistAgent(
                    budget, particle_count=4, rng_seed=7, **options)
                    for options in ({}, {"matrix_proposals": True, "joint_culprits": True})]
                decisions = []
                for agent in agents:
                    chosen = agent.choose_action(participant="team", view=view, offers=offers)
                    self.assertIn(chosen, offers)
                    self.assertIsNone(agent.last_trace.fallback)
                    decision = agent.decision_for_action(chosen)
                    self.assertEqual(len(decision.card_plan), 3)
                    decisions.append(decision)
                self.assertEqual(decisions[0], decisions[1])
                self.assertEqual(agents[0].last_trace.belief_roles, agents[1].last_trace.belief_roles)
                self.assertEqual(agents[0].last_trace.belief_culprits, agents[1].last_trace.belief_culprits)
                diagnostics = agents[0].factorized_belief.proposal_summary()
                self.assertTrue(diagnostics["matrix_proposals_enabled"])
                self.assertTrue(diagnostics["joint_culprits_enabled"])
                self.assertEqual(diagnostics["culprit_posterior"]["version"], "legal-joint-culprits-v1")
                if game.scenario["module"] == "BTX":
                    self.assertEqual(diagnostics["importance"]["proposal_draws"], 192)
                    self.assertEqual(diagnostics["importance"]["proposal_policies"], ["prior"])
                else:
                    self.assertTrue(diagnostics["exact"])
                    self.assertEqual(diagnostics["matrix_proposal_attempts"], 0)
                self.assertEqual(game.protagonist_team_view(), view)

    def test_self_play_default_and_explicit_new_match_are_identical(self):
        matches = [play("official-fs-01-first-script", 0, 2, 4, "fixed",
                        "particle_ensemble", protagonist_nodes=2,
                        protagonist_particles=4, capture_replay=True, **options)
                   for options in ({}, {"matrix_proposals": True, "joint_culprits": True})]
        self.assertEqual(matches[0].decision_digest, matches[1].decision_digest)
        self.assertEqual(matches[0].replay_text, matches[1].replay_text)
        self.assertEqual(matches[0].winner, matches[1].winner)
        for match in matches:
            self.assertTrue(match.matrix_proposals_enabled)
            self.assertTrue(match.joint_culprits_enabled)
            self.assertEqual(match.matrix_variant_policy, "prior")
        legacy = play("official-fs-01-first-script", 0, 2, 4, "fixed",
                      "particle_ensemble", protagonist_nodes=2, protagonist_particles=4,
                      matrix_proposals=False, joint_culprits=False)
        self.assertFalse(legacy.matrix_proposals_enabled)
        self.assertFalse(legacy.joint_culprits_enabled)

    def test_cli_defaults_and_negative_switches_record_resolved_booleans(self):
        cases = (("particle_ensemble", [], True),
                 ("particle_ensemble", ["--no-matrix-proposals", "--no-joint-culprits"], False),
                 ("oracle_script", [], False))
        for module in (ai_self_play, ai_mastermind_matrix):
            for strategy, flags, expected in cases:
                with self.subTest(cli=module.__name__, strategy=strategy, flags=flags):
                    def fake_play(sid, seed, nodes, depth, black, red, **options):
                        self.assertIs(options["matrix_proposals"], expected)
                        self.assertIs(options["joint_culprits"], expected)
                        return MatchResult(sid, "Test", "FS", 2, "standard", black,
                                           red, seed, "mastermind", 1, 1, 0, 0.0,
                                           matrix_proposals_enabled=expected,
                                           joint_culprits_enabled=expected)
                    argv = [module.__name__, "--scenario", "official-fs-01-first-script",
                            "--games", "1", "--protagonists", strategy, *flags]
                    if module is ai_self_play:
                        argv.extend(["--strategy", "fixed"])
                    with (patch("sys.argv", argv), patch.object(module, "play", side_effect=fake_play)
                          as called, redirect_stdout(StringIO())):
                        module.main()
                    self.assertGreater(called.call_count, 0)

    def test_invalid_options_fail_before_starting_a_game(self):
        for option in ("matrix_proposals", "joint_culprits"):
            for value in (0, 1, "false"):
                with self.subTest(option=option, value=value), self.assertRaisesRegex(ValueError, "boolean"):
                    play("official-fs-01-first-script", 0, 1, 1, "fixed", "oracle_script",
                         **{option: value})
