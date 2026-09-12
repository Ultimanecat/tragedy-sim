import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tragedy_sim.engine import RuleError
from tragedy_sim.scenario import example_scenario
from tragedy_sim.scenario_library import ScenarioLibrary


class ScenarioLibraryTests(unittest.TestCase):
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
