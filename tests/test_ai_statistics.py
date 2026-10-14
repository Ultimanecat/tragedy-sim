import unittest

from benchmarks.ai_statistics import binomial_summary, paired_outcomes


class AiStatisticsTests(unittest.TestCase):
    def test_wilson_bounds_and_empty_counts(self):
        self.assertIsNone(binomial_summary(0, 0)["wilson95"])
        bounds = binomial_summary(5, 10)["wilson95"]
        self.assertAlmostEqual(bounds[0], 0.23659, places=4)
        self.assertAlmostEqual(bounds[1], 0.76341, places=4)
        for wins in (0, 10):
            result = binomial_summary(wins, 10)
            self.assertTrue(0 <= result["wilson95"][0] <= result["win_rate"] <= result["wilson95"][1] <= 1)

    def test_paired_counts_and_exact_discordance_probability(self):
        rows = [{"old": {"winner": "mastermind"}, "new": {"winner": "protagonists"}}] * 6
        result = paired_outcomes(rows, ("old", "new"))
        self.assertEqual(result["improved"], 6)
        self.assertEqual(result["paired_only"]["new"]["wins"], 6)
        self.assertEqual(result["exact_paired_binomial_p"], 0.03125)
        self.assertEqual(paired_outcomes([], ("old", "new"))["exact_paired_binomial_p"], 1)
