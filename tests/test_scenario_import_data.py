"""Offline regression checks for imported script provenance and runtime boundaries."""

from collections import Counter
import json
from pathlib import Path
import random
import unittest

from tragedy_sim.engine import RuleError
from tragedy_sim.game import Game
from tragedy_sim.scenario import load_scenario
from tragedy_sim.scenario_library import DEFAULT_SCENARIO_ROOT, ScenarioLibrary


REPOSITORY_ROOT = DEFAULT_SCENARIO_ROOT.parent
SOURCE_ROOT = DEFAULT_SCENARIO_ROOT / "sources" / "tragic-aiplay"


def read_data(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def setup_key(scenario):
    return {
        "module": scenario["module"], "days": scenario["days"],
        "loop_options": scenario.get("loop_options", [scenario["loops"]]),
        "main_plot": scenario["main_plot"], "subplots": sorted(scenario["subplots"]),
        "cast": scenario["cast"], "incidents": scenario["incidents"],
        "character_options": scenario.get("character_options", {}),
        "special_rules": scenario.get("special_rules", {}),
        "role_slots": scenario.get("role_slots"),
        "table_talk": scenario.get("table_talk", False),
    }


class ImportedScenarioDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.collection = read_data(SOURCE_ROOT / "collection-index.json")
        cls.official = read_data(SOURCE_ROOT / "import-index.json")
        cls.community = read_data(SOURCE_ROOT / "community-index.json")

    def test_collection_and_independent_indexes_cover_every_archive_once(self):
        combined = self.official["scripts"] + self.community["scripts"]
        codes = [entry["source_code"] for entry in self.collection["scripts"]]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertCountEqual(codes, [entry["source_code"] for entry in combined])
        self.assertEqual(self.collection["counts"], {
            "total": len(combined), "official": len(self.official["scripts"]),
            "community": len(self.community["scripts"]),
        })
        indexed = {REPOSITORY_ROOT / entry["data_file"] for entry in combined}
        archives = {path for path in SOURCE_ROOT.rglob("*.json")
                    if path.name not in {"collection-index.json", "community-index.json", "import-index.json"}}
        self.assertEqual(indexed, archives)
        collection_by_code = {entry["source_code"]: entry for entry in self.collection["scripts"]}
        for origin, index in (("official", self.official), ("community", self.community)):
            self.assertEqual(index["counts"], dict(Counter(entry["status"] for entry in index["scripts"])))
            for entry in index["scripts"]:
                with self.subTest(entry["source_code"]):
                    self.assertEqual(entry["origin"], origin)
                    for key, value in entry.items():
                        self.assertEqual(collection_by_code[entry["source_code"]][key], value)

    def test_origin_and_special_rule_labels_match_source_and_counts(self):
        groups = Counter()
        for entry in self.collection["scripts"]:
            with self.subTest(entry["source_code"]):
                archive = read_data(REPOSITORY_ROOT / entry["data_file"])
                origin = "official" if "G" in entry["source_code"] else "community"
                has_rules = any(str(rule).strip() for rule in archive["public_setup"]["special_rules"])
                labels = {"origin": origin, "origin_label": "官方" if origin == "official" else "社区",
                          "has_special_rules": has_rules,
                          "special_rules_label": "有特殊规则" if has_rules else "无特殊规则"}
                self.assertIs(type(archive["has_special_rules"]), bool)
                for key, value in labels.items():
                    self.assertEqual(archive[key], value)
                    self.assertEqual(entry[key], value)
                self.assertTrue(archive["source_setup_text"].strip())
                groups[origin, has_rules] += 1
        actual = {(group["origin"], group["has_special_rules"]): group["count"]
                  for group in self.collection["groups"]}
        self.assertEqual(actual, dict(groups))
        self.assertEqual(self.community["special_rules_counts"],
                         dict(Counter(entry["special_rules_label"] for entry in self.community["scripts"])))

    def test_imported_and_duplicate_setups_agree_with_playable_files(self):
        for entry in self.collection["scripts"]:
            if entry["status"] not in {"imported", "already_present"}:
                continue
            with self.subTest(entry["source_code"]):
                archive = read_data(REPOSITORY_ROOT / entry["data_file"])
                path = REPOSITORY_ROOT / entry["playable_file"]
                self.assertEqual(path.parent, DEFAULT_SCENARIO_ROOT)
                playable = load_scenario(path)
                self.assertEqual(setup_key(playable), setup_key(archive["normalized_setup"]))
                self.assertFalse(entry["issues"])
                self.assertFalse(entry["has_special_rules"])
                if entry["origin"] == "community":
                    self.assertIn("[社区·无特殊规则]", playable["title"])

    def test_archives_and_blocked_candidates_stay_out_of_public_catalog(self):
        library = ScenarioLibrary()
        catalog = library.list()
        for item in catalog:
            self.assertEqual(set(item), {"id", "title", "module", "days", "loops", "loop_options", "source"})
        for entry in self.collection["scripts"]:
            if entry["status"] in {"imported", "already_present"}:
                continue
            with self.subTest(entry["source_code"]):
                archive = read_data(REPOSITORY_ROOT / entry["data_file"])
                candidate_id = archive["normalized_setup"]["id"]
                self.assertTrue(entry["issues"])
                self.assertFalse(any(item["id"] == candidate_id or item["id"].startswith(candidate_id + "-")
                                     for item in catalog))
                with self.assertRaisesRegex(RuleError, "剧本不存在"):
                    library.get(candidate_id)
                if entry["status"].startswith("blocked"):
                    self.assertIsNone(entry["playable_file"])

    def test_prologue_source_conflict_is_preserved_without_overwriting_existing_script(self):
        archive = read_data(SOURCE_ROOT / "btx_07g.json")
        existing = load_scenario(REPOSITORY_ROOT / archive["playable_file"])
        self.assertEqual(archive["status"], "existing_data_conflict")
        self.assertEqual(archive["normalized_setup"]["cast"]["student"], "loved")
        self.assertEqual(archive["normalized_setup"]["cast"]["girl"], "lover")
        self.assertEqual(existing["cast"]["student"], "lover")
        self.assertEqual(existing["cast"]["girl"], "loved")

    def test_imported_community_loop_variants_complete_legal_action_walks(self):
        library = ScenarioLibrary()
        imported_ids = {read_data(REPOSITORY_ROOT / entry["playable_file"])["id"]
                        for entry in self.community["scripts"] if entry["status"] == "imported"}
        variants = [item for item in library.list()
                    if any(item["id"] == base or item["id"].startswith(base + "-") for base in imported_ids)]
        self.assertTrue(variants)
        for item in variants:
            with self.subTest(item["id"]):
                game = Game(library.get(item["id"]))
                randomizer = random.Random(20261010)
                for _ in range(1000):
                    if game.winner:
                        break
                    commands = [command for actor in ("m", "a", "b", "c")
                                for command in game.legal_actions(actor)]
                    self.assertTrue(commands, (item["id"], game.state.phase))
                    completing = [command for command in commands if command["action"] == "next"]
                    command = dict(randomizer.choice(completing or commands))
                    actor, action = command.pop("actor"), command.pop("action")
                    game.dispatch(actor, action, **command)
                self.assertIsNotNone(game.winner, item["id"])


if __name__ == "__main__":
    unittest.main()
