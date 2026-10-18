"""Complete public-input pipeline, executable plans and independent work clocks."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from benchmarks import ai_public_day as command
from benchmarks.ai_exact_day import load_root
from tests.test_day_game_posterior import constrained_view
from tragedy_sim.day_game import public_day as module
from tragedy_sim.day_game.public_day import solve_public_day


class PublicDayTests(unittest.TestCase):
    def test_view_only_pipeline_preserves_mass_and_joint_plan_executes_on_real_root(self):
        view = constrained_view(unknown=(), known_culprits=True)
        solved = solve_public_day(view, node_limit=1)
        self.assertEqual(solved.posterior.selected_mass, 1)
        self.assertTrue(solved.model.belief_domain_complete)
        self.assertFalse(solved.result.certified_optimal)
        plan = solved.sample_card_plan(random.Random(1))
        self.assertEqual(len(plan), 3)
        actual = load_root("official-fs-01-first-script")
        for action in plan:
            self.assertIn(action, actual.legal_actions(actual.controller))
            actual.dispatch(**action)
        self.assertEqual(actual.state.phase, "reveal")

    def test_few_worlds_use_original_joint_probabilities_not_empirical_frequencies(self):
        view = load_root("official-fs-01-first-script").protagonist_team_view()
        solved = solve_public_day(view, world_limit=3, node_limit=1)
        self.assertEqual(str(solved.result.covered_mass), "1/2700")
        self.assertEqual(str(solved.result.missing_mass), "2699/2700")
        self.assertFalse(solved.result.belief_domain_complete)

    def test_public_scenario_id_cannot_be_used_to_look_up_secret_script(self):
        view = constrained_view(unknown=(), known_culprits=True)
        with patch("tragedy_sim.scenario_library.ScenarioLibrary.get", side_effect=AssertionError("secret lookup")):
            solved = solve_public_day(view, node_limit=1)
        self.assertIsNotNone(solved.result)

    def test_generic_skip_ablation_keeps_policy_and_uses_conservative_context(self):
        from benchmarks.ai_bayesian_day import GenericSkipPolicy
        view = constrained_view(unknown=(), known_culprits=True)
        specialized = solve_public_day(view, node_limit=1)
        generic = solve_public_day(view, node_limit=1, policy=GenericSkipPolicy())
        self.assertEqual(specialized.result.red, generic.result.red)
        self.assertEqual(specialized.result.lower_bound, generic.result.lower_bound)
        self.assertEqual(specialized.result.upper_bound, generic.result.upper_bound)
        self.assertEqual(generic.model.blocks[0].game.continuation.context_mode, "authorized-history-v1")
        self.assertEqual(specialized.model.blocks[0].game.continuation.context_mode, "audited-menu-only-v1")

    def test_native_history_bridge_reaches_action_search_with_a_separate_evidence_cap(self):
        from tests.test_day_game_history import inputs, second_day_root, singleton_selection
        actual = second_day_root(rumor=True)
        _, _, view, own = inputs(actual)
        selection = singleton_selection(actual, view)
        with patch.object(module.PublicWorldPosterior, "select", return_value=selection):
            solved = solve_public_day(view, own_commands=own, history_node_limit=10000, node_limit=1)
        self.assertEqual(solved.reconstruction.approximated_state_mass, 0)
        self.assertTrue(solved.result.belief_domain_complete)
        self.assertIn("adversarial-compatible-history-support", solved.result.model_scope)
        payload = command.report_payload(solved)
        self.assertTrue(payload["reconstruction"]["history_audits"])
        self.assertEqual(payload["work"][0]["compatible_histories"], 2)
        self.assertEqual(solved.sample_card_plan(random.Random(2))[0]["actor"], actual.controller)

    def test_action_clock_starts_after_posterior_and_reconstruction(self):
        events = []
        original_source, original_roots, original_work = module.PublicWorldPosterior, module.reconstruct_public_roots, module.WorkLimit

        def source(*a, **kw):
            events.append("evidence")
            return original_source(*a, **kw)

        def roots(*a, **kw):
            result = original_roots(*a, **kw)
            events.append("reconstructed")
            return result

        def work(*a, **kw):
            events.append("work")
            return original_work(*a, **kw)

        with (patch.object(module, "PublicWorldPosterior", side_effect=source),
              patch.object(module, "reconstruct_public_roots", side_effect=roots),
              patch.object(module, "WorkLimit", side_effect=work)):
            solved = solve_public_day(constrained_view(unknown=(), known_culprits=True), node_limit=1)
        self.assertEqual(events, ["evidence", "reconstructed", "work"])
        self.assertGreaterEqual(solved.evidence_elapsed_seconds, 0)
        self.assertGreaterEqual(solved.action_elapsed_seconds, 0)

    def test_unavailable_partition_and_midgame_state_never_yield_a_fake_certificate(self):
        view = load_root("official-fs-01-first-script").protagonist_team_view()
        failed = solve_public_day(view, posterior_node_limit=1)
        self.assertIsNone(failed.result)
        self.assertEqual(failed.sample_card_plan(random.Random(0)), ())
        self.assertEqual(failed.action_elapsed_seconds, 0)
        self.assertIn("role_partition", failed.stop_reason)
        view = constrained_view(unknown=(), known_culprits=True, midgame=True)
        strict = solve_public_day(view, node_limit=1)
        self.assertEqual(strict.stop_reason, "no_reconstructible_worlds")
        prior = solve_public_day(view, allow_state_prior=True, node_limit=1)
        self.assertIsNotNone(prior.result)
        self.assertFalse(prior.result.belief_domain_complete)
        for options in (dict(node_limit=0), dict(epsilon=-1), dict(allow_state_prior="yes")):
            with self.assertRaises(ValueError):
                solve_public_day(view, **options)


class PublicDayCommandTests(unittest.TestCase):
    def test_public_view_json_roundtrip_reports_models_and_rational_mass(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"view.json"
            path.write_text(json.dumps(constrained_view(unknown=(), known_culprits=True), ensure_ascii=False), encoding="utf-8")
            with (patch("sys.argv", ["public-day", "--view", str(path), "--nodes", "1"]),
                  redirect_stdout(StringIO()) as output):
                command.main()
            report = json.loads(output.getvalue())
            self.assertIn("authorized-team-view", report["input_source"])
            self.assertFalse(report["room_strategy"])
            self.assertEqual(report["posterior"]["selected_mass"]["fraction"], "1")
            self.assertEqual(report["posterior"]["joint_support"], 1)
            self.assertEqual(report["reconstruction"]["failed_mass"]["fraction"], "0")
            self.assertFalse(report["result"]["certified_optimal"])
            self.assertNotIn("snapshot_key", report["posterior"])

    def test_cli_invalid_or_secret_inputs_fail_cleanly(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"view.json"
            for view in ([], {}, {"viewer": "m", "secret": {}}, {"viewer": "team", "team_hands": None}):
                path.write_text(json.dumps(view), encoding="utf-8")
                with (patch("sys.argv", ["public-day", "--view", str(path)]),
                      redirect_stdout(StringIO()), redirect_stderr(StringIO())):
                    with self.assertRaises(SystemExit):
                        command.main()


if __name__ == "__main__":
    unittest.main()
