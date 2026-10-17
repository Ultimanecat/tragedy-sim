"""Diagnostic roots and machine-readable bounded certificates."""

from contextlib import redirect_stdout, redirect_stderr
from dataclasses import asdict
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from benchmarks import ai_exact_day as evaluation
from tragedy_sim.day_game import PureDaySolver, WorkLimit


SCENARIO = "official-fs-01-first-script"


class ExactDayCommandTests(unittest.TestCase):
    def test_fresh_root_uses_legal_engine_commands_and_has_no_red_commitment(self):
        world = evaluation.load_root(SCENARIO)
        self.assertEqual(world.state.phase, "protagonists")
        self.assertEqual([p.actor for p in world.state.pending], ["m"] * 3)
        self.assertEqual([p.target for p in world.state.pending], ["girl", "worker", "doctor"])
        self.assertFalse(world.state.face_up)
        with self.assertRaises(ValueError):
            evaluation.load_root(SCENARIO, targets=("girl", "girl", "doctor"))
        with self.assertRaises(ValueError):
            evaluation.load_root(SCENARIO, day=2)

    def test_report_selection_and_requested_root_are_validated(self):
        from tests.test_ai_proposal_regression_audit import completed_row

        row = completed_row()
        # Fixture's original scenario id is used to avoid rewriting its replay.
        from tragedy_sim.replay import ReplayArchive
        archive = ReplayArchive.parse(row["replay_text"])
        scenario = archive.scenario["id"]
        row.update(scenario=scenario, seed=0, variant="fixture")
        with TemporaryDirectory() as folder:
            path = Path(folder) / "report.json"
            evaluation.write_report(path, {"results": [row]})
            world = evaluation.load_root(scenario, report=path, seed=0, variant="fixture")
            self.assertEqual(world.state.phase, "protagonists")
            self.assertFalse(any(p.actor != "m" for p in world.state.pending))
            for selectors in ({"seed": 1}, {"variant": "missing"}, {"day": 999}):
                with self.assertRaises(ValueError):
                    evaluation.load_root(scenario, report=path, **selectors)
            evaluation.write_report(path, {"results": [row, row]})
            with self.assertRaises(ValueError):
                evaluation.load_root(scenario, report=path)

    def test_json_reports_unknown_value_scope_and_frozen_sources(self):
        world = evaluation.load_root(SCENARIO)
        result = PureDaySolver().solve(world, work=WorkLimit(node_limit=1))
        with (patch("sys.argv", ["exact-day", "--nodes", "1"]),
              patch.object(evaluation, "load_root", return_value=world),
              patch.object(evaluation, "source_digest", return_value="frozen"),
              patch.object(evaluation.PureDaySolver, "solve", return_value=result),
              redirect_stdout(StringIO()) as output):
            evaluation.main()
        report = json.loads(output.getvalue())
        self.assertEqual(report["sources"], "frozen")
        self.assertFalse(report["certified_pure_value"])
        self.assertTrue(report["known_script"])
        self.assertFalse(report["fair_policy"])
        self.assertEqual(report["result"]["bounds"], asdict(result.bounds))
        self.assertEqual(report["result"]["strategy_class"], "pure")
        with (patch("sys.argv", ["exact-day", "--nodes", "1"]),
              patch.object(evaluation, "load_root", return_value=world),
              patch.object(evaluation, "source_digest", side_effect=["before", "after"]),
              patch.object(evaluation.PureDaySolver, "solve", return_value=result)):
            with self.assertRaisesRegex(RuntimeError, "sources changed"):
                evaluation.main()

    def test_cached_backend_is_optional_and_reports_its_work(self):
        with (patch("sys.argv", ["exact-day", "--backend", "cached", "--nodes", "1"]),
              patch.object(evaluation, "source_digest", return_value="frozen"),
              redirect_stdout(StringIO()) as output):
            evaluation.main()
        report = json.loads(output.getvalue())
        self.assertEqual(report["settings"]["backend"], "cached")
        self.assertFalse(report["certified_pure_value"])
        self.assertGreater(report["cache"]["compact_clones"], 0)
        self.assertEqual(report["cache"]["fallback_clones"], 0)
        self.assertEqual(report["cache"]["version"], "fs-detached-v1")

    def test_compiled_backend_records_program_and_rule_key_versions(self):
        with (patch("sys.argv", ["exact-day", "--backend", "compiled", "--nodes", "1"]),
              patch.object(evaluation, "source_digest", return_value="frozen"),
              redirect_stdout(StringIO()) as output):
            evaluation.main()
        report = json.loads(output.getvalue())
        self.assertEqual(report["settings"]["backend"], "compiled")
        self.assertFalse(report["certified_pure_value"])
        self.assertEqual(report["cache"]["rule_key_version"], "fs-rule-v2-hand-multisets")
        self.assertEqual(report["cache"]["local_program_version"], "fs-local-card-program-v1")
        self.assertEqual(report["cache"]["programs"]["movements"], 1)
        self.assertEqual(report["cache"]["programs"]["fallbacks"], 0)

    def test_optional_observation_edge_cache_reports_capacity_and_work(self):
        with (patch("sys.argv", ["exact-day", "--backend", "compiled", "--nodes", "1", "--edge-cache-capacity", "8"]),
              patch.object(evaluation, "source_digest", return_value="frozen"),
              redirect_stdout(StringIO()) as output):
            evaluation.main()
        report = json.loads(output.getvalue())
        self.assertEqual(report["settings"]["edge_cache_capacity"], 8)
        self.assertEqual(report["cache"]["edges"]["version"], "fs-transition-observation-edge-v1")
        self.assertGreater(report["cache"]["edges"]["stores"], 0)
        self.assertLessEqual(report["cache"]["edges"]["entries"], 8)

    def test_mixed_mode_reports_exact_rational_certificate_and_executable_joint_plans(self):
        from tests.test_day_game_mixed_engine import matching_root
        with (patch("sys.argv", ["exact-day", "--mode", "mixed", "--backend", "cached", "--epsilon", "0",
                                  "--nodes", "100000", "--time-ms", "30000"]),
              patch.object(evaluation, "load_root", return_value=matching_root()),
              patch.object(evaluation, "source_digest", return_value="frozen"),
              redirect_stdout(StringIO()) as output):
            evaluation.main()
        report = json.loads(output.getvalue())
        self.assertTrue(report["certified_mixed_value"])
        self.assertFalse(report["fair_policy"])
        self.assertEqual(report["result"]["lower_bound"]["fraction"], "2/3")
        self.assertEqual(report["result"]["gap"]["fraction"], "0")
        self.assertEqual(report["result"]["numeric_error_bound"]["fraction"], "0")
        self.assertEqual(report["mixed_work"]["row_domain"], 240)
        self.assertTrue(all(len(row["plan"]) == 3 for row in report["result"]["red"]))
        self.assertTrue(all(c["action"] == "play" for row in report["result"]["red"] for c in row["plan"]))

    def test_mixed_budget_and_bad_epsilon_do_not_print_false_optimality(self):
        with (patch("sys.argv", ["exact-day", "--mode", "mixed", "--backend", "cached", "--nodes", "1"]),
              patch.object(evaluation, "source_digest", return_value="frozen"),
              redirect_stdout(StringIO()) as output):
            evaluation.main()
        report = json.loads(output.getvalue())
        self.assertFalse(report["certified_mixed_value"])
        self.assertEqual(report["result"]["lower_bound"]["fraction"], "0")
        self.assertEqual(report["result"]["upper_bound"]["fraction"], "1")
        with (patch("sys.argv", ["exact-day", "--mode", "mixed", "--epsilon", "-1"]),
              redirect_stdout(StringIO()), redirect_stderr(StringIO())):
            with self.assertRaises(SystemExit):
                evaluation.main()


if __name__ == "__main__":
    unittest.main()
