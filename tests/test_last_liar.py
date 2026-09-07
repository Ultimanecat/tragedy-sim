"""Last Liar secrets, betrayal, roles, incidents and final battle."""

from collections import Counter
from itertools import combinations
import json
from pathlib import Path
import unittest

from tragedy_sim import Game, RuleError
from tragedy_sim.catalog import CHARACTERS, MODULES, PLOTS
from tragedy_sim.scenario import example_scenario, validate_scenario


Y_PLOTS = tuple(p for p in MODULES["LL"].plots if PLOTS[p][1] == "Y")
X_PLOTS = tuple(p for p in MODULES["LL"].plots if PLOTS[p][1] == "X")


def scenario(main="ll_final_plan", subplots=None, *, holders=None, incidents=None,
             days=3, loops=2, order=("A", "B", "C")):
    subplots = list(subplots or ("ll_beyond_worldline", "ll_x_citizen"))
    needed = Counter()
    for plot in (main, *subplots):
        needed.update(PLOTS[plot][2])
    for role, cap in MODULES["LL"].role_caps.items():
        needed[role] = min(needed[role], cap)
    if "ll_fabricated_secret" in subplots and needed["secret_key"] == 0:
        extra = next(role for role in ("killer", "brain", "fragment") if needed[role] == 0)
        needed[extra] += 1
    cast = dict.fromkeys(MODULES["LL"].characters, "ordinary")
    holders = dict(holders or {})
    if main == "ll_treacherous_world":
        holders.setdefault("girl", "key")
        holders.setdefault("rich", "fragment")
    cast.update(holders)
    assigned = Counter(holders.values())
    free = [cid for cid in cast if cid not in holders]
    for role in sorted(needed):
        for _ in range(needed[role] - assigned[role]):
            cast[free.pop(0)] = role
    incidents = list(incidents or ())
    clown = next((cid for cid, role in cast.items() if role == "clown"), None)
    if clown and not incidents:
        incidents = [{"day": 1, "kind": "cocoon", "culprit": clown}]
    return {"id": "ll-test", "title": "LL 规则测试", "module": "LL", "days": days,
            "loops": loops, "main_plot": main, "subplots": subplots, "cast": cast,
            "incidents": incidents, "table_talk": False, "ll_secret_order": list(order)}


def choose(game, predicate):
    options = game.options(game.controller)
    index = next((i for i, item in enumerate(options, 1) if predicate(item)), None)
    if index is None:
        raise AssertionError(f"missing option in {game.state.phase}: {options}")
    game.dispatch(game.controller, "choose", index=index)


def run_incident(game, score=None):
    incident = game.scenario["incidents"][0]
    game.state.round = incident["day"]
    game.state.phase = "incident"
    culprit = game.state.characters[incident["culprit"]]
    if score is None:
        score = CHARACTERS[culprit.id].limit
    if incident["kind"] == "hope_light":
        culprit.goodwill = score
    else:
        culprit.paranoia = score
    game.dispatch("m", "next")


class LastLiarTests(unittest.TestCase):
    def test_catalog_example_and_all_105_plot_combinations(self):
        self.assertEqual((len(Y_PLOTS), len(X_PLOTS)), (5, 7))
        self.assertEqual(validate_scenario(example_scenario("LL")), example_scenario("LL"))
        self.assertEqual(validate_scenario(json.loads(
            Path("examples/ll-tutorial.json").read_text(encoding="utf-8"))),
            example_scenario("LL"))
        count = 0
        for main in Y_PLOTS:
            for subplots in combinations(X_PLOTS, 2):
                validate_scenario(scenario(main, subplots))
                count += 1
        self.assertEqual(count, 105)

    def test_secret_order_validation_and_visibility(self):
        bad = scenario()
        bad["ll_secret_order"] = ["A", "A", "C"]
        with self.assertRaisesRegex(RuleError, "A/B/C"):
            validate_scenario(bad)
        game = Game(scenario(order=("C", "A", "B")))
        self.assertNotIn("protagonist_secret", game.view())
        self.assertNotIn("protagonist_secret", game.view("m"))
        self.assertEqual(game.view("a")["protagonist_secret"], "C")
        self.assertEqual(game.view("b")["protagonist_secret"], "A")

    def test_clown_script_constraint_immunity_and_day_three_roles(self):
        data = scenario(subplots=("ll_true_monster", "ll_x_citizen"))
        clown = next(cid for cid, role in data["cast"].items() if role == "clown")
        data["incidents"] = []
        with self.assertRaisesRegex(RuleError, "小丑"):
            validate_scenario(data)
        game = Game(scenario(subplots=("ll_true_monster", "ll_x_citizen")))
        game._kill([clown])
        self.assertTrue(game.state.characters[clown].alive)
        game.state.round = 3
        self.assertTrue(game._has(clown, "killer"))
        self.assertTrue(game._has(clown, "brain"))

    def test_watcher_forces_incident_with_despair(self):
        data = scenario("ll_malicious_script", ("ll_x_citizen", "ll_beyond_worldline"),
                        holders={"doctor": "watcher", "patient": "internet_celeb"},
                        incidents=[{"day": 1, "kind": "cocoon", "culprit": "patient"}])
        game = Game(data)
        game.state.characters["doctor"].location = "hospital"
        game.state.characters["patient"].despair = 1
        run_incident(game, score=0)
        self.assertTrue(game.incident_records[0]["happened"])

    def test_internet_celeb_death_and_goodwill_reaction(self):
        game = Game(scenario("ll_malicious_script", holders={"doctor": "internet_celeb",
                                                               "patient": "watcher"}))
        game._kill(["doctor"])
        self.assertEqual(game.state.characters["patient"].paranoia, 1)

        game = Game(scenario("ll_malicious_script", holders={"doctor": "internet_celeb",
                                                               "patient": "watcher"}))
        game.state.characters["doctor"].goodwill = 3
        game.state.phase = "goodwill"
        choose(game, lambda item: item.get("source") == "doctor" and item.get("ability") == "release")
        self.assertTrue(game.view()["characters"]["doctor"]["friended_token"])
        choose(game, lambda item: item.get("accept"))
        choose(game, lambda item: "住院患者" in item["label"])
        self.assertEqual(game.state.characters["patient"].paranoia, 1)
        self.assertEqual(game.state.characters["patient"].goodwill, 1)

    def test_secret_key_reveal_restricts_next_day(self):
        game = Game(scenario("ll_sealed_end", ("ll_fabricated_secret", "ll_true_monster"),
                             holders={"doctor": "secret_key"}))
        game.state.characters["doctor"].goodwill = 3
        game.state.characters["doctor"].despair = 2
        game.state.phase = "goodwill"
        choose(game, lambda item: item.get("source") == "doctor" and item.get("ability") == "release")
        self.assertFalse(any(item.get("accept") for item in game.options(game.controller)))
        choose(game, lambda item: item.get("refuse"))
        self.assertEqual(game.known_roles["doctor"]["role"], "secret_key")
        game.state.round = 2
        game.state.phase = "day_start"
        game.dispatch(game.controller, "next")
        self.assertEqual(game.mastermind_plays, 1)

    def test_fabricated_secret_extra_role_and_ll_killer_target(self):
        data = scenario("ll_sealed_end", ("ll_fabricated_secret", "ll_x_citizen"))
        roles = Counter(data["cast"].values())
        self.assertEqual(roles["conspiracy"], 1)
        self.assertEqual(sum(roles[role] for role in ("killer", "brain", "fragment")), 2)
        validate_scenario(data)

        game = Game(scenario(holders={"doctor": "killer", "patient": "ordinary"}))
        game.state.characters["doctor"].location = "hospital"
        game.state.characters["patient"].location = "hospital"
        game.state.characters["patient"].intrigue = 2
        game.state.phase = "day_end"
        choose(game, lambda item: "住院患者" in item["label"] and "杀手" in item["label"])
        self.assertFalse(game.state.characters["patient"].alive)

    def test_fragment_and_worldline_grant_at_most_one_special_card_each(self):
        game = Game(scenario("ll_sealed_end", ("ll_beyond_worldline", "ll_x_citizen"),
                             days=1, loops=2))
        game._previous_fragment_dead = {"doctor"}
        game._previous_fragment_friendly = {"doctor"}
        game._new_loop()
        self.assertEqual(game.state.hands["m"].count("ahr_d1"), 1)
        for actor in ("a", "b", "c"):
            self.assertEqual(game.state.hands[actor].count("ahr_h1"), 1)

    def test_executor_and_cocoon(self):
        executor = Game(scenario(incidents=[
            {"day": 1, "kind": "executor", "culprit": "doctor"}]))
        run_incident(executor)
        choose(executor, lambda item: "主人公 B" in item["label"])
        self.assertEqual(executor.controller, "b")
        choose(executor, lambda item: "护士" in item["label"])
        self.assertFalse(executor.state.characters["nurse"].alive)

        cocoon = Game(scenario(incidents=[
            {"day": 1, "kind": "cocoon", "culprit": "doctor"}]))
        run_incident(cocoon)
        self.assertEqual(cocoon.state.locations["hospital"], 2)

    def test_true_monster_traitor_can_win_alone(self):
        game = Game(scenario("ll_sealed_end", ("ll_true_monster", "ll_x_citizen"), order=("A", "B", "C")))
        game._ll_dead_once = set(tuple(game.state.characters)[:5])
        game.state.phase = "day_end"
        game._start_day_end_forced()
        self.assertEqual(game.winner, "traitor:a")

    def test_myth_collector_counts_first_goodwill_declarations(self):
        game = Game(scenario("ll_sealed_end", ("ll_myth_collector", "ll_x_citizen"),
                             order=("A", "B", "C")))
        game._ll_friended_once = set(tuple(game.state.characters)[:5]) - {"doctor"}
        while len(game._ll_friended_once) < 5:
            game._ll_friended_once.add(tuple(game.state.characters)[len(game._ll_friended_once)])
        game.state.characters["doctor"].goodwill = 3
        game.state.phase = "goodwill"
        choose(game, lambda item: item.get("source") == "doctor" and item.get("ability") == "release")
        self.assertEqual(game.winner, "traitor:b")

    def test_hope_and_despair_modify_all_counter_checks(self):
        game = Game(scenario())
        doctor = game.state.characters["doctor"]
        doctor.goodwill, doctor.hope = 2, 1
        game.state.phase = "goodwill"
        self.assertTrue(any(item.get("source") == "doctor" and item.get("ability") == "release"
                            for item in game.options(game.controller)))

        data = scenario(incidents=[{"day": 1, "kind": "cocoon", "culprit": "doctor"}])
        game = Game(data)
        game.state.characters["doctor"].paranoia = 1
        game.state.characters["doctor"].despair = 1
        run_incident(game, score=1)
        self.assertTrue(game.incident_records[0]["happened"])

    def test_final_battle_mastermind_announcement_and_c_detective(self):
        data = scenario("ll_sealed_end", ("ll_detective", "ll_x_citizen"), order=("C", "A", "B"),
                        holders={"doctor": "clown"},
                        incidents=[{"day": 1, "kind": "cocoon", "culprit": "doctor"}])
        game = Game(data)
        game._start_final_guess()
        self.assertEqual(game.controller, "a")
        choose(game, lambda item: "医生" in item["label"])
        self.assertEqual(game.winner, "traitor:a")

    def test_final_battle_supports_two_traitors(self):
        data = scenario("ll_sealed_end", ("ll_true_monster", "ll_detective"),
                        order=("A", "B", "C"))
        game = Game(data)
        culprit = game.scenario["incidents"][0]["culprit"]
        game._start_final_guess()
        declaration = next(event for event in game.state.events if event["kind"] == "traitor_declared")
        self.assertEqual(declaration["seats"], ["a", "c"])
        self.assertEqual(game.controller, "c")
        choose(game, lambda item: game.name(culprit) not in item["label"])
        self.assertEqual(game.state.phase, "final_guess")
        self.assertEqual(game.state.leader, "b")


if __name__ == "__main__":
    unittest.main()
