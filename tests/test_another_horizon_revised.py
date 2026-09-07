"""Another Horizon Revised world, identity, role and incident tests."""

from collections import Counter
from itertools import combinations
import json
from pathlib import Path
import unittest

from tragedy_sim import Game, RuleError
from tragedy_sim.catalog import CHARACTERS, MODULES, PLOTS
from tragedy_sim.scenario import example_scenario, validate_scenario


Y_PLOTS = tuple(p for p in MODULES["AHR"].plots if PLOTS[p][1] == "Y")
X_PLOTS = tuple(p for p in MODULES["AHR"].plots if PLOTS[p][1] == "X")


def scenario(main="ahr_closed_future", subplots=None, *, holders=None, hidden=None,
             incidents=None, days=3, loops=2):
    subplots = list(subplots or ("ahr_puppet_lines", "ahr_beyond_worldline"))
    needed = Counter()
    for plot in (main, *subplots):
        needed.update(PLOTS[plot][2])
    for role, cap in MODULES["AHR"].role_caps.items():
        needed[role] = min(needed[role], cap)
    cast = dict.fromkeys(MODULES["AHR"].characters, "ordinary")
    holders = dict(holders or {})
    cast.update(holders)
    assigned = Counter(holders.values())
    free = [cid for cid in cast if cid not in holders]
    for role in sorted(needed):
        for _ in range(needed[role] - assigned[role]):
            cast[free.pop(0)] = role
    obsessive = next((cid for cid, role in cast.items() if role == "obsessive"), None)
    incidents = list(incidents or ())
    if obsessive and not incidents:
        incidents = [{"day": 1, "kind": "dimension_swap", "culprit": obsessive}]
    return {"id": "ahr-test", "title": "AHR 规则测试", "module": "AHR", "days": days,
            "loops": loops, "main_plot": main, "subplots": subplots, "cast": cast,
            "hidden_cast": dict(hidden or cast), "incidents": incidents, "table_talk": False}


def choose(game, predicate):
    options = game.options(game.controller)
    index = next((i for i, item in enumerate(options, 1) if predicate(item)), None)
    if index is None:
        raise AssertionError(f"missing option in {game.state.phase}: {options}")
    game.dispatch(game.controller, "choose", index=index)


def run_incident(game, index=0, score=None):
    incident = game.scenario["incidents"][index]
    game.state.round = incident["day"]
    game.state.phase = "incident"
    culprit = game.state.characters[incident["culprit"]]
    if score is None:
        score = CHARACTERS[culprit.id].limit
    if incident["kind"] == "imaginary_incident":
        culprit.intrigue = score
    elif game.ex_gauge % 2 or incident["kind"] == "hope_light":
        culprit.goodwill = score
    else:
        culprit.paranoia = score
    game.dispatch("m", "next")


class AnotherHorizonRevisedTests(unittest.TestCase):
    def test_catalog_example_and_all_105_plot_combinations(self):
        self.assertEqual(len(Y_PLOTS), 5)
        self.assertEqual(len(X_PLOTS), 7)
        self.assertEqual(validate_scenario(example_scenario("AHR")), example_scenario("AHR"))
        self.assertEqual(validate_scenario(json.loads(
            Path("examples/ahr-tutorial.json").read_text(encoding="utf-8"))),
            example_scenario("AHR"))
        count = 0
        for main in Y_PLOTS:
            for subplots in combinations(X_PLOTS, 2):
                validate_scenario(scenario(main, subplots))
                count += 1
        self.assertEqual(count, 105)

    def test_hidden_cast_is_scoped_to_ahr(self):
        data = scenario()
        data["hidden_cast"] = {"student": "ordinary"}
        with self.assertRaisesRegex(RuleError, "hidden_cast"):
            validate_scenario(data)
        foreign = example_scenario("BTX")
        foreign["hidden_cast"] = dict(foreign["cast"])
        with self.assertRaisesRegex(RuleError, "只有 AHR"):
            validate_scenario(foreign)

    def test_special_hands_and_world_shift_at_start_of_day_end(self):
        game = Game(scenario("ahr_legendary_killer", incidents=[
            {"day": 1, "kind": "dimension_swap", "culprit": "doctor"}]))
        self.assertIn("ahr_g1", game.state.hands["m"])
        self.assertIn("ahr_d1", game.state.hands["m"])
        self.assertIn("ahr_p2", game.state.hands["a"])
        self.assertNotIn("ahr_h1", game.state.hands["a"])
        run_incident(game)
        self.assertEqual(game.ex_gauge, 1)
        self.assertEqual(game.roles, game.scenario["hidden_cast"])

    def test_hidden_world_swaps_incident_and_goodwill_requirements(self):
        game = Game(scenario("ahr_legendary_killer", incidents=[
            {"day": 1, "kind": "despair_dark", "culprit": "doctor"}]))
        game._change_ex_gauge(1)
        game.state.characters["doctor"].paranoia = 0
        run_incident(game)
        self.assertTrue(game.incident_records[0]["happened"])
        choose(game, lambda item: "男学生" in item["label"])

        game.state.characters["doctor"].goodwill = 0
        game.state.characters["doctor"].paranoia = 2
        game.state.phase = "goodwill"
        self.assertTrue(any(item.get("source") == "doctor" for item in game.options(game.controller)))

    def test_despair_forces_refusal(self):
        game = Game(scenario())
        doctor = game.state.characters["doctor"]
        doctor.goodwill = 2
        doctor.despair = 1
        game.state.phase = "goodwill"
        choose(game, lambda item: item.get("source") == "doctor")
        self.assertTrue(all(not item.get("accept") for item in game.options("m")))

    def test_once_per_loop_goodwill_triggers_world(self):
        game = Game(scenario())
        game.state.characters["class_rep"].goodwill = 2
        game.state.discarded[game.state.leader].append("g2")
        game.state.phase = "goodwill"
        choose(game, lambda item: item.get("source") == "class_rep")
        choose(game, lambda item: item.get("accept"))
        choose(game, lambda item: True)
        self.assertTrue(game._ahr_world_shift_pending)

    def test_incidents_and_singularity_first_only(self):
        murder = Game(scenario("ahr_legendary_killer", incidents=[
            {"day": 1, "kind": "impulsive_murder", "culprit": "doctor"}]))
        run_incident(murder, score=CHARACTERS["doctor"].limit - 1)
        choose(murder, lambda item: "护士" in item["label"])
        self.assertFalse(murder.state.characters["nurse"].alive)

        singular = Game(scenario("ahr_legendary_killer", incidents=[
            {"day": 1, "kind": "singularity", "culprit": "doctor"}]))
        run_incident(singular)
        self.assertIn(singular.state.phase, ("loop_end", "final_guess"))
        self.assertTrue(singular._ahr_singularity_occurred)

    def test_alice_hidden_loss_and_dual_identity_final_guess(self):
        data = scenario(hidden={**scenario()["cast"], "student": "alice"})
        game = Game(data)
        game._change_ex_gauge(1)
        game._finish_loop()
        self.assertEqual(game.state.phase, "loop_end")
        game._start_final_guess()
        self.assertEqual(len(game._guess_remaining), 2 * len(game.roles))
        target = game._guess_remaining[0]
        cid, side = target.rsplit("@", 1)
        source = data["cast"] if side == "surface" else data["hidden_cast"]
        game.dispatch(game.controller, "guess", character=target, role=source[cid])
        self.assertNotEqual(game.state.phase, "game_over")


if __name__ == "__main__":
    unittest.main()
