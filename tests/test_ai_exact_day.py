"""Diagnostic roots and machine-readable bounded certificates."""

from contextlib import redirect_stdout
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


if __name__ == "__main__":
    unittest.main()
