"""Finite-world command input, exact fractions, and explicit coverage scope."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmarks import ai_bayesian_day as evaluation
from benchmarks.ai_exact_day import load_root


def world_records():
    first = load_root("official-fs-01-first-script")
    scenario = deepcopy(first.scenario)
    scenario["cast"]["girl"], scenario["cast"]["maiden"] = scenario["cast"]["maiden"], scenario["cast"]["girl"]
    return [dict(label="h0", mass="2/5", scenario=first.scenario, commands=first.history),
            dict(label="h1", mass="1/2", scenario=scenario, commands=first.history)]


class BayesianDayCommandTests(unittest.TestCase):
    def test_real_world_input_preserves_masses_and_reports_incomplete_unknown_model(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"worlds.json"
            path.write_text(json.dumps(world_records(), ensure_ascii=False), encoding="utf-8")
            loaded = evaluation.load_worlds(path)
            self.assertEqual(tuple(str(mass) for _, mass, _ in loaded), ("2/5", "1/2"))
            self.assertTrue(all(world.state.phase == "protagonists" for _, _, world in loaded))
            with (patch("sys.argv", ["bayesian-day", "--worlds", str(path), "--nodes", "1"]),
                  redirect_stdout(StringIO()) as output):
                evaluation.main()
            report = json.loads(output.getvalue())
            self.assertTrue(report["private_diagnostic"])
            self.assertFalse(report["room_strategy"])
            self.assertFalse(report["asserted_complete_posterior"])
            self.assertEqual(report["result"]["covered_mass"]["fraction"], "9/10")
            self.assertEqual(report["result"]["missing_mass"]["fraction"], "1/10")
            self.assertFalse(report["result"]["certified_optimal"])
            self.assertTrue(all(len(row["plan"]) == 3 for row in report["result"]["red"]))
            self.assertEqual(len(report["result"]["black"]), 2)
            self.assertEqual(report["horizon"], "day")
            self.assertIn("fixed-observable", report["result"]["model_scope"])

    def test_bad_input_and_false_completeness_assertion_fail_cleanly(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"worlds.json"
            for records in ({}, [], [{"label": "bad"}], [dict(label="bad", mass=True, scenario={}, commands=[])]):
                path.write_text(json.dumps(records), encoding="utf-8")
                with self.assertRaises(ValueError):
                    evaluation.load_worlds(path)
            path.write_text(json.dumps(world_records(), ensure_ascii=False), encoding="utf-8")
            for options in (("--complete-posterior",), ("--epsilon", "-1"), ("--nodes", "0")):
                with (patch("sys.argv", ["bayesian-day", "--worlds", str(path), *options]),
                      redirect_stdout(StringIO()), redirect_stderr(StringIO())):
                    with self.assertRaises(SystemExit):
                        evaluation.main()


if __name__ == "__main__":
    unittest.main()
