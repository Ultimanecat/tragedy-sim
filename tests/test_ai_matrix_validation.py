from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from benchmarks import ai_matrix_validation as evaluation
from benchmarks.ai_self_play import MatchResult
from tests.test_ai_proposal_regression_audit import completed_row
from tragedy_sim.replay import ReplayArchive, dumps


class MatrixEvaluationTests(unittest.TestCase):
    def completed(self):
        row = completed_row()
        archive = ReplayArchive.parse(row["replay_text"])
        archive.scenario["id"] = "official-fs-01-first-script"
        return MatchResult("official-fs-01-first-script", "FS", "FS", 1, "standard",
                           "joint", "particle_ensemble", 0, "mastermind", 1, 1, 1, 0.1,
                           replay_text=dumps(archive.verify()), matrix_variant_policy="uniform")

    def fake_play(self, *args, **kwargs):
        return replace(self.completed(), scenario_id=args[0], seed=args[1],
                       matrix_proposals_enabled=kwargs["matrix_proposals"],
                       joint_culprits_enabled=kwargs["joint_culprits"],
                       matrix_variant_policy=kwargs["matrix_variant_policy"],
                       role_sampling_policy=kwargs["role_sampling_policy"], dark_card_policy=kwargs["dark_card_policy"],
                       dark_guard_proposals=kwargs["dark_guard_proposals"],
                       protagonist_candidate_policy=kwargs.get("protagonist_candidate_policy", "legacy"))

    def test_marginal_comparison_routes_same_joint_candidates_and_distinct_attack_policies(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "evaluation.json"
            with (patch("sys.argv", ["evaluate", "--scenario", "official-fs-01-first-script", "--seed", "0",
                                    "--comparison", "joint_marginal_guard", "--workers", "1", "--output", str(path)]),
                  patch.object(evaluation, "play", side_effect=self.fake_play) as play_mock,
                  patch.object(evaluation, "source_digest", return_value="frozen"), redirect_stdout(StringIO())):
                evaluation.main()
            report = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(report["progress"]["complete"])
            self.assertEqual([call.kwargs["protagonist_candidate_policy"] for call in play_mock.call_args_list],
                             ["joint_threat", "joint_threat"])
            self.assertEqual([call.kwargs["dark_card_policy"] for call in play_mock.call_args_list],
                             ["adversarial_guard", "marginal_guard"])

    def test_replay_audit_checks_every_command_and_winner(self):
        match = self.completed()
        audit = evaluation.audit_match(match)
        self.assertTrue(audit["verified"])
        self.assertEqual(audit["commands"], len(ReplayArchive.parse(match.replay_text).commands))
        self.assertEqual(audit["roots"], 1)
        with self.assertRaisesRegex(AssertionError, "winner"):
            evaluation.audit_match(replace(match, winner="protagonists"))

    def test_stop_resume_records_explicit_variants_and_audits(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "evaluation.json"
            base = ["evaluate", "--scenario", "official-fs-01-first-script", "--seed", "0",
                    "--workers", "1", "--output", str(path)]
            with (patch("sys.argv", [*base, "--max-jobs", "1"]),
                  patch.object(evaluation, "play", side_effect=self.fake_play) as play,
                  patch.object(evaluation, "source_digest", return_value="frozen"), redirect_stdout(StringIO())):
                evaluation.main()
                self.assertFalse(play.call_args.kwargs["matrix_proposals"])
            report = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(report["progress"], {"completed": 1, "planned": 2, "complete": False})
            with (patch("sys.argv", [*base, "--resume"]),
                  patch.object(evaluation, "play", side_effect=self.fake_play) as play,
                  patch.object(evaluation, "source_digest", return_value="frozen"), redirect_stdout(StringIO())):
                evaluation.main()
                self.assertTrue(play.call_args.kwargs["matrix_proposals"])
                self.assertTrue(play.call_args.kwargs["joint_culprits"])
                self.assertEqual(play.call_args.kwargs["matrix_variant_policy"], "prior")
            report = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(report["progress"]["complete"])
            self.assertEqual(report["paired_summary"]["both_black"], 1)
            with (patch("sys.argv", [*base, "--resume"]),
                  patch.object(evaluation, "play") as play,
                  patch.object(evaluation, "source_digest", return_value="changed"),
                  patch("sys.stderr", StringIO()), self.assertRaises(SystemExit)):
                evaluation.main()
            play.assert_not_called()

    def test_failure_keeps_completed_match_and_stays_incomplete(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "evaluation.json"
            with (patch("sys.argv", ["evaluate", "--scenario", "official-fs-01-first-script",
                                     "--seed", "0", "--workers", "1", "--output", str(path)]),
                  patch.object(evaluation, "play", side_effect=[self.completed(), RuntimeError("stopped")]),
                  patch.object(evaluation, "source_digest", return_value="frozen"),
                  redirect_stdout(StringIO()), self.assertRaisesRegex(RuntimeError, "stopped")):
                evaluation.main()
            report = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(report["results"]), 1)
            self.assertFalse(report["progress"]["complete"])
            self.assertEqual(report["failed_job"]["variant"], "matrix")

    def test_summary_excludes_incomplete_pairs_and_splits_outcomes(self):
        rows = [{"scenario": "a", "seed": 0, "variant": "legacy", "winner": "mastermind"},
                {"scenario": "a", "seed": 0, "variant": "matrix", "winner": "protagonists"},
                {"scenario": "b", "seed": 0, "variant": "matrix", "winner": "mastermind"}]
        summary = evaluation.paired_summary(rows)
        self.assertEqual(summary["completed_pairs"], 1)
        self.assertEqual(summary["improved"], 1)
        self.assertEqual(summary["variants"]["matrix"], {"matches": 2, "red_wins": 1})

    def test_partition_comparison_forwards_policy_and_uses_correct_pair_denominator(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "evaluation.json"
            argv = ["evaluate", "--scenario", "official-fs-01-first-script", "--seed", "0",
                    "--comparison", "matrix_partition", "--workers", "1", "--output", str(path)]
            with (patch("sys.argv", argv), patch.object(evaluation, "play", side_effect=self.fake_play) as calls,
                  patch.object(evaluation, "source_digest", return_value="frozen"), redirect_stdout(StringIO())):
                evaluation.main()
            self.assertEqual([call.kwargs["role_sampling_policy"] for call in calls.call_args_list],
                             ["importance", "exact_partition"])
            report = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(report["progress"]["complete"])
            self.assertEqual(report["paired_summary"]["comparison"], ["matrix", "partition"])
            self.assertEqual(report["paired_summary"]["completed_pairs"], 1)
            self.assertEqual(report["paired_summary"]["both_black"], 1)

    def test_source_change_inside_match_does_not_publish_a_completed_result(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "evaluation.json"
            with (patch("sys.argv", ["evaluate", "--scenario", "official-fs-01-first-script",
                                     "--seed", "0", "--workers", "1", "--output", str(path)]),
                  patch.object(evaluation, "play", side_effect=self.fake_play),
                  patch.object(evaluation, "source_digest", side_effect=["frozen", "frozen", "changed"]),
                  redirect_stdout(StringIO()), self.assertRaisesRegex(RuntimeError, "during the match")):
                evaluation.main()
            report = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(report["results"], [])
            self.assertFalse(report["progress"]["complete"])

    def test_fingerprints_preserve_order_and_existing_reports_are_not_overwritten(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "evaluation.json"
            # Completed report first; second fresh run must refuse overwriting.
            base = ["evaluate", "--scenario", "official-fs-01-first-script", "--seed", "0",
                    "--workers", "1", "--output", str(path)]
            with (patch("sys.argv", [*base, "--max-jobs", "1"]),
                  patch.object(evaluation, "play", side_effect=self.fake_play),
                  patch.object(evaluation, "source_digest", return_value="frozen"), redirect_stdout(StringIO())):
                evaluation.main()
            before = path.read_bytes()
            with (patch("sys.argv", base), patch("sys.stderr", StringIO()), self.assertRaises(SystemExit)):
                evaluation.main()
            self.assertEqual(before, path.read_bytes())
        class Library:
            def __init__(self, cast): self.cast = cast
            def get(self, sid): return {"cast": self.cast}
        self.assertNotEqual(evaluation.scenario_fingerprints(Library({"a": "key", "b": "ordinary"}), ("x",)),
                            evaluation.scenario_fingerprints(Library({"b": "ordinary", "a": "key"}), ("x",)))

    def test_default_ten_seeds_process_width_and_fixed_work(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "evaluation.json"
            with (patch("sys.argv", ["evaluate", "--scenario", "official-fs-01-first-script", "--output", str(path)]),
                  patch.object(evaluation, "run_jobs", return_value=iter(())) as run,
                  patch.object(evaluation, "source_digest", return_value="frozen"), redirect_stdout(StringIO())):
                evaluation.main()
            report = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(report["settings"]["seeds"], list(range(10)))
            self.assertTrue(report["settings"]["fixed_work"])
            self.assertEqual(run.call_args.kwargs["workers"], evaluation.DEFAULT_WORKERS)
            self.assertEqual(len(run.call_args.args[0]), 20)
            self.assertEqual(report["schema_version"], 2)

    def test_resume_non_prefix_completion_and_fixed_work_width_change(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "evaluation.json"
            base = ["evaluate", "--scenario", "official-fs-01-first-script", "--seed", "0", "--output", str(path)]
            def second_only(jobs, worker, **kwargs):
                job = jobs[1]
                row = worker(job)
                kwargs["validate"](job, row)
                yield job, row, None
            with (patch("sys.argv", [*base, "--workers", "4"]),
                  patch.object(evaluation, "run_jobs", side_effect=second_only),
                  patch.object(evaluation, "play", side_effect=self.fake_play),
                  patch.object(evaluation, "source_digest", return_value="frozen"), redirect_stdout(StringIO())):
                evaluation.main()
            report = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual([r["variant"] for r in report["results"]], ["matrix"])
            with (patch("sys.argv", [*base, "--resume", "--workers", "1"]),
                  patch.object(evaluation, "play", side_effect=self.fake_play) as run,
                  patch.object(evaluation, "source_digest", return_value="frozen"), redirect_stdout(StringIO())):
                evaluation.main()
            self.assertEqual(run.call_count, 1)
            self.assertFalse(run.call_args.kwargs["matrix_proposals"])
            report = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual([r["variant"] for r in report["results"]], ["legacy", "matrix"])
            self.assertTrue(report["progress"]["complete"])

    def test_resume_rejects_duplicate_unknown_ids_and_unverified_results(self):
        job = ("a", 0, "matrix")
        row = {"scenario": "a", "seed": 0, "variant": "matrix", "job_id": evaluation.job_id(job),
               "replay_audit": {"verified": True}}
        for rows in ((row, row), ({**row, "job_id": "wrong"},),
                     ({**row, "scenario": "unknown"},), ({**row, "replay_audit": {}},)):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                evaluation.completed_jobs(rows, (job,))

    def test_timed_resume_rejects_changed_worker_profile(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "evaluation.json"
            base = ["evaluate", "--scenario", "official-fs-01-first-script", "--seed", "0", "--no-fixed-work",
                    "--max-jobs", "1", "--output", str(path)]
            with (patch("sys.argv", [*base, "--workers", "1"]),
                  patch.object(evaluation, "play", side_effect=self.fake_play),
                  patch.object(evaluation, "source_digest", return_value="frozen"), redirect_stdout(StringIO())):
                evaluation.main()
            with (patch("sys.argv", [*base, "--workers", "2", "--resume"]),
                  patch.object(evaluation, "source_digest", return_value="frozen"),
                  patch("sys.stderr", StringIO()), self.assertRaises(SystemExit)):
                evaluation.main()
