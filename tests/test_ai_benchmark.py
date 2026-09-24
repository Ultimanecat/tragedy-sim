"""Developer benchmark telemetry regressions."""

import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from benchmarks import ai_mastermind_matrix
from benchmarks.ai_difficulty_matrix import (difficulty_groups, paired_outcomes,
                                             summarize, wilson_interval)
from benchmarks.ai_self_play import MatchResult, _ability_usage
from tragedy_sim.scenario_library import ScenarioLibrary


class AbilityUsageTests(unittest.TestCase):
    def test_mastermind_matrix_pairs_strategies_under_same_budget(self):
        def fake_play(scenario, seed, nodes, depth, strategy, protagonists, **kwargs):
            self.assertEqual((scenario, seed, nodes, depth, protagonists),
                             ("official-fs-01-first-script", 2, 7, 5,
                              "particle_ensemble"))
            self.assertEqual(kwargs["time_limit_ms"], 900)
            self.assertEqual(kwargs["protagonist_time_limit_ms"], 800)
            return MatchResult(
                scenario_id=scenario, scenario_title="FS01", module="FS",
                loops=3, difficulty="standard", mastermind_strategy=strategy,
                protagonist_strategy=protagonists, seed=seed,
                winner="mastermind", decisions=3, mastermind_decisions=1,
                search_nodes=7, elapsed_seconds=1.0,
                mastermind_search_seconds=0.4)

        output = StringIO()
        with (patch("sys.argv", ["ai_mastermind_matrix",
                                 "--scenario", "official-fs-01-first-script",
                                 "--games", "1", "--seed", "2",
                                 "--mastermind-ms", "900",
                                 "--mastermind-nodes", "7",
                                 "--protagonist-ms", "800",
                                 "--protagonist-nodes", "4",
                                 "--depth", "5"]),
              patch.object(ai_mastermind_matrix, "play", side_effect=fake_play)
              as mocked,
              redirect_stdout(output)):
            ai_mastermind_matrix.main()
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
