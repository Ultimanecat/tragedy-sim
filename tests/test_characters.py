"""Character-card catalog and special-rule conformance tests."""

import unittest

from tragedy_sim import Game, RuleError
from tragedy_sim.catalog import CHARACTERS, MODULES
from tragedy_sim.effects.vocabulary import op, option
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
            "godly": ("神灵", "shrine", 3, ("man", "woman"), (), (("culprit", 3), ("purify", 5))),
            "police": ("刑警", "city", 3, ("adult", "man"), (), (("culprit", 4), ("guard", 5))),
            "worker": ("职员", "city", 2, ("adult", "man"), ("school",), (("reveal", 3),)),
            "informer": ("情报商", "city", 3, ("adult", "woman"), (), (("plot", 5),)),
            "idol": ("偶像", "city", 2, ("student", "girl"), (), (("calm", 3), ("befriend", 4))),
            "journalist": ("媒体人", "city", 2, ("adult", "man"), (), (("alarm", 2), ("intrigue", 2))),
            "boss": ("大人物", "city", 4, ("adult", "man"), (), (("reveal", 5),)),
            "forensic": ("鉴识官", "city", 3, ("adult", "man"), (), (("transfer", 2), ("reveal_dead", 5))),
            "doctor": ("医生", "hospital", 2, ("adult", "man"), (), (("adjust", 2), ("release", 3))),
            "patient": ("住院患者", "hospital", 2, ("boy",), ("shrine", "city", "school"), ()),
            "nurse": ("护士", "hospital", 3, ("adult", "woman"), (), (("calm", 2),)),
            "scholar": ("学者", "hospital", 2, ("adult", "man"), (), (("reset", 3),)),
            "illusion": ("幻想", "shrine", 3, ("fictional", "woman"), (), (("relocate", 3), ("vanish", 4))),
            "ai": ("A.I.", "city", 4, ("construct",), ("hospital", "shrine", "school"), (("incident", 3),)),
            "soldier": ("军人", "hospital", 3, ("adult", "man"), (), (("alarm", 2), ("protect", 5))),
            "black_cat": ("黑猫", "shrine", 0, ("animal",), (), ()),
            "transfer_student": ("转校生", "school", 2, ("student", "girl"), (), (("convert", 2),)),
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
        additions = {"godly", "boss", "scholar", "illusion", "ai", "black_cat",
                     "transfer_student"}
        self.assertTrue(all(additions <= set(spec.characters) for spec in MODULES.values()))


def special_scenario(character, *, role="ordinary", options=None, incidents=None,
                     days=3, loops=3):
    cast = {"doctor": "brain", "maiden": "conspiracy", character: role}
    if role == "brain":
        cast["doctor"] = "ordinary"
    return {"id": f"character-{character}", "title": f"{character} 测试", "module": "FS",
            "days": days, "loops": loops, "main_plot": "avenger", "subplots": ["rumor"],
            "cast": cast, "incidents": incidents or [], "table_talk": False,
            "character_options": options or {}}


def choose(game, actor, predicate):
    choices = game.options(actor)
    index = next((i for i, item in enumerate(choices, 1) if predicate(item)), None)
    if index is None:
        raise AssertionError(f"Missing choice for {actor}: {choices}")
    game.dispatch(actor, "choose", index=index)


def use_ability(game, source, ability, target=None):
    actor = game.controller
    choose(game, actor, lambda item: item.get("source") == source
           and item.get("ability") == ability
           and (target is None or any(effect.get("target") == target
                                      for effect in item.get("effects", []))))
    if game.state.phase == "refusal":
        choose(game, "m", lambda item: item.get("accept"))


class AddedCharacterTests(unittest.TestCase):
    def test_script_options_are_required_and_ai_cannot_be_ordinary(self):
        for character in ("godly", "boss", "transfer_student"):
            with self.subTest(character=character), self.assertRaises(RuleError):
                validate_scenario(special_scenario(character))
        with self.assertRaises(RuleError):
            validate_scenario(special_scenario("ai"))
        validated = validate_scenario(special_scenario(
            "boss", options={"boss": {"territory": "hospital"}}))
        self.assertEqual(validated["character_options"]["boss"]["territory"], "hospital")

    def test_godly_enters_on_selected_loop_and_reveals_future_culprit(self):
        scenario = special_scenario(
            "godly", options={"godly": {"entry_loop": 2}},
            incidents=[{"day": 3, "kind": "suicide", "culprit": "doctor"}])
        game = Game(scenario)
        self.assertFalse(game.state.characters["godly"].present)
        self.assertNotIn("godly", [character.id for character in game._living()])
        self.assertNotIn("character_options", game.view("a").get("secret", {}))
        self.assertEqual(game.view("m")["secret"]["character_options"],
                         {"godly": {"entry_loop": 2}})
        game.state.loop = 2
        game._apply_character_setup()
        self.assertTrue(game.state.characters["godly"].present)
        game.state.phase = "goodwill"
        game.state.characters["godly"].goodwill = 5
        use_ability(game, "godly", "culprit")
        self.assertEqual(game.known_culprits, {"3": "doctor"})
        game.state.characters["godly"].intrigue = 1
        use_ability(game, "godly", "purify", "godly")
        self.assertEqual(game.state.characters["godly"].intrigue, 0)

    def test_boss_uses_role_and_goodwill_abilities_from_public_territory(self):
        game = Game(special_scenario(
            "boss", role="brain", options={"boss": {"territory": "hospital"}}))
        self.assertEqual(game.view("a")["characters"]["boss"]["territory"], "hospital")
        game.state.phase = "master_abilities"
        choices = game.options("m")
        self.assertTrue(any(item.get("key") == "brain:boss"
                            and item["effects"][0].get("target") == "hospital"
                            for item in choices))
        game.state.phase = "goodwill"
        game.state.characters["boss"].goodwill = 5
        use_ability(game, "boss", "reveal", "doctor")
        self.assertEqual(game.known_roles["doctor"]["role"], "ordinary")

    def test_scholar_loop_marker_and_reset_include_guard(self):
        game = Game(special_scenario("scholar"))
        self.assertEqual(game.state.phase, "decision")
        choose(game, "m", lambda item: item["effects"][0].get("counter") == "paranoia")
        scholar = game.state.characters["scholar"]
        self.assertEqual(scholar.paranoia, 1)
        scholar.goodwill, scholar.intrigue = 3, 2
        game.guards["scholar"] = 1
        game.state.phase = "goodwill"
        use_ability(game, "scholar", "reset")
        self.assertEqual((scholar.goodwill, scholar.paranoia, scholar.intrigue,
                          game.guards["scholar"]), (0, 0, 0, 0))

    def test_illusion_cannot_be_targeted_and_repeats_board_action(self):
        game = Game(special_scenario("illusion"))
        game.state.phase = "mastermind"
        with self.assertRaises(RuleError):
            game.dispatch("m", "play", card="h", target="illusion")
        for card, target in (("h", "shrine"), ("p1a", "school"), ("p1b", "city")):
            game.dispatch("m", "play", card=card, target=target)
        for actor, target in (("a", "shrine"), ("b", "city"), ("c", "hospital")):
            game.dispatch(actor, "play", card="g1", target=target)
        game.dispatch("m", "resolve")
        game.dispatch("m", "next")
        illusion = game.state.characters["illusion"]
        self.assertEqual((illusion.location, illusion.goodwill), ("hospital", 1))

    def test_illusion_goodwill_may_relocate_then_leave_for_the_loop(self):
        game = Game(special_scenario("illusion"))
        game.state.phase = "goodwill"
        game.state.characters["illusion"].goodwill = 4
        use_ability(game, "illusion", "relocate", "maiden")
        self.assertEqual(game.state.characters["maiden"].location, "hospital")
        use_ability(game, "illusion", "vanish")
        self.assertFalse(game.state.characters["illusion"].present)
        self.assertNotIn("illusion", [c.id for c in game._living()])

    def test_ai_counts_every_marker_for_its_incident_threshold(self):
        game = Game(special_scenario(
            "ai", role="brain",
            incidents=[{"day": 1, "kind": "suicide", "culprit": "ai"}]))
        game.state.characters["ai"].goodwill = 4
        game.state.phase = "incident"
        game.dispatch("m", "next")
        self.assertFalse(game.state.characters["ai"].alive)
        self.assertTrue(game.incident_records[0]["happened"])

    def test_ai_simulates_public_event_without_recording_occurrence(self):
        game = Game(special_scenario(
            "ai", role="brain",
            incidents=[{"day": 1, "kind": "murder", "culprit": "doctor"}]))
        game.state.characters["doctor"].location = "city"
        game.state.characters["ai"].goodwill = 3
        game.state.phase = "goodwill"
        use_ability(game, "ai", "incident")
        self.assertEqual(game.controller, "a")
        choose(game, "a", lambda item: any(effect.get("target") == "doctor"
                                             for effect in item["effects"]))
        self.assertFalse(game.state.characters["doctor"].alive)
        self.assertEqual(game.incident_records, [])
        self.assertIsNone(game._simulated_incident)
        self.assertTrue(any(event["kind"] == "simulated_incident_ended"
                            for event in game.state.events))

    def test_ai_only_redirects_mastermind_decisions_to_the_leader(self):
        game = Game(special_scenario(
            "ai", role="brain",
            incidents=[{"day": 1, "kind": "murder", "culprit": "doctor"}]))
        game._choice_actor_override = "a"
        game._return_phase = "goodwill"
        game._queue = [op("choice", actor="b", prompt="由主人公 B 决定",
                          options=[option("确认", [])])]
        game._drain()
        self.assertEqual(game.controller, "b")

    def test_black_cat_adds_shrine_intrigue_and_nullifies_its_incident(self):
        game = Game(special_scenario(
            "black_cat", incidents=[{"day": 1, "kind": "suicide", "culprit": "black_cat"}]))
        self.assertEqual(game.state.locations["shrine"], 1)
        game._incident_effect = True  # A previous day's non-board effect must not leak.
        game.state.phase = "incident"
        game.dispatch("m", "next")
        self.assertTrue(game.state.characters["black_cat"].alive)
        self.assertEqual(game.incident_records[0],
                         {"day": 1, "kind": "suicide", "happened": True, "effective": False})

    def test_transfer_student_arrives_on_selected_day_and_converts_intrigue(self):
        game = Game(special_scenario(
            "transfer_student", options={"transfer_student": {"entry_day": 2}}))
        transfer = game.state.characters["transfer_student"]
        self.assertFalse(transfer.present)
        game.state.round = 2
        game.state.phase = "day_start"
        game.dispatch("m", "next")
        self.assertTrue(transfer.present)
        self.assertEqual(transfer.location, "school")
        game.state.characters["doctor"].location = "school"
        game.state.characters["doctor"].intrigue = 1
        transfer.goodwill = 2
        game.state.phase = "goodwill"
        use_ability(game, "transfer_student", "convert", "doctor")
        self.assertEqual((game.state.characters["doctor"].intrigue,
                          game.state.characters["doctor"].goodwill), (0, 1))


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
