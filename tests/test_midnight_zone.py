"""Midnight Zone catalog, validation, information and resolution tests."""

from collections import Counter
from copy import deepcopy
from itertools import combinations
import json
from pathlib import Path
import subprocess
import sys
import unittest

from tragedy_sim import Game, RuleError
from tragedy_sim.catalog import CHARACTERS, MODULES, PLOTS
from tragedy_sim.scenario import example_scenario, validate_scenario


Y_SLOTS = {
    "sealed": {"brain": 1, "cultist": 1},
    "mz_secret_record": {"key": 1, "brain": 1, "conspiracy": 1},
    "mz_battle": {"ninja": 1},
    "mz_approaching": {"key": 1, "cultist": 1, "ninja": 1},
    "mz_causal": {"friend": 1, "serial": 1, "conspiracy": 1},
}
X_SLOTS = {
    "mz_love_hate": {"friend": 1, "obsessive": 1},
    "mz_witch_tea": {"friend": 1, "conspiracy": 1, "witch": 2},
    "mz_gods_dice": {"serial": 1, "obsessive": 1},
    "mz_factor": {"factor": 1},
    "mz_death_show": {"magician": 1, "immortal": 1},
    "mz_clear_mind": {"conspiracy": 1, "magician": 1},
    "mz_doom_song": {"prophet": 1},
}


def scenario(main="sealed", subplots=None, *, holders=None, incidents=None, days=3, loops=2):
    subplots = list(subplots or ("mz_factor", "mz_death_show"))
    needed = Counter()
    for plot in (main, *subplots):
        needed.update(PLOTS[plot][2])
    for role, cap in MODULES["MZ"].role_caps.items():
        needed[role] = min(needed[role], cap)
    cast = dict.fromkeys(MODULES["MZ"].characters, "ordinary")
    holders = dict(holders or {})
    cast.update(holders)
    assigned = Counter(holders.values())
    free = [cid for cid in cast if cid not in holders]
    for role in sorted(needed):
        for _ in range(needed[role] - assigned[role]):
            cid = free.pop(0)
            cast[cid] = role
    return {"id": "mz-test", "title": "MZ 规则测试", "module": "MZ", "days": days,
            "loops": loops, "main_plot": main, "subplots": subplots, "cast": cast,
            "incidents": list(incidents or ()), "table_talk": False}


def make(*args, **kwargs):
    return Game(scenario(*args, **kwargs))


def run_incident(game, *, panic=True):
    game.state.phase = "incident"
    if panic:
        culprit = game.scenario["incidents"][0]["culprit"]
        game.state.characters[culprit].paranoia = CHARACTERS[culprit].limit
    game.dispatch("m", "next")


def choose(game, predicate, actor=None):
    actor = game.controller if actor is None else actor
    options = game.options(actor)
    index = next((i for i, item in enumerate(options, 1) if predicate(item)), None)
    if index is None:
        raise AssertionError(f"missing option in {game.state.phase}: {options}")
    game.dispatch(actor, "choose", index=index)


class MidnightZoneCatalogAndScenarioTests(unittest.TestCase):
    def test_printed_slots_and_module_metadata(self):
        self.assertEqual(MODULES["MZ"].plots, tuple((*Y_SLOTS, *X_SLOTS)))
        for plot, slots in {**Y_SLOTS, **X_SLOTS}.items():
            self.assertEqual(PLOTS[plot][2], slots)
        self.assertTrue(MODULES["MZ"].cli_supported)
        self.assertTrue(MODULES["MZ"].gui_supported)
        self.assertEqual(validate_scenario(example_scenario("MZ")), example_scenario("MZ"))
        self.assertEqual(validate_scenario(json.loads(
            Path("examples/mz-tutorial.json").read_text(encoding="utf-8"))),
            example_scenario("MZ"))

    def test_all_105_plot_combinations_validate(self):
        count = 0
        for main in Y_SLOTS:
            for subplots in combinations(X_SLOTS, 2):
                holders = {"worker": "ninja"} if main == "mz_battle" else {}
                data = scenario(main, subplots, holders=holders)
                obsessive = next((cid for cid, role in data["cast"].items()
                                   if role == "obsessive"), None)
                incidents = []
                if obsessive:
                    incidents.append({"day": 1, "kind": "serial_murder", "culprit": obsessive})
                if "mz_doom_song" in subplots:
                    culprit = next(cid for cid in data["cast"] if cid != obsessive)
                    incidents.append({"day": 2, "kind": "suicide", "culprit": culprit})
                data["incidents"] = incidents
                validate_scenario(data)
                count += 1
        self.assertEqual(count, 105)

    def test_special_script_constraints(self):
        valid = scenario("mz_battle", holders={"worker": "ninja"})
        validate_scenario(valid)
        invalid = deepcopy(valid)
        invalid["cast"]["worker"], invalid["cast"]["patient"] = "ordinary", "ninja"
        with self.assertRaisesRegex(RuleError, "男性属性"):
            validate_scenario(invalid)

        doom = scenario(subplots=["mz_factor", "mz_doom_song"])
        with self.assertRaisesRegex(RuleError, "至少有一起自杀"):
            validate_scenario(doom)
        obsessive = scenario("mz_battle", ["mz_love_hate", "mz_factor"],
                             holders={"worker": "ninja", "doctor": "obsessive"})
        with self.assertRaisesRegex(RuleError, "强迫症"):
            validate_scenario(obsessive)

    def test_duplicate_culprits_and_fake_public_name(self):
        repeated = scenario(incidents=[
            {"day": 1, "kind": "serial_murder", "culprit": "doctor"},
            {"day": 2, "kind": "serial_murder", "culprit": "doctor"},
        ])
        validate_scenario(repeated)
        repeated["incidents"][1]["kind"] = "suicide"
        with self.assertRaisesRegex(RuleError, "只有连续杀人"):
            validate_scenario(repeated)
        fake = scenario(incidents=[{"day": 1, "kind": "fake_incident", "culprit": "doctor",
                                    "public_kind": "poison_gas"}])
        self.assertEqual(validate_scenario(fake)["incidents"][0]["public_kind"], "poison_gas")


class MidnightZoneRuleTests(unittest.TestCase):
    def test_continuous_murder_unease_missing_and_fake_suicide(self):
        murder = make(incidents=[{"day": 1, "kind": "serial_murder", "culprit": "doctor"}])
        run_incident(murder)
        choose(murder, lambda item: any(e.get("target") == "patient" for e in item["effects"]))
        self.assertFalse(murder.state.characters["patient"].alive)

        unease = make(incidents=[{"day": 1, "kind": "unease", "culprit": "doctor"}])
        run_incident(unease)
        choose(unease, lambda item: any(e.get("target") == "student" for e in item["effects"]))
        choose(unease, lambda item: any(e.get("target") == "girl" for e in item["effects"]))
        self.assertEqual(unease.state.characters["student"].paranoia, 2)
        self.assertEqual(unease.state.characters["girl"].intrigue, 1)

        missing = make(incidents=[{"day": 1, "kind": "missing", "culprit": "patient"}])
        run_incident(missing)
        self.assertFalse(any("神社" in item["label"] for item in missing.options("m")))
        choose(missing, lambda item: "医院" in item["label"])
        self.assertEqual(missing.state.locations["hospital"], 1)

        fake = make(incidents=[{"day": 1, "kind": "fake_suicide", "culprit": "doctor"}])
        run_incident(fake)
        self.assertEqual(fake.ex_cards["doctor"], 1)

    def test_covert_activity_copies_a_previous_public_event_effect(self):
        game = make(incidents=[{"day": 1, "kind": "covert_activity", "culprit": "doctor"}])
        game._occurred_incidents = [{"kind": "serial_murder", "culprit": "student"}]
        run_incident(game)
        choose(game, lambda item: "连续杀人" in item["label"])
        choose(game, lambda item: any(e.get("target") == "patient" for e in item["effects"]))
        self.assertFalse(game.state.characters["patient"].alive)

        outside = make(incidents=[{"day": 1, "kind": "covert_activity", "culprit": "doctor"}])
        outside._occurred_incidents = [{"kind": "poison_gas", "culprit": "student"}]
        run_incident(outside)
        choose(outside, lambda item: "毒气扩散" in item["label"])
        self.assertEqual(set(outside.state.locations.values()), {0})
        self.assertFalse(outside.incident_records[0]["effective"])

    def test_riot_breakthrough_and_obsessive_event(self):
        riot = make(holders={"patient": "immortal"},
                    incidents=[{"day": 1, "kind": "riot", "culprit": "doctor"}])
        riot.state.locations["hospital"] = 1
        run_incident(riot)
        self.assertTrue(riot.state.characters["patient"].alive)
        self.assertFalse(riot.state.characters["doctor"].alive)

        breaking = make(incidents=[{"day": 1, "kind": "breakthrough", "culprit": "doctor"}])
        breaking.state.characters["student"].intrigue = 1
        run_incident(breaking)
        self.assertEqual(breaking.controller, "a")
        choose(breaking, lambda item: any(e.get("target") == "student" for e in item["effects"]), "a")
        self.assertEqual(breaking.state.characters["student"].intrigue, 0)

        obsessive = make("mz_battle", ["mz_love_hate", "mz_factor"],
                         holders={"worker": "ninja", "doctor": "obsessive"},
                         incidents=[{"day": 1, "kind": "fake_suicide", "culprit": "doctor"}])
        run_incident(obsessive, panic=False)
        self.assertTrue(obsessive.incident_records[0]["happened"])
        self.assertEqual(obsessive.ex_cards["doctor"], 1)

    def test_prophet_blocks_placements_and_incidents_but_doom_song_lowers_person_threshold(self):
        data = scenario(subplots=["mz_factor", "mz_doom_song"], holders={"patient": "prophet"},
                        incidents=[{"day": 1, "kind": "suicide", "culprit": "doctor"}])
        game = Game(data)
        game.state.phase = "mastermind"
        with self.assertRaisesRegex(RuleError, "预言家"):
            game.dispatch("m", "play", card="p1a", target="patient")

        game.state.characters["doctor"].location = "hospital"
        game.state.characters["doctor"].paranoia = CHARACTERS["doctor"].limit - 1
        run_incident(game, panic=False)
        self.assertFalse(game.incident_records[0]["happened"])

        game = Game(data)
        game.state.characters["patient"].location = "school"
        game.state.characters["doctor"].paranoia = CHARACTERS["doctor"].limit - 1
        run_incident(game, panic=False)
        self.assertTrue(game.incident_records[0]["happened"])

    def test_fake_incident_public_information_ex_and_action_lock(self):
        game = make(incidents=[{"day": 1, "kind": "fake_incident", "culprit": "doctor",
                               "public_kind": "suicide"}])
        run_incident(game)
        public = game.view()
        self.assertEqual(public["schedule"], [{"day": 1, "kind": "suicide"}])
        self.assertEqual(public["incidents"][0]["kind"], "suicide")
        self.assertNotIn("fake_incident", repr(public))
        self.assertEqual(public["characters"]["doctor"]["ex_cards"], 1)
        game.state.phase = "protagonists"
        with self.assertRaisesRegex(RuleError, "Ex"):
            game.dispatch(game.controller, "play", card="g1", target="doctor")

    def test_causal_bond_friend_bonus_and_ex_transform_are_both_applied(self):
        game = make("mz_causal", holders={"doctor": "friend"})
        game._kill(["doctor"])
        game._finish_loop()
        self.assertEqual(game.state.phase, "loop_end")
        game.dispatch("m", "next")
        self.assertEqual(game.state.phase, "decision")
        choose(game, lambda item: any(e.get("target") == "doctor" for e in item["effects"]))
        self.assertEqual(game.state.characters["doctor"].goodwill, 1)
        self.assertEqual(game.roles["doctor"], "key")
        self.assertEqual(game.view()["characters"]["doctor"]["ex_cards"], 1)
        game._return_phase = "day_start"
        game._queue = [{"kind": "place_ex", "target": "student"}]
        game._drain()
        choose(game, lambda item: "医生 → 男学生" in item["label"])
        self.assertEqual(game.ex_cards["doctor"], 0)
        self.assertEqual(game.ex_cards["student"], 1)
        self.assertEqual(game.roles["doctor"], "friend")
        self.assertEqual(game.roles["student"], "key")
        game._start_final_guess()
        self.assertEqual(set(game.ex_cards.values()), {0})
        self.assertEqual(game.roles, game.scenario["cast"])

    def test_magician_immortal_and_ninja(self):
        game = make("mz_secret_record", ["mz_factor", "mz_death_show"],
                    holders={"doctor": "magician", "nurse": "immortal"})
        game.state.characters["doctor"].goodwill = 2
        game.state.characters["nurse"].location = "hospital"
        game.state.characters["nurse"].goodwill = 1
        game.state.phase = "master_abilities"
        choose(game, lambda item: item.get("key") == "role:magician"
               and any(e.get("target") == "nurse" and e.get("location") == "shrine"
                       for e in item["effects"]))
        self.assertEqual(game.state.characters["nurse"].location, "shrine")
        game._kill(["doctor", "nurse"])
        self.assertFalse(game.state.characters["doctor"].alive)
        self.assertEqual(game.state.characters["doctor"].goodwill, 0)
        self.assertTrue(game.state.characters["nurse"].alive)

        ninja = make("mz_battle", holders={"worker": "ninja"})
        ninja.state.characters["doctor"].location = ninja.state.characters["worker"].location
        ninja.state.characters["doctor"].intrigue = 2
        ninja.state.phase = "day_end"
        ninja._night_forced_done = True
        choose(ninja, lambda item: item.get("key") == "ninja:worker")
        self.assertFalse(ninja.state.characters["doctor"].alive)

    def test_confession_allows_ninja_to_announce_another_role(self):
        game = make("mz_battle", holders={"worker": "ninja"},
                    incidents=[{"day": 1, "kind": "confession", "culprit": "worker"}])
        run_incident(game)
        self.assertEqual(game.state.phase, "decision")
        choose(game, lambda item: "不安定因子" in item["label"])
        self.assertEqual(game.view()["known_roles"]["worker"]["role"], "factor")
        self.assertEqual(game.view("m")["secret"]["roles"]["worker"], "ninja")

    def test_secret_record_battle_death_show_and_clear_mind(self):
        secret = make("mz_secret_record", ["mz_factor", "mz_death_show"])
        factor = next(cid for cid, role in secret.roles.items() if role == "factor")
        secret._publish_role(factor, "factor")
        secret._finish_loop()
        self.assertEqual(secret.state.phase, "loop_end")

        battle = make("mz_battle", holders={"worker": "ninja"})
        battle.state.characters["worker"].intrigue = 2
        battle._finish_loop()
        self.assertEqual(battle.state.phase, "loop_end")

        show = make(subplots=["mz_factor", "mz_death_show"])
        for cid in list(show.state.characters)[6:]:
            show.state.characters[cid].alive = False
        show._finish_loop()
        self.assertEqual(show.state.phase, "loop_end")

        clear = make(subplots=["mz_factor", "mz_clear_mind"])
        clear.state.phase = "mastermind"
        clear.dispatch("m", "play", card="fg", target="student")
        clear.dispatch("m", "play", card="p1a", target="city")
        clear.dispatch("m", "play", card="p1b", target="shrine")
        clear.dispatch("a", "play", card="h", target="student")
        clear.dispatch("b", "play", card="g1", target="city")
        clear.dispatch("c", "play", card="g1", target="shrine")
        clear.dispatch("m", "resolve")
        clear.dispatch("m", "next")
        self.assertEqual(clear.state.characters["student"].location, "school")

    def test_cli_demo_completes(self):
        result = subprocess.run([sys.executable, "-m", "tragedy_sim", "--demo", "--module", "MZ"],
                                text=True, capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("演示完成", result.stdout)


if __name__ == "__main__":
    unittest.main()
