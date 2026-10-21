"""Private information-set diagnostic: real JSON input and conservative limits."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmarks import ai_information_day as command
from benchmarks.ai_exact_day import load_root
from tests.test_day_game_posterior import constrained_view


class InformationCommandTests(unittest.TestCase):
    def invoke(self, argv):
        with patch("sys.argv", ["information-day", *argv]), redirect_stdout(StringIO()) as output:
            command.main()
        return json.loads(output.getvalue())

    def test_public_posterior_bridge_and_exact_fractional_interval_json(self):
        with tempfile.TemporaryDirectory() as folder:
            view_path, plan_path = Path(folder)/"view.json", Path(folder)/"plans.json"
            view_path.write_text(json.dumps(constrained_view(unknown=(), known_culprits=True)), encoding="utf-8")
            plans = [[dict(actor=actor, action="play", card="g1", target=target)
                      for actor, target in zip(("a", "b", "c"), ("girl", "doctor", "maiden"))]]
            plan_path.write_text(json.dumps(plans), encoding="utf-8")
            result = self.invoke(["--view", str(view_path), "--warmstart", str(plan_path), "--nodes", "1"])
            self.assertTrue(result["private_diagnostic"])
            self.assertFalse(result["room_strategy"])
            self.assertEqual(result["evidence"]["selected_mass"]["fraction"], "1")
            self.assertFalse(result["tree"]["root_domain_complete"])
            self.assertFalse(result["result"]["certified_optimal"])
            self.assertEqual(result["result"]["bounds"]["lower"]["fraction"], "0")
            self.assertEqual(result["result"]["bounds"]["upper"]["fraction"], "1")
            raw = self.invoke(["--view", str(view_path), "--warmstart", str(plan_path), "--nodes", "1",
                               "--no-constant-compression"])
            self.assertEqual(raw["tree"]["compression"], "none")
            self.assertEqual(raw["tree"]["range_stats"]["folded_subtrees"], 0)
            t0 = self.invoke(["--view", str(view_path), "--warmstart", str(plan_path), "--nodes", "1",
                              "--boundary-evaluator", "day-survival"])
            self.assertEqual(t0["utility"], "day-survival-v1")
            self.assertEqual(t0["tree"]["compression"], "fs-all-native-actions/day-survival-v1")
            unknown = self.invoke(["--view", str(view_path), "--warmstart", str(plan_path), "--nodes", "1",
                                   "--boundary-evaluator", "unknown", "--no-constant-compression"])
            self.assertEqual(unknown["utility"], "unknown-v1")
            self.assertEqual(unknown["tree"]["compression"], "none")
            self.assertFalse(unknown["tree"]["continuation_complete"])
            self.assertEqual(unknown["result"]["bounds"]["lower"]["fraction"], "0")
            self.assertEqual(unknown["result"]["bounds"]["upper"]["fraction"], "1")
            with patch("sys.argv", ["information-day", "--view", str(view_path), "--warmstart", str(plan_path),
                                    "--boundary-evaluator", "unknown"]), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit):
                    command.main()
            full = self.invoke(["--view", str(view_path), "--warmstart", str(plan_path), "--nodes", "1",
                                "--mode", "full-responses"])
            self.assertIn("full-root-information-responses", full["result"]["scope"])
            self.assertFalse(full["result"]["certified_optimal"])
            self.assertFalse(full["result"]["best_response_complete"])
            self.assertEqual(full["result"]["bounds"]["lower"]["fraction"], "0")
            self.assertTrue(full["result"]["lower_strategy"]["red_cards"])

    def test_worlds_input_and_lp_limit_return_no_unverified_strategy(self):
        root = load_root("official-fs-01-first-script")
        with tempfile.TemporaryDirectory() as folder:
            worlds_path, plan_path = Path(folder)/"worlds.json", Path(folder)/"plans.json"
            worlds_path.write_text(json.dumps([dict(label="h0", mass="1", scenario=root.scenario, commands=root.history)]), encoding="utf-8")
            plans = [[dict(actor=actor, action="play", card="g1", target=target)
                      for actor, target in zip(("a", "b", "c"), ("girl", "doctor", "maiden"))]]
            plan_path.write_text(json.dumps(plans), encoding="utf-8")
            result = self.invoke(["--worlds", str(worlds_path), "--warmstart", str(plan_path), "--nodes", "1", "--lp-cells", "1"])
            self.assertEqual(result["stop_reason"], "sequence_lp_cell_limit")
            self.assertIsNone(result["result"])
            self.assertEqual(result["fallback_bounds"], dict(lower=0, upper=1))

    def test_invalid_budget_or_private_view_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"input.json"
            path.write_text(json.dumps({"viewer": "m", "secret": {}}), encoding="utf-8")
            for extra in ([], ["--history-nodes", "0"], ["--black-limit", "0"], ["--complete-posterior"]):
                with patch("sys.argv", ["information-day", "--view", str(path), "--warmstart", str(path), *extra]), redirect_stderr(StringIO()):
                    with self.assertRaises(SystemExit):
                        command.main()


if __name__ == "__main__":
    unittest.main()
