"""Character-card catalog and special-rule conformance tests."""

import unittest

from tragedy_sim import Game, RuleError
from tragedy_sim.catalog import CHARACTERS, MODULES
from tragedy_sim.scenario import validate_scenario


class CharacterCatalogTests(unittest.TestCase):
    def test_supported_character_card_metadata(self):
        expected = {
            "student": ("男学生", "school", 2, ("student", "boy"), (), (("calm", 2),)),
            "girl": ("女学生", "school", 3, ("student", "girl"), (), (("calm", 2),)),
            "rich": ("大小姐", "school", 1, ("student", "girl"), (), (("befriend", 3),)),
            "class_rep": ("班长", "school", 2, ("student", "girl"), (), (("recover", 2),)),
            "teacher": ("教师", "school", 2, ("adult", "woman"), (), (("adjust", 3), ("reveal", 4))),
            "maiden": ("巫女", "shrine", 2, ("student", "girl"), ("city",), (("purify", 3), ("reveal", 5))),
            "outsider": ("异界人", "shrine", 2, ("girl",), ("hospital",), (("kill", 4), ("revive", 5))),
            "irregular": ("局外人", "school", 3, ("student", "boy"), (), (("reveal", 3),)),
            "police": ("刑警", "city", 3, ("adult", "man"), (), (("culprit", 4), ("guard", 5))),
            "worker": ("职员", "city", 2, ("adult", "man"), ("school",), (("reveal", 3),)),
            "informer": ("情报商", "city", 3, ("adult", "woman"), (), (("plot", 5),)),
            "idol": ("偶像", "city", 2, ("student", "girl"), (), (("calm", 3), ("befriend", 4))),
            "journalist": ("媒体人", "city", 2, ("adult", "man"), (), (("alarm", 2), ("intrigue", 2))),
            "forensic": ("鉴识官", "city", 3, ("adult", "man"), (), (("transfer", 2), ("reveal_dead", 5))),
            "doctor": ("医生", "hospital", 2, ("adult", "man"), (), (("adjust", 2), ("release", 3))),
            "patient": ("住院患者", "hospital", 2, ("boy",), ("shrine", "city", "school"), ()),
            "nurse": ("护士", "hospital", 3, ("adult", "woman"), (), (("calm", 2),)),
            "soldier": ("军人", "hospital", 3, ("adult", "man"), (), (("alarm", 2), ("protect", 5))),
            "henchman": ("手下", "school", 1, ("adult", "man"), (), (("prevent_incident", 3),)),
        }
        actual = {
            cid: (definition.name, definition.start, definition.limit, definition.traits,
                  definition.forbidden,
                  tuple((ability.id, ability.threshold) for ability in definition.abilities))
            for cid, definition in CHARACTERS.items()
        }
        self.assertEqual(actual, expected)
        self.assertTrue(all("irregular" in spec.characters for key, spec in MODULES.items()
                            if key != "MC"))
        self.assertIn("irregular", MODULES["MC"].characters)


class IrregularTests(unittest.TestCase):
    @staticmethod
    def scenario(role="killer"):
        return {"id": "irregular", "title": "局外人测试", "module": "FS",
                "days": 2, "loops": 2, "main_plot": "avenger", "subplots": ["rumor"],
                "cast": {"doctor": "brain", "maiden": "conspiracy", "irregular": role},
                "incidents": [], "table_talk": False}

    def test_script_role_must_exist_in_module_but_not_selected_plots(self):
        self.assertEqual(validate_scenario(self.scenario())["cast"]["irregular"], "killer")
        for role in ("ordinary", "brain", "vampire"):
            with self.subTest(role=role), self.assertRaises(RuleError):
                validate_scenario(self.scenario(role))

    def test_reveal_is_available_from_loop_two_and_cannot_be_refused(self):
        game = Game(self.scenario())
        game.state.phase = "goodwill"
        game.state.characters["irregular"].goodwill = 3
        self.assertFalse(any(choice.get("source") == "irregular" for choice in game.options("a")))
        game.state.loop = 2
        choices = game.options("a")
        index = next(i for i, choice in enumerate(choices, 1)
                     if choice.get("source") == "irregular")
        game.dispatch("a", "choose", index=index)
        self.assertEqual(len(game.options("m")), 1)
        game.dispatch("m", "choose", index=1)
        self.assertEqual(game.known_roles["irregular"]["role"], "killer")


if __name__ == "__main__":
    unittest.main()
