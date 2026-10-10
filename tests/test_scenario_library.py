import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tragedy_sim.engine import RuleError
from tragedy_sim.game import Game
from tragedy_sim.scenario import example_scenario
from tragedy_sim.scenario_library import DEFAULT_SCENARIO_ROOT, ScenarioLibrary


class ScenarioLibraryTests(unittest.TestCase):
    def test_bundled_scripts_and_every_loop_variant_validate_and_start(self):
        library = ScenarioLibrary()
        bundled = [item for item in library.list() if item["source"] == "library"]
        expected = {}
        for path in DEFAULT_SCENARIO_ROOT.glob("*.json"):
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            for suffix, loops in zip(("", "-easy", "-very-easy"),
                                     raw.get("loop_options", [raw["loops"]]), strict=False):
                expected[raw["id"] + suffix] = (raw["module"], loops)
        self.assertTrue(expected)
        self.assertCountEqual([item["id"] for item in bundled], expected)
        for item in bundled:
            with self.subTest(item["id"]):
                self.assertEqual((item["module"], item["loops"]), expected[item["id"]])
                self.assertEqual(item["loop_options"], [item["loops"]])
                game = Game(library.get(item["id"]))
                self.assertEqual(game.scenario["id"], item["id"])

    def test_nested_source_archives_are_not_discovered(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            scenario = example_scenario("FS")
            scenario.update(id="playable-fs", title="可玩目录测试")
            (root / "playable.json").write_text(json.dumps(scenario), encoding="utf-8")
            archive = root / "sources" / "community"
            archive.mkdir(parents=True)
            (archive / "unimplemented.json").write_text(
                json.dumps({"id": "unsupported-source", "loops": "无限", "cast": {"仙人": "自定义身份"}}),
                encoding="utf-8")
            library = ScenarioLibrary(root)
            self.assertEqual([item["id"] for item in library.list()
                              if item["source"] == "library"], ["playable-fs"])
            with self.assertRaisesRegex(RuleError, "剧本不存在"):
                library.get("unsupported-source")

    def test_loop_choices_are_distinct_difficulty_entries(self):
        library = ScenarioLibrary()
        standard = library.get("official-btx-08-mirror-passcode")
        easy = library.get("official-btx-08-mirror-passcode-easy")

        self.assertEqual((standard["loops"], standard["loop_options"]), (3, [3]))
        self.assertEqual((easy["loops"], easy["loop_options"]), (4, [4]))
        self.assertEqual(easy["title"], "Mirror Passcode (Easy)")
        self.assertEqual(standard["cast"], easy["cast"])
        self.assertEqual(standard["incidents"], easy["incidents"])

        very_easy = library.get(
            "official-btx-02-traditional-ensemble-murder-very-easy")
        self.assertEqual(very_easy["loops"], 5)
        self.assertEqual(very_easy["loop_options"], [5])

    def test_official_script_special_rules_are_applied(self):
        library = ScenarioLibrary()
        milestone = Game(library.get("official-mc-12-milestone"))
        self.assertNotIn("fg", milestone.state.hands["m"])

        academic = Game(library.get("official-mc-10-unknowns-of-academic-city"))
        self.assertEqual(set(academic._ability_locations("boss")),
                         {"hospital", "shrine", "city", "school"})

        festival = Game(library.get("official-mc-11-festival-of-fools"))
        self.assertEqual(festival.state.characters["henchman"].location, "school")
        self.assertFalse(any(option.get("source") == "henchman"
                             for option in festival.options("m")))

    def test_tutorial_catalog_contains_public_metadata_only(self):
        items = ScenarioLibrary(root=Path("missing-scenario-directory")).list("BTX")
        self.assertEqual([item["id"] for item in items], ["silent-town-btx"])
        self.assertEqual(items[0]["source"], "tutorial")
        self.assertNotIn("cast", items[0])
        self.assertNotIn("incidents", items[0])

    def test_external_scenario_is_discovered_and_resolved_by_id(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            scenario = example_scenario("BTX")
            scenario.update(id="library-btx-01", title="资料库测试剧本")
            (root / "btx-01.json").write_text(json.dumps(scenario), encoding="utf-8")
            library = ScenarioLibrary(root)

            summary = next(item for item in library.list() if item["id"] == "library-btx-01")
            self.assertEqual((summary["module"], summary["days"], summary["source"]),
                             ("BTX", 3, "library"))
            loaded = library.get("library-btx-01")
            self.assertEqual(loaded["cast"], scenario["cast"])
            loaded["cast"]["student"] = "key"
            self.assertEqual(library.get("library-btx-01")["cast"]["student"], "ordinary")

    def test_invalid_file_and_duplicate_id_fail_loudly(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "broken.json").write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(RuleError, "broken.json"):
                ScenarioLibrary(root).list()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "duplicate.json").write_text(json.dumps(example_scenario("BTX")), encoding="utf-8")
            with self.assertRaisesRegex(RuleError, "ID 重复"):
                ScenarioLibrary(root).list()


if __name__ == "__main__":
    unittest.main()
