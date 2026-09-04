"""Mystery Circle X content and CLI-engine regression tests."""

from collections import Counter
from itertools import combinations
import json
from pathlib import Path
import unittest

from tragedy_sim import Game, RuleError
from tragedy_sim.catalog import CHARACTERS, MODULES, PLOTS
from tragedy_sim.scenario import example_scenario, validate_scenario


def scenario(main="murder_plan", subplots=None, *, holders=None, incidents=None, days=3, loops=2,
             include_henchman=False):
    subplots = list(subplots or ("mc_isolation", "mc_gunpowder"))
    needed = Counter()
    for plot in (main, *subplots):
        needed.update(PLOTS[plot][2])
    for role, cap in MODULES["MC"].role_caps.items():
        needed[role] = min(needed[role], cap)
    cast = dict.fromkeys((cid for cid in MODULES["MC"].characters
                          if include_henchman or cid != "henchman"), "ordinary")
    holders = dict(holders or {})
    cast.update(holders)
    assigned = Counter(holders.values())
    free = [cid for cid in cast if cid not in holders]
    for role in sorted(needed):
        for _ in range(needed[role] - assigned[role]):
            cast[free.pop(0)] = role
    return {"id": "mc-test", "title": "MC 规则测试", "module": "MC", "days": days,
            "loops": loops, "main_plot": main, "subplots": subplots, "cast": cast,
            "incidents": list(incidents or ()), "table_talk": False}


def choose(game, predicate):
    choices = game.options(game.controller)
    index = next((i for i, item in enumerate(choices, 1) if predicate(item)), None)
    if index is None:
        raise AssertionError(f"missing option in {game.state.phase}: {choices}")
    game.dispatch(game.controller, "choose", index=index)


def run_incident(game, *, paranoia=None):
    game.state.phase = "incident"
    culprit = game.scenario["incidents"][0]["culprit"]
    if paranoia is not None:
        game.state.characters[culprit].paranoia = paranoia
    game.dispatch("m", "next")


class MysteryCircleTests(unittest.TestCase):
    def test_catalog_example_and_script_constraints(self):
        self.assertTrue(MODULES["MC"].gui_supported)
        self.assertEqual(validate_scenario(example_scenario("MC")), example_scenario("MC"))
        self.assertEqual(validate_scenario(json.loads(
            Path("examples/mc-tutorial.json").read_text(encoding="utf-8"))),
            example_scenario("MC"))

        detective = scenario(subplots=["mc_detective", "mc_gunpowder"],
                             holders={"student": "detective"},
                             incidents=[{"day": 1, "kind": "suicide", "culprit": "student"}])
        with self.assertRaisesRegex(RuleError, "侦探不能"):
            validate_scenario(detective)

        fool = scenario("mc_event_web", incidents=[])
        with self.assertRaisesRegex(RuleError, "愚者"):
            validate_scenario(fool)

    def test_all_printed_plot_combinations_validate(self):
        y_plots = [plot for plot in MODULES["MC"].plots if PLOTS[plot][1] == "Y"]
        x_plots = [plot for plot in MODULES["MC"].plots if PLOTS[plot][1] == "X"]
        count = 0
        for main in y_plots:
            for subplots in combinations(x_plots, 2):
                data = scenario(main, subplots)
                culprits = [cid for cid, role in data["cast"].items()
                            if role in ("fool", "obsessive", "twin")]
                data["incidents"] = [
                    {"day": day, "kind": "serial_murder", "culprit": culprit}
                    for day, culprit in enumerate(culprits, 1)
                ]
                validate_scenario(data)
                count += 1
        self.assertEqual(count, 105)

    def test_ex_gauge_and_special_increment_events(self):
        ordinary = Game(scenario(incidents=[{"day": 1, "kind": "suicide", "culprit": "doctor"}]))
        run_incident(ordinary, paranoia=CHARACTERS["doctor"].limit)
        self.assertEqual(ordinary.ex_gauge, 1)

        bizarre = Game(scenario(incidents=[{"day": 1, "kind": "bizarre_murder", "culprit": "doctor"}]))
        run_incident(bizarre, paranoia=CHARACTERS["doctor"].limit + 1)
        self.assertEqual(bizarre.ex_gauge, 2)

        bullet = Game(scenario(incidents=[{"day": 1, "kind": "silver_bullet", "culprit": "doctor"}]))
        run_incident(bullet, paranoia=CHARACTERS["doctor"].limit)
        self.assertEqual(bullet.ex_gauge, 0)
        self.assertTrue(bullet.incident_records[0]["effective"])
        self.assertIn(bullet.state.phase, ("loop_end", "final_guess"))

        fake = Game(scenario(incidents=[{"day": 1, "kind": "fake_suicide", "culprit": "doctor"}]))
        run_incident(fake, paranoia=CHARACTERS["doctor"].limit)
        self.assertEqual(fake.ex_cards["doctor"], 1)
        self.assertFalse(fake._can_target_action("a", "doctor"))
        self.assertTrue(fake._can_target_action("m", "doctor"))

    def test_area_incidents_and_unease(self):
        terror = Game(scenario(incidents=[
            {"day": 1, "kind": "terror_attack", "culprit": "doctor"}]))
        terror.state.locations["city"] = 1
        run_incident(terror, paranoia=CHARACTERS["doctor"].limit)
        self.assertFalse(terror.state.characters["worker"].alive)

        hospital = Game(scenario(incidents=[
            {"day": 1, "kind": "hospital", "culprit": "doctor"}]))
        hospital.state.locations["hospital"] = 1
        run_incident(hospital, paranoia=CHARACTERS["doctor"].limit)
        self.assertFalse(hospital.state.characters["doctor"].alive)

        unease = Game(scenario(incidents=[{"day": 1, "kind": "unease", "culprit": "doctor"}]))
        run_incident(unease, paranoia=CHARACTERS["doctor"].limit)
        choose(unease, lambda item: any(e.get("target") == "student" for e in item["effects"]))
        choose(unease, lambda item: any(e.get("target") == "girl" for e in item["effects"]))
        self.assertEqual(unease.state.characters["student"].paranoia, 2)
        self.assertEqual(unease.state.characters["girl"].intrigue, 1)

    def test_detective_forces_event_and_fool_clears_after_resolution(self):
        data = scenario("mc_event_web", ["mc_detective", "mc_gunpowder"],
                        holders={"student": "detective", "girl": "fool"},
                        incidents=[{"day": 1, "kind": "omen", "culprit": "girl"}])
        game = Game(data)
        run_incident(game, paranoia=0)
        self.assertTrue(game.incident_records[0]["happened"])
        choose(game, lambda item: any(e.get("target") == "girl" for e in item["effects"]))
        self.assertEqual(game.state.characters["girl"].paranoia, 0)
        self.assertEqual(game.ex_gauge, 1)

    def test_strychnine_counts_intrigue_as_paranoia(self):
        data = scenario("mc_strychnine", ["mc_gunpowder", "mc_isolation"],
                        holders={"doctor": "fool"},
                        incidents=[{"day": 1, "kind": "suicide", "culprit": "doctor"}])
        game = Game(data)
        game.state.characters["doctor"].intrigue = CHARACTERS["doctor"].limit
        run_incident(game, paranoia=0)
        self.assertTrue(game.incident_records[0]["happened"])

    def test_twin_resolves_from_diagonal_board(self):
        data = scenario("mc_tightrope", ["mc_twins", "mc_gunpowder"],
                        holders={"student": "twin"},
                        incidents=[{"day": 1, "kind": "serial_murder", "culprit": "student"}])
        game = Game(data)
        run_incident(game, paranoia=CHARACTERS["student"].limit)
        labels = [item["label"] for item in game.options("m")]
        self.assertTrue(any("医生" in label or "住院患者" in label or "护士" in label for label in labels))
        self.assertFalse(any("女学生" in label for label in labels))

    def test_psychiatrist_is_mandatory_and_can_target_zero_paranoia(self):
        data = scenario(holders={"doctor": "psychiatrist", "patient": "paranoid"})
        game = Game(data)
        game.ex_gauge = 1
        game.state.phase = "master_abilities"
        game._start_master_abilities_forced()
        self.assertEqual(game.state.phase, "decision")
        self.assertTrue(any("住院患者" in item["label"] for item in game.options("m")))

    def test_poisoner_activates_in_mandatory_batch(self):
        data = scenario("mc_strychnine", ["mc_isolation", "mc_gunpowder"],
                        holders={"doctor": "poisoner", "student": "fool"},
                        incidents=[{"day": 1, "kind": "omen", "culprit": "student"}])
        game = Game(data)
        game.ex_gauge = 2
        game.state.phase = "day_end"
        game._start_day_end_forced()
        self.assertEqual(game.state.phase, "decision")
        choose(game, lambda item: "投毒者" in item["label"] and "住院患者" in item["label"])
        self.assertFalse(game.state.characters["patient"].alive)
        self.assertIn("mandatory:poisoner:doctor", game.loop_used)

        lethal = Game(data)
        lethal.ex_gauge = 4
        lethal.state.phase = "day_end"
        lethal._start_day_end_forced()
        choose(lethal, lambda item: "投毒者" in item["label"])
        self.assertIn(lethal.state.phase, ("loop_end", "final_guess"))
        self.assertIn("投毒者使主人公死亡", lethal.loss_reasons)

    def test_poisoner_may_accept_or_refuse_goodwill(self):
        data = scenario("mc_strychnine", ["mc_isolation", "mc_gunpowder"],
                        holders={"doctor": "poisoner", "student": "fool"},
                        incidents=[{"day": 1, "kind": "omen", "culprit": "student"}])
        game = Game(data)
        game.state.characters["doctor"].goodwill = 2
        game.state.phase = "goodwill"
        choose(game, lambda item: item.get("source") == "doctor")
        choices = game.options("m")
        self.assertTrue(any(item.get("accept") for item in choices))
        self.assertTrue(any(item.get("refuse") for item in choices))

    def test_all_mc_loop_end_loss_rules(self):
        fixtures = []
        web_data = scenario("mc_event_web")
        fool = next(cid for cid, role in web_data["cast"].items() if role == "fool")
        web_data["incidents"] = [{"day": 1, "kind": "omen", "culprit": fool}]
        web = Game(web_data)
        web.ex_gauge = 3
        fixtures.append(web)

        tightrope = Game(scenario("mc_tightrope"))
        tightrope.ex_gauge = 1
        fixtures.append(tightrope)

        fixtures.append(Game(scenario("mc_dark_school")))

        gunpowder = Game(scenario())
        gunpowder.state.characters["student"].intrigue = 12
        fixtures.append(gunpowder)

        for game in fixtures:
            with self.subTest(main=game.scenario["main_plot"], subplots=game.scenario["subplots"]):
                game._finish_loop()
                self.assertEqual(game.state.phase, "loop_end")

    def test_isolation_carries_only_the_previous_ex_threshold(self):
        game = Game(scenario())
        game.ex_gauge = 2
        game._finish_loop(forced=True)
        self.assertEqual(game.state.phase, "loop_end")
        game.dispatch(game.controller, "next")
        self.assertEqual(game.ex_gauge, 1)

    def test_suspicious_letter_and_lockdown_publish_movement_restrictions(self):
        letter = Game(scenario(incidents=[
            {"day": 1, "kind": "suspicious_letter", "culprit": "doctor"}]))
        run_incident(letter, paranoia=CHARACTERS["doctor"].limit)
        choose(letter, lambda item: "护士" in item["label"] and "学校" in item["label"])
        self.assertEqual(letter.state.characters["nurse"].location, "school")
        self.assertEqual(letter.view()["movement_locks"]["nurse"], 2)

        sealed = Game(scenario(incidents=[{"day": 1, "kind": "lockdown", "culprit": "doctor"}]))
        run_incident(sealed, paranoia=CHARACTERS["doctor"].limit)
        self.assertEqual(sealed.view()["sealed_boards"], [{"board": "hospital", "through": 3}])
        self.assertFalse(sealed._movement_destination_allowed("student", "hospital"))

    def test_henchman_loop_placement_and_incident_prevention(self):
        data = scenario(include_henchman=True, incidents=[
            {"day": 1, "kind": "suicide", "culprit": "henchman"}])
        game = Game(data)
        self.assertEqual(game.state.phase, "decision")
        choose(game, lambda item: "都市" in item["label"])
        self.assertEqual(game.state.characters["henchman"].location, "city")
        self.assertEqual(game.view()["characters"]["henchman"]["initial_location"], "city")
        replay = Game(data)
        for command in game.history:
            command = dict(command)
            replay.dispatch(command.pop("actor"), command.pop("action"), **command)
        self.assertEqual(game.state_key("m"), replay.state_key("m"))

        game.state.characters["henchman"].goodwill = 3
        game.state.phase = "goodwill"
        choose(game, lambda item: item.get("source") == "henchman")
        choose(game, lambda item: item.get("accept"))
        game.state.characters["henchman"].paranoia = 1
        game.state.phase = "incident"
        game.dispatch("m", "next")
        self.assertFalse(game.incident_records[0]["happened"])


if __name__ == "__main__":
    unittest.main()
