import json
from io import StringIO
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from benchmarks import ai_calibration_matrix as matrix
from tragedy_sim.scenario_library import ScenarioLibrary


class CalibrationMatrixTests(unittest.TestCase):
    def test_discovers_all_recorded_fs_btx_variants(self):
        library = ScenarioLibrary()
        all_ids = matrix.select_scenarios(library, "all", "all")
        standard = matrix.select_scenarios(library, "all", "standard")
        self.assertGreaterEqual(len(standard), 13)
        self.assertGreaterEqual(len(all_ids), 25)
        self.assertTrue(set(standard) <= set(all_ids))
        self.assertTrue(all(library.get(sid)["module"] in {"FS", "BTX"}
                            for sid in all_ids))

    def test_resume_limits_new_jobs_and_never_reruns_completed_matches(self):
        calls = []

        def worker(command, **kwargs):
            self.assertIn("--fixed-work", command)
            sid = command[command.index("--scenario") + 1]
            calls.append(sid)
            return subprocess.CompletedProcess(command, 0, json.dumps({
                "rows": [], "matches": [{"outcome_mode": "survival_win",
                                          "final_correct": 0, "final_total": 0,
                                          "elapsed_seconds": 1}]}), "")

        with TemporaryDirectory() as folder:
            argv = ["matrix", "--output-dir", folder, "--max-jobs", "1"]
            with (patch.object(matrix, "source_digest", return_value="sources"),
                  patch.object(matrix.subprocess, "run", side_effect=worker),
                  patch("builtins.print")):
                with patch("sys.argv", argv):
                    matrix.main()
                with patch("sys.argv", [*argv, "--resume"]):
                    matrix.main()
                self.assertEqual(len(calls), 2)
                self.assertNotEqual(calls[0], calls[1])
                summary = json.loads(next(Path(folder).glob(
                    "run-*/summary.json")).read_text(encoding="utf-8"))
                self.assertEqual(summary["completed"], 2)
                self.assertEqual(summary["planned"], len(matrix.select_scenarios(
                    ScenarioLibrary(), "all", "all")))
                with (patch("sys.argv", argv), patch("sys.stderr", StringIO()),
                      self.assertRaises(SystemExit)):
                    matrix.main()
                checkpoint = next(Path(folder).glob("run-*/official*.json"))
                checkpoint.write_text("{}", encoding="utf-8")
                with (patch("sys.argv", [*argv, "--resume"]),
                      self.assertRaises(ValueError)):
                    matrix.main()
                self.assertEqual(len(calls), 2)

    def test_failed_child_leaves_no_completed_checkpoint(self):
        with TemporaryDirectory() as folder:
            with (patch("sys.argv", ["matrix", "--output-dir", folder,
                                     "--max-jobs", "1"]),
                  patch.object(matrix.subprocess, "run",
                               side_effect=subprocess.CalledProcessError(1, "worker")),
                  patch("builtins.print"),
                  self.assertRaises(subprocess.CalledProcessError)):
                matrix.main()
            self.assertEqual([p.name for p in Path(folder).glob("run-*/*.json")],
                             ["manifest.json"])


if __name__ == "__main__":
    unittest.main()
