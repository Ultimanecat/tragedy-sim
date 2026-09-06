"""Weird Mythology plots, Old Magic, roles and incidents."""

from collections import Counter
from itertools import combinations
import json
from pathlib import Path
import unittest

from tragedy_sim import Game, RuleError
from tragedy_sim.catalog import CHARACTERS, MODULES, PLOTS
from tragedy_sim.scenario import example_scenario, validate_scenario


Y_PLOTS = ("wm_outer_chorus", "wm_gospel", "wm_yellow_king", "wm_bomb", "wm_blood_ritual")
X_PLOTS = ("wm_rumor", "wm_resistance", "wm_witness_terror", "wm_great_race",
           "wm_deep_whisper", "wm_faceless_god", "wm_mad_truth")


def scenario(main="wm_gospel", subplots=None, *, holders=None, incidents=None, days=3, loops=2):
    subplots = list(subplots or ("wm_rumor", "wm_great_race"))
    needed = Counter()
    for plot in (main, *subplots):
        needed.update(PLOTS[plot][2])
    for role, cap in MODULES["WM"].role_caps.items():
        needed[role] = min(needed[role], cap)
    cast = dict.fromkeys(MODULES["WM"].characters, "ordinary")
    holders = dict(holders or {})
    cast.update(holders)
    assigned = Counter(holders.values())
    free = [cid for cid in cast if cid not in holders]
    for role in sorted(needed):
        for _ in range(needed[role] - assigned[role]):
            cast[free.pop(0)] = role
    incidents = list(incidents or ())
    sacrifice = next((cid for cid, role in cast.items() if role == "sacrifice"), None)
    if sacrifice and not incidents:
        incidents = [{"day": 1, "kind": "discovery", "culprit": sacrifice}]
    data = {"id": "wm-test", "title": "WM 规则测试", "module": "WM", "days": days,
            "loops": loops, "main_plot": main, "subplots": subplots, "cast": cast,
            "incidents": incidents, "table_talk": False}
    if "wm_mad_truth" in subplots:
        data["wm_replacement_plot"] = next(plot for plot in Y_PLOTS if plot != main)
    return data


def choose(game, predicate):
    options = game.options(game.controller)
    index = next((i for i, item in enumerate(options, 1) if predicate(item)), None)
    if index is None:
        raise AssertionError(f"missing option in {game.state.phase}: {options}")
    game.dispatch(game.controller, "choose", index=index)


def run_incident(game, index=0, *, score=None):
    incident = game.scenario["incidents"][index]
    game.state.round = incident["day"]
    game.state.phase = "incident"
    culprit = game.state.characters[incident["culprit"]]
    if score is None:
        score = CHARACTERS[culprit.id].limit
    if incident["kind"] == "dagon_whisper":
        culprit.intrigue = score
    else:
        culprit.paranoia = score
    game.dispatch("m", "next")


class WeirdMythologyTests(unittest.TestCase):
    def test_catalog_example_and_all_plot_combinations(self):
        self.assertEqual(MODULES["WM"].plots, (*Y_PLOTS, *X_PLOTS))
        self.assertTrue(MODULES["WM"].cli_supported)
        self.assertTrue(MODULES["WM"].gui_supported)
        self.assertEqual(validate_scenario(example_scenario("WM")), example_scenario("WM"))
        self.assertEqual(validate_scenario(json.loads(
            Path("examples/wm-tutorial.json").read_text(encoding="utf-8"))),
            example_scenario("WM"))
        count = 0
        for main in Y_PLOTS:
            for subplots in combinations(X_PLOTS, 2):
                validate_scenario(scenario(main, subplots))
                count += 1
        self.assertEqual(count, 105)

    def test_mad_truth_and_sacrifice_script_validation(self):
        mad = scenario(subplots=("wm_mad_truth", "wm_rumor"))
        del mad["wm_replacement_plot"]
        with self.assertRaisesRegex(RuleError, "wm_replacement_plot"):
            validate_scenario(mad)
        bad = scenario("wm_outer_chorus", incidents=[
            {"day": 1, "kind": "discovery", "culprit": "doctor"}])
        with self.assertRaisesRegex(RuleError, "第一起事件"):
            validate_scenario(bad)

    def test_ex_persists_and_sensory_spell_starts_next_loop(self):
        game = Game(scenario())
        game.ex_gauge = 1
        game._finish_loop(forced=True)
        game.dispatch(game.controller, "next")
        self.assertEqual(game.ex_gauge, 1)
        self.assertEqual(game.state.phase, "decision")
        self.assertIn("感应咒文", game._pending["prompt"])
        choose(game, lambda item: "男学生" in item["label"])
        self.assertEqual(game.state.characters["student"].goodwill, 2)

    def test_ex_three_keeps_multiple_forbid_intrigue_cards_active(self):
        game = Game(scenario())
        game.ex_gauge = 3
        game.state.phase = "mastermind"
        game.play("m", "i1", "doctor")
        game.play("m", "p1a", "student")
        game.play("m", "p1b", "girl")
        game.play("a", "fi", "doctor")
        game.play("b", "fi", "student")
        game.play("c", "g1", "girl")
        game.resolve()
        game.dispatch("m", "next")
        self.assertEqual(game.state.characters["doctor"].intrigue, 0)
        self.assertFalse(any(e["kind"] == "forbids_cancelled" for e in game.state.events))

    def test_conspiracy_death_reveals_role_and_increases_ex(self):
        game = Game(scenario("wm_bomb", holders={"doctor": "conspiracy"}))
        game._kill(["doctor"])
        self.assertFalse(game.state.characters["doctor"].alive)
        self.assertEqual(game.ex_gauge, 1)
        self.assertEqual(game.known_roles["doctor"]["role"], "conspiracy")

    def test_faceless_gains_roles_without_changing_identity(self):
        game = Game(scenario("wm_bomb", ("wm_faceless_god", "wm_rumor"),
                             holders={"doctor": "faceless"}))
        game.ex_gauge = 2
        self.assertTrue(game._has("doctor", "conspiracy"))
        self.assertTrue(game._has("doctor", "deep_one"))
        game._kill(["doctor"])
        self.assertTrue(game.state.characters["doctor"].alive)
        self.assertEqual(game.roles["doctor"], "faceless")

    def test_wizard_goodwill_reveals_then_leader_controls_ex(self):
        game = Game(scenario("wm_bomb", ("wm_resistance", "wm_great_race"),
                             holders={"doctor": "wizard"}))
        game.state.characters["doctor"].goodwill = 2
        game.state.phase = "goodwill"
        choose(game, lambda item: item.get("source") == "doctor")
        choose(game, lambda item: item.get("accept"))
        self.assertEqual(game.known_roles["doctor"]["role"], "wizard")
        choose(game, lambda item: "Ex 槽 +1" in item["label"])
        self.assertEqual(game.ex_gauge, 1)

    def test_refusing_goodwill_increases_ex(self):
        game = Game(scenario())
        cultist = next(cid for cid, role in game.roles.items() if role == "cultist")
        game.state.characters[cultist].goodwill = 2
        game.state.phase = "goodwill"
        choose(game, lambda item: item.get("source") == cultist)
        choose(game, lambda item: item.get("refuse"))
        self.assertEqual(game.ex_gauge, 1)

    def test_witness_is_a_mandatory_simultaneous_death(self):
        game = Game(scenario("wm_bomb", ("wm_witness_terror", "wm_great_race"),
                             holders={"doctor": "witness"}))
        game.state.characters["doctor"].paranoia = 4
        game.state.phase = "day_end"
        game._start_day_end_forced()
        self.assertFalse(game.state.characters["doctor"].alive)
        self.assertEqual(game.ex_gauge, 1)

    def test_sacrifice_uses_intrigue_for_incident_and_cannot_die(self):
        data = scenario("wm_outer_chorus", incidents=[
            {"day": 1, "kind": "discovery", "culprit": "student"}],
            holders={"student": "sacrifice"})
        game = Game(data)
        game.state.characters["student"].intrigue = CHARACTERS["student"].limit
        run_incident(game, score=0)
        self.assertTrue(game.incident_records[0]["happened"])
        game._kill(["student"])
        self.assertTrue(game.state.characters["student"].alive)

    def test_dagon_whisper_kills_after_a_later_different_event(self):
        game = Game(scenario(incidents=[
            {"day": 1, "kind": "dagon_whisper", "culprit": "doctor"},
            {"day": 2, "kind": "discovery", "culprit": "patient"}]))
        run_incident(game, 0)
        self.assertTrue(game._wm_dagon_active)
        self.assertNotEqual(game.state.phase, "loop_end")
        run_incident(game, 1)
        self.assertIn(game.state.phase, ("loop_end", "final_guess"))
        self.assertIn("主人公死亡", game.loss_reasons)

    def test_extinction_is_lethal_only_the_first_time_in_the_match(self):
        game = Game(scenario(incidents=[
            {"day": 1, "kind": "extinction", "culprit": "doctor"}]))
        run_incident(game)
        self.assertTrue(game._wm_extinction_occurred)
        self.assertEqual(game.state.phase, "loop_end")
        game.dispatch(game.controller, "next")
        if game.state.phase == "decision":
            choose(game, lambda item: True)
        run_incident(game)
        self.assertTrue(game.state.characters["girl"].alive)
        self.assertNotEqual(game.state.phase, "loop_end")
        self.assertTrue(any(e["kind"] == "extinction_repeated" for e in game.state.events))

    def test_main_plot_losses_and_mad_truth_replacement(self):
        outer = Game(scenario("wm_outer_chorus"))
        for character in outer._living()[:5]:
            character.intrigue = 1
        self.assertTrue(outer._wm_plot_loss("wm_outer_chorus"))
        yellow = Game(scenario("wm_yellow_king"))
        self.assertTrue(yellow._wm_plot_loss("wm_yellow_king"))
        mad = Game(scenario("wm_bomb", ("wm_mad_truth", "wm_rumor")))
        mad.ex_gauge = 2
        mad._finish_loop(forced=True)
        mad.dispatch(mad.controller, "next")
        choose(mad, lambda item: True)
        self.assertTrue(mad._wm_replacement_active)


if __name__ == "__main__":
    unittest.main()
