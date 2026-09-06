"""Haunted Stage Again catalog, curse, corpse, role and incident tests."""

from collections import Counter
from itertools import combinations
import json
from pathlib import Path
import unittest

from tragedy_sim import Game, RuleError
from tragedy_sim.catalog import CHARACTERS, MODULES, PLOTS
from tragedy_sim.scenario import example_scenario, validate_scenario


Y_SLOTS = {
    "hsa_noble": {"key": 1, "vampire": 1},
    "hsa_moon_beast": {"werewolf": 1},
    "hsa_fog_nightmare": {"nightmare": 1},
    "hsa_ancient_dead": {},
    "hsa_cursed_land": {"ghost": 1, "paper_tiger": 1},
}
X_SLOTS = {
    "hsa_panic_party": {"ghost": 1, "serial": 1, "lover": 1},
    "love_hsa": {"lover": 1, "loved": 1},
    "hsa_witch_curse": {"conspiracy": 1, "witch": 1},
    "hsa_girl_crisis": {"key": 1},
    "hsa_monster_plot": {"conspiracy": 1},
    "hsa_fear_delusion": {"serial": 1, "chicken": 1, "witch": 1},
    "hsa_unlistening": {"paper_tiger": 1, "conspiracy": 1, "chicken": 1},
}


def scenario(main="hsa_noble", subplots=None, *, holders=None, incidents=None, days=3, loops=2):
    subplots = list(subplots or ("love_hsa", "hsa_monster_plot"))
    needed = Counter()
    for plot in (main, *subplots):
        needed.update(PLOTS[plot][2])
    for role, cap in MODULES["HSA"].role_caps.items():
        needed[role] = min(needed[role], cap)
    cast = dict.fromkeys(MODULES["HSA"].characters, "ordinary")
    holders = dict(holders or {})
    if "hsa_girl_crisis" in subplots and "key" not in holders.values():
        holders["girl"] = "key"
        if needed["key"] > 1:
            holders["rich"] = "key"
    if main == "hsa_noble":
        if "key" not in holders.values():
            holders["girl"] = "key"
        if "vampire" not in holders.values():
            holders["doctor"] = "vampire"
    cast.update(holders)
    assigned = Counter(holders.values())
    free = [cid for cid in cast if cid not in holders]
    for role in sorted(needed):
        for _ in range(needed[role] - assigned[role]):
            cast[free.pop(0)] = role
    return {"id": "hsa-test", "title": "HSA 规则测试", "module": "HSA", "days": days,
            "loops": loops, "main_plot": main, "subplots": subplots, "cast": cast,
            "incidents": list(incidents or ()), "table_talk": False}


def choose(game, predicate, actor=None):
    actor = game.controller if actor is None else actor
    options = game.options(actor)
    index = next((i for i, item in enumerate(options, 1) if predicate(item)), None)
    if index is None:
        raise AssertionError(f"missing option in {game.state.phase}: {options}")
    game.dispatch(actor, "choose", index=index)


def run_incident(game, *, panic=True):
    game.state.phase = "incident"
    incident = game.scenario["incidents"][0]
    if panic and incident["culprit"] in game.state.characters:
        culprit = incident["culprit"]
        game.state.characters[culprit].paranoia = CHARACTERS[culprit].limit
    game.dispatch("m", "next")


class HauntedStageAgainTests(unittest.TestCase):
    def test_catalog_and_example(self):
        self.assertEqual(MODULES["HSA"].plots, tuple((*Y_SLOTS, *X_SLOTS)))
        for plot, slots in {**Y_SLOTS, **X_SLOTS}.items():
            self.assertEqual(PLOTS[plot][2], slots)
        self.assertEqual(validate_scenario(example_scenario("HSA")), example_scenario("HSA"))
        self.assertEqual(validate_scenario(json.loads(
            Path("examples/hsa-tutorial.json").read_text(encoding="utf-8"))),
            example_scenario("HSA"))
        self.assertTrue(MODULES["HSA"].cli_supported)
        self.assertTrue(MODULES["HSA"].gui_supported)

    def test_all_105_plot_combinations_validate(self):
        count = 0
        for main in Y_SLOTS:
            for subplots in combinations(X_SLOTS, 2):
                validate_scenario(scenario(main, subplots))
                count += 1
        self.assertEqual(count, 105)

    def test_gender_girl_and_group_incident_validation(self):
        invalid = scenario(holders={"student": "key", "doctor": "vampire"})
        with self.assertRaisesRegex(RuleError, "异性"):
            validate_scenario(invalid)
        girl = scenario("hsa_moon_beast", ["hsa_girl_crisis", "hsa_monster_plot"],
                        holders={"student": "key", "doctor": "werewolf"})
        with self.assertRaisesRegex(RuleError, "少女"):
            validate_scenario(girl)
        group = scenario(incidents=[{"day": 1, "kind": "frenzied_night", "culprit": "school"}])
        validate_scenario(group)
        group["incidents"][0]["culprit"] = "student"
        with self.assertRaisesRegex(RuleError, "版图"):
            validate_scenario(group)

    def test_werewolf_cannot_receive_mastermind_cards(self):
        game = Game(scenario("hsa_moon_beast", holders={"doctor": "werewolf"}))
        game.state.phase = "mastermind"
        self.assertFalse(game._can_target_action("m", "doctor"))
        with self.assertRaises(RuleError):
            game.dispatch("m", "play", card="p1a", target="doctor")

    def test_immortal_monsters_and_paper_tiger_refusal(self):
        vampire = Game(scenario(holders={"doctor": "vampire", "girl": "key"}))
        vampire._kill(["doctor"])
        self.assertTrue(vampire.state.characters["doctor"].alive)
        tiger = Game(scenario("hsa_cursed_land", holders={"doctor": "ghost", "patient": "paper_tiger"}))
        choose(tiger, lambda item: "不发动" in item["label"])
        tiger._kill(["patient"])
        self.assertTrue(tiger.state.characters["patient"].alive)

    def test_board_curse_attaches_then_kills_and_returns_to_board(self):
        game = Game(scenario())
        game.board_ex["school"] = 1
        game.state.phase = "day_end"
        game._start_day_end_forced()
        choose(game, lambda item: "男学生" in item["label"])
        self.assertEqual(game.ex_cards["student"], 1)
        self.assertEqual(game.board_ex["school"], 0)
        game._night_forced_done = False
        game._start_day_end_forced()
        choose(game, lambda item: "男学生身上" in item["label"])
        self.assertFalse(game.state.characters["student"].alive)
        self.assertEqual(game.ex_cards["student"], 0)
        self.assertEqual(game.board_ex["school"], 1)

    def test_ghost_and_chicken_are_forced_before_optional_abilities(self):
        game = Game(scenario("hsa_cursed_land", ["hsa_fear_delusion", "hsa_monster_plot"],
                             holders={"doctor": "ghost", "student": "chicken",
                                      "girl": "paper_tiger", "maiden": "serial",
                                      "patient": "witch", "worker": "conspiracy"}))
        choose(game, lambda item: "不发动" in item["label"])
        game.state.characters["doctor"].alive = False
        game.state.characters["student"].paranoia = 2
        game.state.phase = "master_abilities"
        game._start_master_abilities_forced()
        self.assertEqual(game.state.phase, "decision")
        self.assertTrue(any("鬼魂" in item["label"] for item in game.options("m")))
        choose(game, lambda item: "鬼魂" in item["label"])
        self.assertTrue(any("胆小鬼" in item["label"] for item in game.options("m")))

    def test_ancient_dead_turns_person_corpses_into_zombies(self):
        game = Game(scenario("hsa_ancient_dead", holders={}))
        ordinary = [cid for cid, role in game.roles.items() if role == "ordinary"][:2]
        for cid in ("patient", "nurse", "soldier"):
            game.state.characters[cid].location = "school"
        for cid in ordinary:
            game.state.characters[cid].location = "hospital"
        game._kill(ordinary)
        self.assertTrue(all(game.roles[cid] == "zombie" for cid in ordinary))
        game.state.phase = "day_end"
        game._start_day_end_forced()
        self.assertTrue(any("丧尸" in item["label"] for item in game.options("m")))
        choose(game, lambda item: "医生" in item["label"])
        self.assertFalse(game.state.characters["doctor"].alive)

    def test_group_incidents_use_corpses_and_publish_only_results(self):
        game = Game(scenario(incidents=[
            {"day": 1, "kind": "curse_awakening", "culprit": "school"}]))
        game.state.locations["school"] = 2
        run_incident(game, panic=False)
        self.assertTrue(game.incident_records[0]["happened"])
        self.assertEqual(game.board_ex["school"], 1)
        self.assertNotIn("culprit", game.incident_records[0])
        self.assertEqual(game.view()["schedule"][0]["board"], "school")

        apocalypse = Game(scenario(incidents=[
            {"day": 1, "kind": "dead_apocalypse", "culprit": "school"}]))
        apocalypse.state.locations["school"] = 3
        run_incident(apocalypse, panic=False)
        self.assertFalse(apocalypse.state.characters["student"].alive)
        self.assertIn(apocalypse.state.phase, ("loop_end", "final_guess"))

    def test_frenzied_murder_can_create_a_corpse_marker(self):
        game = Game(scenario(incidents=[
            {"day": 1, "kind": "frenzied_murder", "culprit": "doctor"}]))
        run_incident(game)
        choose(game, lambda item: "一具尸体" in item["label"])
        self.assertEqual(game.state.locations["hospital"], 1)


if __name__ == "__main__":
    unittest.main()
