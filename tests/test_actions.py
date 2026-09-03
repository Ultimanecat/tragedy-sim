from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

from tragedy_sim import ActionGame, Character, RuleError
from tragedy_sim.cards import ACTORS, COORDS, HERO_CARDS, MASTER_CARDS, deck


def place_all(game, master=None, heroes=None):
    for card, target in master or [("p1a", "doctor"), ("p1b", "student"), ("i1", "hospital")]:
        game.play("m", card, target)
    for actor, card, target in heroes or [("a", "g1", "doctor"), ("b", "g1", "student"), ("c", "fi", "hospital")]:
        game.play(actor, card, target)


class ActionTests(unittest.TestCase):
    def test_deck_contents(self):
        self.assertEqual(len(MASTER_CARDS), 10)
        self.assertEqual(len(HERO_CARDS), 8)
        self.assertEqual({c.id for c in MASTER_CARDS if c.once_per_loop}, {"d", "i2"})
        self.assertEqual({c.id for c in HERO_CARDS if c.once_per_loop}, {"p-1", "g2", "fm"})
        self.assertEqual(len({c.id for c in MASTER_CARDS}), 10)

    def test_decks_match_resource_index(self):
        path = Path(__file__).resolve().parents[1] / "resources" / "data.xml"
        if not path.exists():
            self.skipTest("用户资源未随代码分发")
        root = ET.parse(path).getroot()
        for stack_name, expected in [("剧作家手牌", 10), ("主人公A手牌", 8),
                                      ("主人公B手牌", 8), ("主人公C手牌", 8)]:
            stacks = [s for s in root.findall("card-stack")
                      if s.findtext("data/data[@name='common']/data[@name='name']") == stack_name]
            self.assertEqual(len(stacks), 1)
            self.assertEqual(len(stacks[0].find("node")), expected)

    def test_three_master_cards_then_each_hero_in_leader_order(self):
        game = ActionGame(leader="b")
        self.assertEqual(game.next_actor, "m")
        for card, target in [("p1a", "student"), ("p1b", "doctor"), ("i1", "school")]:
            game.play("m", card, target)
        for actor, target in [("b", "student"), ("c", "doctor"), ("a", "maiden")]:
            self.assertEqual(game.next_actor, actor)
            game.play(actor, "g1", target)
        self.assertIsNone(game.next_actor)
        self.assertEqual(game.state.phase, "reveal")
        self.assertEqual(game.state.characters["student"].paranoia, 0)
        game.resolve()
        self.assertEqual(game.state.phase, "resolved")

    def test_invalid_plays_do_not_change_state(self):
        game = ActionGame()
        game.play("m", "p1a", "student")
        before = asdict(game.state)
        for play in [("m", "p1b", "student"), ("m", "p1a", "doctor"), ("a", "g1", "doctor"),
                     ("m", "bad", "doctor"), ("m", "i1", "missing"), ("x", "g1", "doctor")]:
            with self.subTest(play=play), self.assertRaises(RuleError):
                game.play(*play)
            self.assertEqual(asdict(game.state), before)
        for action in (game.resolve, game.next_round, game.reset_loop):
            with self.assertRaises(RuleError):
                action()
            self.assertEqual(asdict(game.state), before)

    def test_protagonists_cannot_share_target_or_play_twice(self):
        game = ActionGame()
        for card, target in [("p1a", "student"), ("p1b", "doctor"), ("i1", "school")]:
            game.play("m", card, target)
        game.play("a", "g1", "student")
        before = asdict(game.state)
        for play in [("b", "g1", "student"), ("a", "g2", "doctor")]:
            with self.assertRaises(RuleError):
                game.play(*play)
            self.assertEqual(asdict(game.state), before)

    def test_only_own_facedown_cards_are_visible(self):
        game = ActionGame()
        place_all(game)
        for viewer in (*ACTORS, "spectator"):
            view = game.view(viewer)
            for p in view["pending"]:
                self.assertEqual(p["card"] is not None, p["actor"] == viewer)
            self.assertTrue(all("card" not in e and "cards" not in e for e in view["events"]))
        view = game.view("a")
        view["characters"]["student"]["goodwill"] = 999
        view["discarded"]["m"].append("i2")
        self.assertEqual(game.state.characters["student"].goodwill, 0)
        self.assertEqual(game.state.discarded["m"], [])
        game.resolve()
        revealed = next(e for e in game.view()["events"] if e["kind"] == "cards_revealed")
        self.assertEqual(len(revealed["cards"]), 6)

    def test_movement_table_all_start_locations(self):
        combinations = {("h", "h"): (1, 0), ("v", "v"): (0, 1), ("h", "v"): (1, 1),
                        ("v", "h"): (1, 1), ("d", "h"): (0, 1), ("d", "v"): (1, 0),
                        ("h", "g1"): (1, 0), ("v", "g1"): (0, 1), ("d", "g1"): (1, 1),
                        ("h", "fm"): (0, 0), ("v", "fm"): (0, 0), ("d", "fm"): (0, 0)}
        for origin, (x, y) in COORDS.items():
            for (master, hero), (dx, dy) in combinations.items():
                with self.subTest(origin=origin, cards=(master, hero)):
                    game = ActionGame([Character("test", "测试角色", origin)])
                    place_all(game, [(master, "test"), ("p1a", "hospital"), ("p1b", "shrine")],
                              [("a", hero, "test"), ("b", "g1", "hospital"), ("c", "g1", "shrine")])
                    game.resolve()
                    self.assertEqual(COORDS[game.state.characters["test"].location], (x ^ dx, y ^ dy))

    def test_forbidden_location_checks_final_combined_move(self):
        for master, hero, expected in [("h", "g1", "hospital"), ("h", "v", "school")]:
            game = ActionGame([Character("test", "测试角色", "hospital", ("shrine",))])
            place_all(game, [(master, "test"), ("p1a", "hospital"), ("p1b", "shrine")],
                      [("a", hero, "test"), ("b", "g1", "hospital"), ("c", "g1", "shrine")])
            game.resolve()
            self.assertEqual(game.state.characters["test"].location, expected)

    def test_single_forbid_intrigue_blocks_character_or_location(self):
        for target in ("student", "hospital"):
            game = ActionGame()
            place_all(game, [("i2", target), ("p1a", "maiden"), ("p1b", "doctor")],
                      [("a", "fi", target), ("b", "g1", "maiden"), ("c", "g1", "doctor")])
            game.resolve()
            self.assertEqual(game.state.characters["student"].intrigue, 0)
            self.assertEqual(game.state.locations["hospital"], 0)
            self.assertIn("i2", game.view()["discarded"]["m"])

    def test_two_or_three_forbid_intrigues_cancel_globally(self):
        for count in (2, 3):
            game = ActionGame()
            place_all(game, [("i2", "student"), ("i1", "hospital"), ("p1a", "doctor")],
                      [("a", "fi", "student"), ("b", "fi", "hospital"),
                       ("c", "fi" if count == 3 else "g1", "shrine")])
            game.resolve()
            self.assertEqual(game.state.characters["student"].intrigue, 2)
            self.assertEqual(game.state.locations["hospital"], 1)

    def test_other_forbids(self):
        for master, hero, counter in [("fp", "p1", "paranoia"), ("fp", "p-1", "paranoia"),
                                      ("fg", "g1", "goodwill"), ("fg", "g2", "goodwill")]:
            game = ActionGame([Character("test", "测试", "school", paranoia=1, goodwill=1)])
            place_all(game, [(master, "test"), ("i1", "hospital"), ("h", "city")],
                      [("a", hero, "test"), ("b", "g1", "hospital"), ("c", "g1", "city")])
            game.resolve()
            self.assertEqual(getattr(game.state.characters["test"], counter), 1)

    def test_paranoia_add_then_remove_and_floor_zero(self):
        for initial in (0, 2):
            for master, hero, delta in [("p1a", "p-1", 0), ("p-1", "p1", 0), ("p-1", "p-1", -2)]:
                game = ActionGame([Character("test", "测试", "school", paranoia=initial)])
                place_all(game, [(master, "test"), ("i1", "hospital"), ("h", "city")],
                          [("a", hero, "test"), ("b", "g1", "hospital"), ("c", "g1", "city")])
                game.resolve()
                self.assertEqual(game.state.characters["test"].paranoia, max(0, initial + delta))

    def test_any_card_can_bluff_on_location(self):
        for master in deck("m"):
            for hero in deck("a"):
                game = ActionGame([])
                others = [c for c in deck("m") if c != master][:2]
                place_all(game, [(master, "school"), (others[0], "hospital"), (others[1], "shrine")],
                          [("a", hero, "school"), ("b", "g1", "hospital"), ("c", "g1", "shrine")])
                game.resolve()
                expected = deck("m")[master].amount if master in ("i1", "i2") and hero != "fi" else 0
                self.assertEqual(game.state.locations["school"], expected)

    def test_movement_resolves_before_counters_and_counters_stay_with_target(self):
        game = ActionGame()
        place_all(game, [("i1", "doctor"), ("h", "student"), ("v", "maiden")],
                  [("a", "g1", "doctor"), ("b", "g1", "student"), ("c", "g1", "hospital")])
        game.resolve()
        kinds = [e["kind"] for e in game.state.events]
        self.assertLess(max(i for i, k in enumerate(kinds) if k == "character_moved"), kinds.index("counter_changed"))
        self.assertEqual(game.state.characters["student"].location, "city")
        self.assertEqual(game.state.characters["student"].goodwill, 1)

    def test_hands_return_on_resolve_and_limited_cards_are_independent(self):
        game = ActionGame()
        place_all(game, [("fg", "doctor"), ("d", "patient"), ("i2", "hospital")],
                  [("a", "g2", "doctor"), ("b", "fm", "patient"), ("c", "p-1", "city")])
        self.assertEqual(game.view()["discarded"]["a"], [])
        game.resolve()
        self.assertIn("fg", game.state.hands["m"])
        for actor, cards in {"m": ["d", "i2"], "a": ["g2"], "b": ["fm"], "c": ["p-1"]}.items():
            self.assertEqual(set(game.state.discarded[actor]), set(cards))
        self.assertIn("g2", game.state.hands["b"])
        game.next_round()
        self.assertEqual(game.state.leader, "b")
        self.assertNotIn("g2", game.state.hands["a"])
        place_all(game, heroes=[("b", "g1", "doctor"), ("c", "g1", "student"), ("a", "fi", "hospital")])
        game.resolve()
        game.reset_loop()
        self.assertEqual(game.state.loop, 2)
        self.assertEqual(game.state.round, 1)
        for actor in ACTORS:
            self.assertEqual(set(game.state.hands[actor]), set(deck(actor)))
        self.assertTrue(all(c.goodwill == c.paranoia == c.intrigue == 0 for c in game.state.characters.values()))

    def test_fs_btx_basic_actions_are_identical(self):
        states = []
        for module in ("FS", "BTX"):
            game = ActionGame(module=module)
            place_all(game)
            game.resolve()
            states.append(asdict(game.state))
        self.assertEqual(*states)

    def test_dead_characters_rejected_and_setup_is_copied(self):
        characters = [Character("test", "测试", "hospital", alive=False)]
        game = ActionGame(characters)
        characters[0].alive = True
        with self.assertRaises(RuleError):
            game.play("m", "i1", "test")
        self.assertFalse(game.state.characters["test"].alive)

    def test_invalid_setup(self):
        for chars in [[Character("school", "测试", "school")],
                      [Character("x", "测试", "missing")],
                      [Character("x", "测试", "school", ("school",))],
                      [Character("x", "测试", "school", paranoia=-1)]]:
            with self.assertRaises(RuleError):
                ActionGame(chars)


class CLITests(unittest.TestCase):
    def run_cli(self, *args, commands=""):
        return subprocess.run([sys.executable, "-m", "tragedy_sim", *args], input=commands,
                              capture_output=True, encoding="utf-8", timeout=10,
                              cwd=Path(__file__).resolve().parents[1])

    def test_demo_both_modules(self):
        for module in ("FS", "BTX"):
            result = self.run_cli("--demo", "--module", module)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("演示完成", result.stdout)
            self.assertNotIn("�", result.stdout)

    def test_interactive_errors_and_success(self):
        result = self.run_cli("--practice", commands="\n".join([
            "hand m", "resolve", "play m h student", "play m i2 hospital", "play m p1a doctor",
            "play a h student", "play b fi hospital", "play c g2 doctor", "view a", "resolve",
            "board", "next", "board", "nonsense", "quit", ""]))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("无法执行", result.stdout)
        self.assertIn("男学生 移动到都市", result.stdout)
        self.assertIn("第 2 次出牌", result.stdout)
        self.assertIn("领队 b", result.stdout)


if __name__ == "__main__":
    unittest.main()
