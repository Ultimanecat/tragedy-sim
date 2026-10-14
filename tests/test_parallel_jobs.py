"""Spawn isolation, completion holes, bounded failures and replay identity."""

import os
from time import sleep
import unittest

from benchmarks.parallel_jobs import job_id, peak_memory_mib, run_jobs


def replay_job(job):
    from tests.test_ai_proposal_regression_audit import completed_row
    from tragedy_sim.replay import ReplayArchive
    archive = ReplayArchive.parse(completed_row()["replay_text"])
    game = archive.verify()
    sleep(0.25 if job == 0 else 0.02)
    return {"job": job, "winner": game.winner, "commands": archive.commands, "pid": os.getpid()}


def fail_job(job):
    if job == 1:
        raise ValueError("deliberate failure")
    sleep(0.3)
    return job


class ParallelJobsTests(unittest.TestCase):
    def test_spawn_results_match_serial_replay_and_do_not_run_in_parent(self):
        serial = list(run_jobs((0, 1), replay_job, workers=1))
        parallel = list(run_jobs((0, 1), replay_job, workers=2))
        self.assertTrue(all(error is None for _, _, error in parallel))
        for job, row, _ in parallel:
            reference = next(r for key, r, _ in serial if key == job)
            self.assertEqual(row["commands"], reference["commands"])
            self.assertEqual(row["winner"], reference["winner"])
            self.assertNotEqual(row["pid"], os.getpid())

    def test_failure_drains_running_success_and_does_not_launch_more(self):
        outcomes = list(run_jobs((0, 1, 2, 3), fail_job, workers=2))
        self.assertEqual({job for job, _, _ in outcomes}, {0, 1})
        self.assertEqual(next(result for job, result, _ in outcomes if job == 0), 0)
        self.assertIsInstance(next(error for job, _, error in outcomes if job == 1), ValueError)

    def test_parent_validation_stops_launching_and_serial_failure_is_explicit(self):
        def reject(job, row):
            if job == 1:
                raise ValueError("reject parent checkpoint")
        outcomes = list(run_jobs((0, 1, 2), replay_job, workers=2, validate=reject))
        self.assertEqual({job for job, _, _ in outcomes}, {0, 1})
        self.assertTrue(any(isinstance(error, ValueError) for _, _, error in outcomes))
        serial = list(run_jobs((1, 2), fail_job, workers=1))
        self.assertEqual(len(serial), 1)
        self.assertIsInstance(serial[0][2], ValueError)

    def test_invalid_width_and_job_keys(self):
        for value in (0, -1, True, "2"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                list(run_jobs((), replay_job, workers=value))
        self.assertNotEqual(job_id(("x", 1, "matrix")), job_id(("x", 1, "partition")))
        memory = peak_memory_mib()
        self.assertTrue(memory is None or memory > 0)
