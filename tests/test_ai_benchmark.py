"""Developer benchmark telemetry regressions."""

import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from benchmarks import ai_cutoff_calibration, ai_mastermind_matrix
from benchmarks.ai_cutoff_calibration import summarize as summarize_cutoffs, weighted_auc
from benchmarks.ai_path_calibration import cross_validated_paths
from benchmarks.ai_difficulty_matrix import (difficulty_groups, paired_outcomes,
                                             summarize, wilson_interval)
from benchmarks.ai_self_play import (MatchResult, ProtagonistPlayRecord,
                                    ProtagonistSearchRecord, _ability_usage, play)
from tragedy_sim.scenario_library import ScenarioLibrary


class AbilityUsageTests(unittest.TestCase):
    def test_calibration_records_actual_world_counts_and_placement_work(self):
        result = MatchResult(
            scenario_id="test", scenario_title="test", module="BTX", loops=3,
            difficulty="standard", mastermind_strategy="fixed",
            protagonist_strategy="particle_ensemble", seed=0, winner="mastermind",
            decisions=1, mastermind_decisions=1, search_nodes=0, elapsed_seconds=1)
        empty = ai_cutoff_calibration.match_telemetry(result)
        self.assertIsNone(empty["sampled_worlds_min"])
        self.assertEqual(empty["policy_rollouts"], 0)
        search = ProtagonistSearchRecord(
            1, 1, 2, (2, 2), "factorized", None, 12, 0, (), (), (),
            evaluated_pairs=24)
        observed = ai_cutoff_calibration.match_telemetry(replace(
            result, protagonist_searches=(search, replace(
                search, particles=32, evaluated_pairs=64)),
            protagonist_evidence_seconds=0.1, protagonist_search_seconds=0.2,
            protagonist_plays=(ProtagonistPlayRecord(1, 1, "a", "fi", "school",
                                                    reason="no_particles"),
                               ProtagonistPlayRecord(1, 1, "b", "fm", "girl",
                                                    reason="joint_plan_followup"))))
        self.assertEqual((observed["sampled_worlds_min"],
                          observed["sampled_worlds_max"]), (12, 32))
        self.assertEqual(observed["policy_rollouts"], 88)
        self.assertEqual(observed["play_fallback_reasons"], {"no_particles": 1})
        self.assertEqual(observed["placement_search_seconds"], 0.2)

    def test_match_digest_covers_repeatable_complete_decisions(self):
        first = play("official-btx-02-traditional-ensemble-murder", 0, 2, 2,
                     "fixed", "baseline")
        second = play("official-btx-02-traditional-ensemble-murder", 0, 2, 2,
                      "fixed", "baseline")
        self.assertEqual(len(first.decision_digest), 64)
        self.assertEqual(first.decision_digest, second.decision_digest)
        self.assertEqual(first.winner, second.winner)

    def test_fixed_work_cli_removes_both_deadlines_and_checks_repeats(self):
        def fake_play(scenario, seed, nodes, depth, strategy, protagonists, **kwargs):
            self.assertIsNone(kwargs["time_limit_ms"])
            self.assertIsNone(kwargs["protagonist_time_limit_ms"])
            return MatchResult(
                scenario_id=scenario, scenario_title="test", module="BTX",
                loops=3, difficulty="standard", mastermind_strategy=strategy,
                protagonist_strategy=protagonists, seed=seed,
                winner="protagonists", decisions=1, mastermind_decisions=1,
                search_nodes=0, elapsed_seconds=1.0, decision_digest="same")

        output = StringIO()
        with (patch("sys.argv", ["ai_cutoff_calibration", "--games", "1",
                                 "--strategy", "fixed", "--fixed-work",
                                 "--repeat-check", "--json"]),
              patch.object(ai_cutoff_calibration, "play", side_effect=fake_play)
              as mocked, redirect_stdout(output)):
            ai_cutoff_calibration.main()
        self.assertEqual(mocked.call_count, 4)  # Two scenarios, each repeated.
        self.assertIn('"unstable": 0', output.getvalue())
        counter = 0

        def changing_play(*args, **kwargs):
            nonlocal counter
            counter += 1
            return replace(fake_play(*args, **kwargs),
                           decision_digest=str(counter))

        with (patch("sys.argv", ["ai_cutoff_calibration", "--games", "1",
                                 "--strategy", "fixed", "--fixed-work",
                                 "--repeat-check", "--json"]),
              patch.object(ai_cutoff_calibration, "play",
                           side_effect=changing_play),
              redirect_stdout(StringIO()), self.assertRaises(SystemExit) as error):
            ai_cutoff_calibration.main()
        self.assertEqual(error.exception.code, 1)

        with TemporaryDirectory() as directory:
            target = Path(directory) / "nested" / "report.json"
            with (patch("sys.argv", ["ai_cutoff_calibration", "--games", "1",
                                     "--strategy", "fixed", "--fixed-work",
                                     "--output", str(target)]),
                  patch.object(ai_cutoff_calibration, "play", side_effect=fake_play),
                  redirect_stdout(StringIO())):
                ai_cutoff_calibration.main()
            saved = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(saved["budget"]["mode"], "fixed_work")
            self.assertEqual(saved["matches"][0]["decision_digest"], "same")
        def particle_play(*args, **kwargs):
            self.assertEqual(kwargs["protagonist_particles"], 12)
            return fake_play(*args, **kwargs)

        with (patch("sys.argv", ["ai_cutoff_calibration", "--games", "1",
                                 "--strategy", "fixed", "--fixed-work",
                                 "--protagonist-particles", "12"]),
              patch.object(ai_cutoff_calibration, "play", side_effect=particle_play),
              redirect_stdout(StringIO())):
            ai_cutoff_calibration.main()

    def test_dual_path_calibration_holds_out_seeds_and_handles_sparse_guesses(self):
        modes = ("survival_win", "final_guess_win", "final_guess_loss",
                 "other_black_win")
        rows = []
        for seed, mode in enumerate(modes):
            for day in (1, 2):
                rows.append({
                    "scenario": "btx", "strategy": "fixed", "seed": seed,
                    "loop": 1, "day_ended": day, "days": 3, "loops": 2,
                    "hero_score": (0.8 if mode == "survival_win" else -0.3),
                    "hard_role_entropy": (0.1 if mode == "final_guess_win"
                                          else 0.8),
                    "outcome_mode": mode,
                    "red_win": mode.endswith("win"), "weight": 0.5,
                })
        report = cross_validated_paths(rows)
        self.assertEqual(report["heldout_seeds"], 4)
        self.assertEqual(report["matches"], 4)
        self.assertEqual(report["conditional_guess_win_matches"], 1)
        self.assertEqual(report["conditional_guess_loss_matches"], 1)
        self.assertGreaterEqual(report["path_brier"], 0)
        self.assertLessEqual(report["path_brier"], 1)
        self.assertGreaterEqual(report["single_brier"], 0)
        self.assertLessEqual(report["single_brier"], 1)
        self.assertEqual(cross_validated_paths(rows[:2])["heldout_seeds"], 1)

    def test_cutoff_auc_ranks_match_outcomes_and_handles_one_class(self):
        rows = [
            {"scenario": "a", "strategy": "fixed", "seed": 0,
             "red_win": True, "direct_red_win": True, "weight": 0.5,
             "hero_score": 0.8, "negative_entropy": -0.3,
             "score_minus_entropy": 0.79},
            {"scenario": "a", "strategy": "fixed", "seed": 1,
             "red_win": False, "direct_red_win": False, "weight": 1.0,
             "hero_score": 0.2, "negative_entropy": -0.7,
             "score_minus_entropy": 0.19},
        ]
        self.assertEqual(weighted_auc(rows, "hero_score"), 1.0)
        self.assertIsNone(weighted_auc(rows[:1], "hero_score"))
        self.assertEqual(summarize_cutoffs(rows)["matches"], 2)

    def test_cutoff_observer_receives_only_stable_nonterminal_days(self):
        observed = []

        def inspect(game, event):
            observed.append((event["kind"], int(event["round"]),
                             game.state.phase, game.winner))

        play("official-btx-02-traditional-ensemble-murder", 0, 2, 2,
             "fixed", "baseline", cutoff_observer=inspect)
        self.assertTrue(observed)
        self.assertTrue(all(kind == "day_ended" and phase == "day_start"
                            and winner is None and day >= 1
                            for kind, day, phase, winner in observed))

    def test_mastermind_matrix_pairs_strategies_under_same_budget(self):
        def fake_play(scenario, seed, nodes, depth, strategy, protagonists, **kwargs):
            self.assertEqual((scenario, seed, nodes, depth, protagonists),
                             ("official-fs-01-first-script", 2, 7, 5,
                              "particle_ensemble"))
            self.assertEqual(kwargs["time_limit_ms"], 900)
            self.assertEqual(kwargs["protagonist_time_limit_ms"], 800)
            self.assertEqual(kwargs["joint_reply_model"], "public")
            self.assertEqual(kwargs['protagonist_particles'], 32)
            return MatchResult(
                scenario_id=scenario, scenario_title="FS01", module="FS",
                loops=3, difficulty="standard", mastermind_strategy=strategy,
                protagonist_strategy=protagonists, seed=seed,
                winner="mastermind", decisions=3, mastermind_decisions=1,
                search_nodes=7, elapsed_seconds=1.0,
                mastermind_search_seconds=0.4)

        output = StringIO()
        with (TemporaryDirectory() as folder,
              patch("sys.argv", ["ai_mastermind_matrix",
                                 "--scenario", "official-fs-01-first-script",
                                 "--games", "1", "--seed", "2",
                                 "--mastermind-ms", "900",
                                 "--mastermind-nodes", "7",
                                 "--protagonist-ms", "800",
                                 "--protagonist-nodes", "4",
                                 "--protagonist-particles", "32",
                                 "--output", str(Path(folder) / 'report.json'),
                                 "--depth", "5"]),
              patch.object(ai_mastermind_matrix, "play", side_effect=fake_play)
              as mocked,
              redirect_stdout(output)):
            ai_mastermind_matrix.main()
            report = json.loads((Path(folder) / 'report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['schema_version'], 2)
            self.assertEqual(report['settings']['protagonist_particles'], 32)
            self.assertEqual(len(report['results']), 2)
            self.assertEqual(report['results'][0]['recorded_placement_searches'], 0)
            self.assertEqual(report['results'][0]['play_fallback_reasons'], {})
        self.assertEqual([call.args[4] for call in mocked.call_args_list],
                         ["strategic", "joint"])
        self.assertIn("joint: black wins 1/1", output.getvalue())

    def test_summarizes_information_ability_lifecycle(self):
        common = {"source": "worker", "ability": "reveal",
                  "ability_kind": "reveal"}
        records = _ability_usage([
            {"kind": "goodwill_requested", **common},
            {"kind": "goodwill_refused", **common},
            {"kind": "ability_no_effect", "reason": "refused", **common},
            {"kind": "goodwill_requested", **common},
            {"kind": "goodwill_accepted", **common},
        ])
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].information)
        self.assertEqual(
            (records[0].requested, records[0].accepted,
             records[0].refused, records[0].no_effect),
            (2, 1, 1, 1))

    def test_discovers_concrete_loop_difficulty_groups(self):
        groups = difficulty_groups(ScenarioLibrary(), "BTX")
        mirror = next(item for item in groups
                      if item.base_id == "official-btx-08-mirror-passcode")
        ensemble = next(item for item in groups
                        if item.base_id ==
                        "official-btx-02-traditional-ensemble-murder")
        self.assertEqual(mirror.variants, (
            mirror.base_id, mirror.base_id + "-easy"))
        self.assertEqual(ensemble.variants, (
            ensemble.base_id, ensemble.base_id + "-easy",
            ensemble.base_id + "-very-easy"))

    def test_difficulty_summary_keeps_guess_and_loop_metrics_separate(self):
        common = dict(
            scenario_title="Test", module="BTX", loops=3,
            difficulty="standard", mastermind_strategy="fixed",
            protagonist_strategy="particle_ensemble", seed=0,
            mastermind_decisions=1, search_nodes=0,
            protagonist_horizon="day")
        results = [
            MatchResult(scenario_id="one", winner="protagonists", decisions=3,
                        elapsed_seconds=1.0, **common),
            MatchResult(scenario_id="two", winner="mastermind", decisions=4,
                        elapsed_seconds=3.0,
                        loop_losses=(), **common),
        ]
        report = summarize(results)
        self.assertEqual(report["protagonist_win_rate"], 0.5)
        self.assertEqual(report["mean_elapsed_seconds"], 2.0)
        self.assertEqual(report["lost_loop_fraction"], 0.0)
        self.assertIsNone(report["final_guess_accuracy"])
        self.assertEqual(report["true_setup_in_exact_space"], 0)

    def test_win_interval_and_paired_outcomes(self):
        low, high = wilson_interval(3, 9)
        self.assertAlmostEqual(low, 0.1206, places=3)
        self.assertAlmostEqual(high, 0.6458, places=3)

        common = dict(
            scenario_title="Test", module="BTX",
            mastermind_strategy="fixed",
            protagonist_strategy="particle_ensemble", seed=0,
            decisions=3, mastermind_decisions=1, search_nodes=0,
            elapsed_seconds=1.0, protagonist_horizon="day")
        results = [
            MatchResult(scenario_id="one", loops=3, difficulty="standard",
                        winner="mastermind", **common),
            MatchResult(scenario_id="one-easy", loops=4, difficulty="easy",
                        winner="protagonists", **common),
        ]
        self.assertEqual(paired_outcomes(results), {
            "both_win": 0, "easy_only_win": 1,
            "standard_only_win": 0, "both_lose": 0, "pairs": 1})


if __name__ == "__main__":
    unittest.main()
