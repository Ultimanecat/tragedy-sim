"""Developer benchmark telemetry regressions."""

import unittest

from benchmarks.ai_self_play import _ability_usage


class AbilityUsageTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
