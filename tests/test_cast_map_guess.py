"""Opt-in cast marginal guessing is fair, bounded and action-independent."""

from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from benchmarks.ai_final_guess_comparison import compare_final_root
from benchmarks import ai_final_guess_comparison
from benchmarks.ai_self_play import _final_inference_diagnostics, _policy_offer, play
from benchmarks import ai_self_play, ai_mastermind_matrix
from tragedy_sim import Game
from tragedy_sim.belief import PublicEvidence
from tragedy_sim.final_guess_probability import JointGuessProbabilitySolver
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.search import SearchBudget
from tragedy_sim.witness import FsbtxWitnessCompiler
from tests.test_particle_ensemble import protagonist_position


def final_game():
    game = Game({"id": "cast-map-counterexample", "title": "cast marginal test", "module": "BTX",
                 "days": 1, "loops": 1, "main_plot": "sign", "subplots": ["rumor", "threads"],
                 "cast": {"doctor": "ordinary", "girl": "ordinary", "maiden": "key", "student": "conspiracy"},
                 "incidents": [], "table_talk": True})
    game._start_final_guess()
    return game


class CastMapGuessTests(unittest.TestCase):
    def choose(self, game, mode, **options):
        policy = ParticleEnsembleProtagonistAgent(
            SearchBudget(node_limit=1, seed=4), particle_count=1,
            final_guess_policy=mode, **options)
        offers = [_policy_offer(game, action) for action in game.action_offers(game.controller)]
        return policy, policy.choose_action(participant="team", view=game.protagonist_team_view(), offers=offers)

    def test_marginal_map_aggregates_plots_and_improves_joint_probability(self):
        game = final_game()
        old, old_action = self.choose(game, "latent_map")
        new, new_action = self.choose(game, "cast_map")
        view = game.protagonist_team_view()
        result = JointGuessProbabilitySolver().solve(PublicEvidence.from_view(view), FsbtxWitnessCompiler().compile(view))
        a, b = (action["arguments"]["guesses"] for action in (old_action, new_action))
        self.assertAlmostEqual(result.probability_for(b), 3 * result.probability_for(a))
        self.assertEqual(b, dict(result.best_guess))
        self.assertEqual(new.last_trace.belief_source, "exact_cast_marginal_map")
        self.assertEqual(new.last_trace.belief_roles, ())  # No invented marginals from a MAP representative.
        self.assertEqual(new.last_trace.final_guess_probability["best_guess_probability"], result.best_guess_probability)
        self.assertEqual(old.last_trace.belief_source, "exact_joint_map")
        self.assertEqual(game.state.phase, "final_guess")

    def test_work_limit_preserves_legacy_choice_and_marks_probability_unavailable(self):
        game = final_game()
        _, baseline = self.choose(game, "latent_map")
        policy, chosen = self.choose(game, "cast_map", final_guess_node_limit=1)
        self.assertEqual(chosen, baseline)
        self.assertEqual(policy.last_trace.belief_failure, "cast_map_work_limit")
        self.assertFalse(policy.last_trace.final_guess_probability["exact"])
        self.assertIsNone(policy.last_trace.final_guess_probability["best_guess_probability"])

    def test_policy_does_not_change_day_plan_or_sampling_rng(self):
        game = protagonist_position()
        offers = [_policy_offer(game, action) for action in game.action_offers(game.controller)]
        decisions, states = [], []
        for mode in ("latent_map", "cast_map"):
            policy = ParticleEnsembleProtagonistAgent(SearchBudget(node_limit=2, seed=4),
                                                       particle_count=2, rng_seed=4, final_guess_policy=mode)
            chosen = policy.choose_action(participant="team", view=deepcopy(game.protagonist_team_view()), offers=offers)
            decisions.append(policy.decision_for_action(chosen))
            states.append((policy.factorized_belief.rng.getstate(), policy.factorized_belief.matrix_rng.getstate()))
        self.assertEqual(decisions[0], decisions[1])
        self.assertEqual(states[0], states[1])
        self.assertEqual(ParticleEnsembleProtagonistAgent().final_guess_policy, "latent_map")

    def test_final_inference_audit_requires_pre_submission_and_private_knowledge(self):
        game = final_game()
        game.protagonist_knowledge = {"initial_roles": {"maiden": "brain"}}
        policy, chosen = self.choose(game, "latent_map")
        result = _final_inference_diagnostics(game, policy, game.scenario)
        self.assertFalse(result["hard_compatible"])
        self.assertFalse(result["in_space"])
        game.dispatch(game.controller, "guess_all", **chosen["arguments"])
        with self.assertRaisesRegex(ValueError, "before"):
            _final_inference_diagnostics(game, policy, game.scenario)

    def test_comparison_inputs_are_authorized_and_game_is_unchanged(self):
        game = final_game()
        before = deepcopy(game.view("m"))
        inputs = []
        original = ParticleEnsembleProtagonistAgent.choose_action
        def spy(policy, *, participant, view, offers):
            inputs.append(deepcopy(view))
            return original(policy, participant=participant, view=view, offers=offers)
        with patch.object(ParticleEnsembleProtagonistAgent, "choose_action", spy):
            result = compare_final_root(game)
        self.assertTrue(result["cast_map_maximizes_probability"])
        self.assertTrue(all("secret" not in view for view in inputs))
        self.assertEqual(len(inputs), 2)
        self.assertEqual(game.view("m"), before)
        self.assertEqual(result["decisions"][1]["offline_outcome"]["winner"], "protagonists")

    def test_invalid_configuration_fails_before_starting(self):
        for options in ({"final_guess_policy": "unknown"}, {"final_guess_node_limit": True},
                        {"final_guess_node_limit": 0}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                ParticleEnsembleProtagonistAgent(**options)
        with self.assertRaisesRegex(ValueError, "particle_ensemble"):
            play("unused", 0, 1, 1, "fixed", "oracle_script", final_guess_policy="cast_map")

    def test_comparison_partial_reports_resume_and_reject_changed_inputs(self):
        with TemporaryDirectory() as directory:
            source, output = (Path(directory) / name for name in ("source.json", "comparison.json"))
            source.write_text(json.dumps({"progress": {"complete": True}, "results": [
                {"scenario": "a"}, {"scenario": "b"}]}), encoding="utf-8")
            args = ["compare", str(source), "--output", str(output), "--max-jobs", "1"]
            with (patch("sys.argv", args), redirect_stdout(StringIO()),
                  patch.object(ai_final_guess_comparison, "compare_row",
                               side_effect=lambda row, **_: {"scenario": row["scenario"], "finals": []})):
                ai_final_guess_comparison.main()
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved["progress"], {"completed": 1, "planned": 2, "complete": False})
            with (patch("sys.argv", args + ["--resume"]), redirect_stdout(StringIO()),
                  patch.object(ai_final_guess_comparison, "compare_row",
                               side_effect=lambda row, **_: {"scenario": row["scenario"], "finals": []}) as called):
                ai_final_guess_comparison.main()
            self.assertEqual(called.call_args.args[0]["scenario"], "b")
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved["progress"], {"completed": 2, "planned": 2, "complete": True})
            source.write_text(json.dumps({"sources": "changed", "progress": {"complete": True},
                                          "results": [{"scenario": "a"}, {"scenario": "b"}]}), encoding="utf-8")
            with (patch("sys.argv", args + ["--resume"]), patch("sys.stderr", StringIO()),
                  self.assertRaises(SystemExit)):
                ai_final_guess_comparison.main()

    def test_cli_forwards_explicit_terminal_mode_without_changing_defaults(self):
        from benchmarks.ai_self_play import MatchResult
        for module in (ai_self_play, ai_mastermind_matrix):
            argv = [module.__name__, "--scenario", "unused", "--games", "1",
                    "--protagonists", "particle_ensemble", "--final-guess-policy", "cast_map",
                    "--final-guess-node-limit", "20"]
            if module is ai_self_play:
                argv.extend(["--strategy", "fixed"])
            def fake_play(*args, **kwargs):
                self.assertEqual(kwargs["final_guess_policy"], "cast_map")
                self.assertEqual(kwargs["final_guess_node_limit"], 20)
                return MatchResult("unused", "test", "BTX", 1, "standard", "fixed",
                                   "particle_ensemble", 0, "mastermind", 1, 1, 0, 0.0)
            with (patch("sys.argv", argv), patch.object(module, "play", side_effect=fake_play),
                  redirect_stdout(StringIO())):
                module.main()


if __name__ == "__main__":
    unittest.main()
