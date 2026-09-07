"""Terminology configuration and localized timing tests."""

import unittest

from tragedy_sim.i18n import format_timepoint, label, locale, normalize_language, terminology
from tragedy_sim.model import TimingId


class InternationalizationTests(unittest.TestCase):
    def test_supported_locales_and_aliases(self):
        self.assertEqual(normalize_language(None), "zh")
        self.assertEqual(normalize_language("zh-CN"), "zh")
        self.assertEqual(normalize_language("ja-JP"), "ja")
        for language in ("zh", "en", "ja"):
            self.assertEqual(locale(language)["meta"]["name"], label("meta", "name", language))

    def test_every_timing_has_three_human_labels(self):
        for timing in TimingId:
            values = [format_timepoint(timing.value, 2, 3, language)
                      for language in ("zh", "en", "ja")]
            self.assertTrue(all("{" not in value for value in values))
        self.assertEqual(format_timepoint("day_end", 2, 3), "第 3 天结束时")
        self.assertEqual(format_timepoint("loop_end", 2, 3, "en"), "At the end of Loop 2")
        self.assertEqual(format_timepoint("mastermind_ability", 2, 3, "ja"),
                         "3 日目・脚本家能力フェイズ")

    def test_entity_terminology_is_complete(self):
        data = terminology()
        for group in ("characters", "roles", "incidents"):
            for key, translations in data[group].items():
                self.assertEqual(set(translations), {"zh", "en", "ja"}, (group, key))
                self.assertTrue(all(translations.values()), (group, key))


if __name__ == "__main__":
    unittest.main()
