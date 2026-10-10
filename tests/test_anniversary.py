"""Optional anniversary compositions, including hidden-information/replay checks."""

from copy import deepcopy
import json
import random
import unittest

from tragedy_sim.cards import ACTORS, deck
from tragedy_sim.engine import RuleError
from tragedy_sim.game import Game
from tragedy_sim.i18n import label
from tragedy_sim.hotseat import character_details, module_roles, public_knowledge, public_log, public_rules
from tragedy_sim.model import TimingId
from tragedy_sim.rooms import RoomService
from tragedy_sim.replay import dumps, ReplayArchive
from tragedy_sim.scenario import example_scenario, validate_scenario
from tragedy_sim.service import GameService


class AnniversaryTests(unittest.TestCase):
    def game(self, module="BTX+"):
        return Game(example_scenario(module))

    def test_examples_have_one_extra_civilian_role_and_no_initial_cards(self):
        for module in ("BTX+", "MZ+"):
            game = self.game(module)
            self.assertEqual(game.ruleset.id, module)
            self.assertEqual(list(game.scenario["cast"].values()).count("fragment"), 1)
            for actor in ACTORS:
                self.assertEqual(set(game.state.hands[actor]), set(deck(actor, module[:-1])))
            self.assertIsNone(game.winner)

    def test_fragment_required_without_extra_plot_and_basic_rules_reject_it(self):
        for module in ("BTX+", "MZ+"):
            data = example_scenario(module)
            data["subplots"] = example_scenario(module[:-1])["subplots"]
            if module == "MZ+":
                data["cast"]["patient"] = "prophet"
                data["incidents"][1]["kind"] = "suicide"
            validate_scenario(data)
            with self.assertRaises(RuleError):
                validate_scenario({**data, "module": module[:-1]})
            data["cast"]["student"] = "ordinary"
            with self.assertRaises(RuleError):
                validate_scenario(data)

    def test_copycat_can_duplicate_fragment_without_consuming_another_slot(self):
        data = example_scenario("BTX+")
        data["cast"]["copycat"] = "fragment"
        data["character_options"]["copycat"] = {"role_source": "student"}
        validate_scenario(data)
        data["cast"]["patient"] = "fragment"
        with self.assertRaises(RuleError):
            validate_scenario(data)

    def test_ai_cannot_be_converted_from_civilian(self):
        data = example_scenario("BTX+")
        data["cast"]["student"] = "ordinary"
        data["cast"]["ai"] = "fragment"
        with self.assertRaises(RuleError):
            validate_scenario(data)

    def test_role_slot_overrides_cannot_add_another_fragment(self):
        data = example_scenario("BTX+")
        data["cast"]["patient"] = "fragment"
        data["role_slots"] = {"key": 1, "brain": 1, "killer": 1, "conspiracy": 1, "fragment": 1}
        with self.assertRaises(RuleError):
            validate_scenario(data)

    def test_plot_grants_even_despair_and_final_hope_only_for_that_loop(self):
        for module in ("BTX+", "MZ+"):
            game = self.game(module)
            game._resolve_loop_end(True)
            game._new_loop()
            self.assertIn("ahr_d1", game.state.hands["m"])
            self.assertNotIn("ahr_h1", game.state.hands["a"])
            game._resolve_loop_end(True)
            game._new_loop()
            self.assertNotIn("ahr_d1", game.state.hands["m"])
            for actor in ("a", "b", "c"):
                self.assertEqual(game.state.hands[actor].count("ahr_h1"), 1)
            grants = [event for event in game.state.events if event["kind"] == "special_card_gained"]
            self.assertTrue(grants)
            for event in grants:
                self.assertEqual(event["timing"], TimingId.LOOP_START.value)
                self.assertNotIn("student", str(event))
                self.assertNotIn("fragment", str(event))
                self.assertNotIn("anniversary_beyond_worldline", str(event))

    def test_final_first_loop_gets_hope_but_not_despair(self):
        data = example_scenario("BTX+")
        data["loops"] = 1
        game = Game(data)
        self.assertIn("ahr_h1", game.state.hands["a"])
        self.assertNotIn("ahr_d1", game.state.hands["m"])

    def test_fragment_previous_dead_friendly_and_effective_goodwill(self):
        for module in ("BTX+", "MZ+"):
            for dead, goodwill, hope, expected in ((True, 4, 0, "ahr_d1"),
                                                    (False, 2, 0, "ahr_h1"),
                                                    (False, 1, 1, "ahr_h1"),
                                                    (False, 1, 0, None)):
                with self.subTest(module=module, dead=dead, goodwill=goodwill, hope=hope):
                    game = self.game(module)
                    game.scenario["subplots"] = []  # Isolate the role, bypass plot grants in this unit test.
                    char = game.state.characters["student"]
                    char.alive, char.goodwill, char.hope = not dead, goodwill, hope
                    game._resolve_loop_end(True)
                    game._new_loop()
                    cards = {cid for hand in game.state.hands.values() for cid in hand}
                    self.assertEqual(cards & {"ahr_d1", "ahr_h1"}, {expected} if expected else set())

    def test_inactive_part_timer_reverse_side_does_not_grant_dead_fragment(self):
        data = example_scenario("BTX+")
        data["cast"]["student"] = "ordinary"
        data["cast"]["part_timer"] = "fragment"
        game = Game(data)
        game.scenario["subplots"] = []
        self.assertNotIn("part_timer_question", game.state.characters)
        game._resolve_loop_end(True)
        game._new_loop()
        self.assertNotIn("ahr_d1", game.state.hands["m"])

    def test_multiple_sources_grant_one_copy_and_reset_clears_discarded(self):
        game = self.game()
        game.state.characters["student"].alive = False
        game._resolve_loop_end(True)
        game._new_loop()
        self.assertEqual(game.state.hands["m"].count("ahr_d1"), 1)
        game.state.hands["m"].remove("ahr_d1")
        game.state.discarded["m"].append("ahr_d1")
        game.state.characters["student"].goodwill = 2
        game._resolve_loop_end(True)
        game._new_loop()
        self.assertEqual(game.state.hands["a"].count("ahr_h1"), 1)
        self.assertNotIn("ahr_d1", game.state.discarded["m"])

    def test_effective_counts_leave_physical_markers_unchanged(self):
        for module in ("BTX+", "MZ+"):
            game = self.game(module)
            char = game.state.characters["student"]
            char.goodwill, char.paranoia, char.intrigue = 1, 2, 1
            char.hope, char.despair = 4, 2
            self.assertEqual([game._count(char, name) for name in ("goodwill", "paranoia", "intrigue")], [5, 4, 0])
            self.assertEqual((char.goodwill, char.paranoia, char.intrigue), (1, 2, 1))
            self.assertEqual(game._incident_score(char), 4)

    def test_base_btx_does_not_apply_hope_and_despair(self):
        game = self.game("BTX")
        char = game.state.characters["student"]
        char.hope, char.despair = 5, 5
        self.assertEqual(game._count(char, "goodwill"), 0)
        self.assertEqual(game._count(char, "paranoia"), 0)

    def test_hope_unlocks_goodwill_and_prevents_traveler_failure(self):
        game = self.game()
        char = game.state.characters["doctor"]
        char.hope = 2
        game.state.phase = "goodwill"
        self.assertTrue(any(item.get("source") == "doctor" for item in game.options(game.controller)))
        game.roles["doctor"] = "time_traveler"
        game.state.round = game.scenario["days"]
        game.state.phase = "day_end"
        game._night_forced_done = True
        char.hope = 3
        self.assertFalse(any(item.get("key") == "time_traveler:doctor" for item in game.options("m")))
        char.hope = 2
        self.assertTrue(any(item.get("key") == "time_traveler:doctor" for item in game.options("m")))

    def test_hope_reduces_sealed_contract_failure(self):
        game = self.game()
        girl = game.state.characters["girl"]
        girl.intrigue = 2
        girl.hope = 1
        self.assertFalse(game.ruleset.operations["_plot_loss"](game, "sign"))
        girl.despair = 1
        self.assertTrue(game.ruleset.operations["_plot_loss"](game, "sign"))

    def test_refusal_hope_despair_and_unrefusable_precedence(self):
        for module in ("BTX+", "MZ+"):
            game = self.game(module)
            char = game.state.characters["doctor"]
            game.state.phase = "refusal"
            game._request = {"source": "doctor", "effects": [], "unrefusable": False}
            game.roles["doctor"] = "killer"  # Optional refusal.
            self.assertEqual(len(game.options("m")), 2)
            char.hope = 1
            self.assertTrue(game.options("m")[0].get("accept"))
            self.assertEqual(len(game.options("m")), 1)
            char.despair = 1
            self.assertTrue(game.options("m")[0].get("refuse"))
            game._request["unrefusable"] = True
            self.assertTrue(game.options("m")[0].get("accept"))
            char.despair = 0
            game._request["unrefusable"] = False
            game.roles["doctor"] = "clown"  # Mandatory refusal survives hope.
            self.assertTrue(game.options("m")[0].get("refuse"))

    def test_once_goodwill_refusal_releases_usage_records(self):
        for module in ("BTX+", "MZ+"):
            game = self.game(module)
            key = "goodwill:doctor:test"
            game.state.phase = "refusal"
            game.state.characters["doctor"].despair = 1
            game._request = {"source": "doctor", "effects": [], "unrefusable": False,
                             "key": key, "once": True}
            for used in (game.day_used, game.loop_used, game.public_day_used, game.public_loop_used):
                used.add(key)
            game.dispatch("m", "choose", index=1)
            for used in (game.day_used, game.loop_used, game.public_day_used, game.public_loop_used):
                self.assertNotIn(key, used)
            self.assertTrue(any(event["kind"] == "goodwill_refused" for event in game.state.events))

    def test_hope_incident_uses_goodwill_and_leader_target(self):
        for module in ("BTX+", "MZ+"):
            game = self.game(module)
            game.state.round = 2
            game.state.phase = "incident"
            game.state.characters["doctor"].hope = 2  # Doctor's threshold is two.
            game._incident()
            self.assertTrue(game.incident_records[-1]["happened"])
            self.assertEqual(game.controller, game.state.leader)
            game.dispatch(game.controller, "choose", index=1)
            self.assertEqual(game.state.characters["student"].hope, 1)
            self.assertTrue(game.incident_records[-1]["effective"])

    def test_hope_incident_does_not_use_paranoia(self):
        for module in ("BTX+", "MZ+"):
            game = self.game(module)
            game.state.round = 2
            game.state.phase = "incident"
            game.state.characters["doctor"].paranoia = 10
            game._incident()
            self.assertFalse(game.incident_records[-1]["happened"])

    def test_despair_incident_uses_paranoia_and_mastermind_target(self):
        for module in ("BTX+", "MZ+"):
            game = self.game(module)
            game.state.round = 3
            game.state.phase = "incident"
            game.state.characters["patient"].despair = 3
            game._incident()
            self.assertTrue(game.incident_records[-1]["happened"])
            self.assertEqual(game.controller, "m")
            game.dispatch("m", "choose", index=1)
            self.assertEqual(game.state.characters["student"].despair, 1)

    def test_mz_copy_can_copy_both_added_incidents(self):
        game = self.game("MZ+")
        for kind in ("hope_light", "despair_dark"):
            effects = game._mz_incident_effects(kind, "doctor")
            self.assertEqual(effects[0]["actor"], "a" if kind == "hope_light" else "m")
            self.assertTrue(effects[0]["options"])

    def test_mz_ninja_magician_and_end_loss_keep_effective_thresholds(self):
        data = example_scenario("MZ+")
        data.update(main_plot="mz_battle", subplots=["mz_clear_mind", "anniversary_beyond_worldline"],
                    cast={"student": "fragment", "girl": "ordinary", "doctor": "magician",
                          "worker": "ninja", "maiden": "conspiracy", "patient": "ordinary"})
        game = Game(data)
        doctor = game.state.characters["doctor"]
        doctor.hope = 1
        game.state.phase = "master_abilities"
        self.assertTrue(any(item.get("key") == "role:magician" for item in game.options("m")))
        girl = game.state.characters["girl"]
        girl.location = game.state.characters["worker"].location
        girl.intrigue, girl.hope = 2, 1
        game.state.phase = "day_end"
        game._night_forced_done = True
        self.assertFalse(any(item.get("key") == "ninja:worker" and
                             item["effects"][0].get("target") == "girl" for item in game.options("m")))
        girl.despair = 1
        self.assertTrue(any(item.get("key") == "ninja:worker" and
                            item["effects"][0].get("target") == "girl" for item in game.options("m")))
        worker = game.state.characters["worker"]
        worker.intrigue, worker.hope = 2, 1
        safe = game.clone()
        safe._resolve_loop_end()
        self.assertEqual(safe.winner, "protagonists")
        worker.despair = 1
        game._resolve_loop_end()
        self.assertEqual(game.state.phase, "loop_end")

    def test_mz_ninja_can_claim_the_additional_fragment_role(self):
        game = self.game("MZ+")
        game.roles["doctor"] = "ninja"
        game._reveal_role("doctor")
        offered = game._queue[0]["options"]
        self.assertTrue(any(item["effects"][0]["role"] == "fragment" for item in offered))
        self.assertIn("fragment", game._script_roles())

    def test_final_guess_accepts_civilian_only_for_actual_fragment(self):
        for module in ("BTX+", "MZ+"):
            for guessed_role in ("ordinary", "fragment"):
                game = self.game(module)
                game._start_final_guess()
                guesses = dict(game.scenario["cast"])
                guesses["student"] = guessed_role
                game.dispatch(game.controller, "guess_all", guesses=guesses)
                self.assertEqual(game.winner, "protagonists")
                result = next(e for e in game.state.events if e["kind"] == "final_guess_result")
                self.assertEqual(result["correct"], len(guesses))
                self.assertEqual(result["guesses"][0]["guessed_role"], guessed_role)
            game = self.game(module)
            game._start_final_guess()
            guesses = dict(game.scenario["cast"])
            guesses["patient"] = "fragment"
            game.dispatch(game.controller, "guess_all", guesses=guesses)
            self.assertEqual(game.winner, "mastermind")

    def test_catalog_and_three_languages(self):
        service = GameService()
        for module in ("BTX+", "MZ+"):
            for language in ("zh", "en", "ja"):
                catalog = service.get_catalog(module, language)
                self.assertIn("fragment", {item["id"] for item in catalog["roles"]})
                self.assertIn("anniversary_beyond_worldline", {item["id"] for item in catalog["plots"]})
                self.assertIn("hope_light", {item["id"] for item in catalog["incidents"]})
                self.assertIn("ahr_h1", {item["id"] for item in catalog["cards"]["a"]})
                self.assertNotEqual(label("modules", module, language), module)
        self.assertEqual(label("roles", "fragment"), "因果残片")

    def test_lan_room_can_select_each_expansion(self):
        for module in ("BTX+", "MZ+"):
            rooms = RoomService()
            created = rooms.create({"module": module, "nickname": "扩展测试", "seat": "m", "protagonist_count": 1})
            self.assertEqual(created["room"]["module"], module)
            self.assertEqual(created["room"]["protagonist_count"], 1)

    def test_hotseat_public_reference_and_details_include_the_expansion(self):
        for module in ("BTX+", "MZ+"):
            self.assertIn("fragment", module_roles(module))
            self.assertIn("因果残片", public_rules(module))
            game = self.game(module)
            game.state.characters["student"].hope = 2
            self.assertIn("后的判定：友好 2", character_details(game.view(), "student"))
            game.state.discarded["a"].append("ahr_h1")
            self.assertIn("希望 +1", public_knowledge(game.view()))
            if module == "MZ+":
                self.assertIn("公开宣称", public_knowledge(game.view()))

    def test_json_service_complete_match_snapshot_and_final_guess_menu(self):
        service = GameService()
        created = service.create_game({"module": "BTX+"})
        session, admin = created["session_id"], created["credentials"]["admin"]
        rng = random.Random(42)
        for _ in range(900):
            view = service.get_view(session)["state"]
            self.assertNotIn("secret", view)
            self.assertEqual(view["module"], "BTX+")
            self.assertIn("effective_counters", view["characters"]["student"])
            if view["winner"]:
                break
            actor = view["controller"]
            offers = service.get_actions(session, actor, token=admin)
            choices = [offer for offer in offers["actions"] if offer["type"] != "final"]
            selected = rng.choice(choices or offers["actions"])
            request = {"action_id": selected["id"], "expected_revision": offers["revision"]}
            if selected["type"] == "guess_all":
                self.assertIn("fragment", selected["parameters"]["roles"])
                guesses = dict(example_scenario("BTX+")["cast"])
                guesses["student"] = "ordinary"
                request["arguments"] = {"guesses": guesses}
            service.dispatch(session, request, token=admin)
        self.assertIsNotNone(view["winner"])
        replay = ReplayArchive.parse(service.get_replay(session, token=admin)).verify()
        self.assertEqual(json.loads(json.dumps(replay.view())), view)

    def test_loop_cards_and_their_plays_are_in_deterministic_text_replay(self):
        data = example_scenario("BTX+")
        data.update(days=1, incidents=[])
        game = Game(data)
        for _ in range(500):
            if game.winner:
                break
            actor, phase = game.controller, game.state.phase
            if phase == "mastermind":
                ordinal = sum(p.actor == "m" for p in game.state.pending)
                card, target = [("i2", "girl"), ("p1a", "student"),
                                ("ahr_d1" if "ahr_d1" in game.state.hands["m"] else "p1b", "doctor")][ordinal]
                game.dispatch(actor, "play", card=card, target=target)
            elif phase == "protagonists":
                ordinal = sum(p.actor != "m" for p in game.state.pending)
                card = "h" if ordinal == 2 else "ahr_h1" if "ahr_h1" in game.state.hands[actor] else "g2"
                game.dispatch(actor, "play", card=card, target=["student", "maiden", "girl"][ordinal])
            elif phase == "final_guess":
                guesses = dict(game.scenario["cast"])
                guesses["student"] = "ordinary"
                game.dispatch(actor, "guess_all", guesses=guesses)
            else:
                legal = game.legal_actions(actor)
                attacks = [index for index, item in enumerate(game.options(actor), 1)
                           if item.get("key") == "killer:character:worker"]
                if attacks:
                    game.dispatch(actor, "choose", index=attacks[0])
                else:
                    command = next((c for c in legal if c["action"] not in ("choose", "final")), legal[-1])
                    command = dict(command)
                    game.dispatch(command.pop("actor"), command.pop("action"), **command)
        self.assertEqual(game.winner, "protagonists")
        grants = [e for e in game.state.events if e["kind"] == "special_card_gained"]
        self.assertTrue(any(e.get("card") == "ahr_d1" for e in grants))
        self.assertTrue(any(e.get("card") == "ahr_h1" for e in grants))
        self.assertTrue(any(c.get("card") == "ahr_d1" for c in game.history))
        self.assertTrue(any(c.get("card") == "ahr_h1" for c in game.history))
        text = dumps(game)
        self.assertIn("轮回开始时", text)
        self.assertIn("希望 +1", public_log(game.view()))
        self.assertEqual(ReplayArchive.parse(text).verify().view("m"), game.view("m"))

    def test_legal_playouts_clones_and_text_replay(self):
        for module in ("BTX+", "MZ+"):
            for seed in (7, 18, 103):
                with self.subTest(module=module, seed=seed):
                    rng = random.Random(seed)
                    game = self.game(module)
                    for _ in range(900):
                        if game.winner:
                            break
                        legal = game.legal_actions(game.controller)
                        if game.state.phase == "final_guess":
                            command = {"actor": game.controller, "action": "guess_all", "guesses": dict(game.scenario["cast"])}
                        else:
                            nonfinal = [c for c in legal if c["action"] != "final"]
                            command = dict(rng.choice(nonfinal or legal))
                        game.dispatch(command.pop("actor"), command.pop("action"), **command)
                    self.assertIsNotNone(game.winner)
                    replay = ReplayArchive.parse(dumps(game)).verify()
                    self.assertEqual(replay.view("m"), game.view("m"))
                    self.assertEqual(deepcopy(game).view("m"), game.view("m"))
                    self.assertEqual(game.clone().state_key(), game.state_key())


if __name__ == "__main__":
    unittest.main()
