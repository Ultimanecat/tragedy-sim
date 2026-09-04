"""OldFashion catalog, scenario, rules, incident, action-count and CLI tests.

The fixtures deliberately use only OF's eleven printed characters.  Rare board
positions are assembled directly, while every actual choice goes through the
public ``dispatch`` interface.
"""

from collections import Counter
from itertools import combinations
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tragedy_sim import Game, RuleError
from tragedy_sim.cards import LOCATIONS, PROTAGONISTS
from tragedy_sim.catalog import (
    CHARACTERS,
    INCIDENT_NAMES,
    INCIDENT_RULES,
    MODULES,
    MODULE_PLOTS,
    PLOTS,
    PLOT_RULES,
    ROLE_NAMES,
    ROLE_RULES,
)
from tragedy_sim.scenario import example_scenario, load_scenario, validate_scenario


Y_SLOTS = {
    "of_dream_beauty": {"key": 1, "puppet": 1, "brain": 1},
    "of_retry": {"key": 1},
    "of_endless": {"brain": 1, "assassin": 1},
    "of_time_patrol": {"terrorist": 1},
    "of_terminator": {"key": 1, "terrorist": 1},
}
X_SLOTS = {
    "of_truman": {"friend": 1},
    "of_delorean": {"loved": 1, "lover": 1},
    "of_blue_cat": {"returner_enemy": 1, "conspiracy": 1},
    "of_lavender": {"returner_friend": 1, "friend": 1},
    "of_doomsday": {"friend": 1, "conspiracy": 1, "trickster": 1},
    "of_grandfather": {"returner_enemy": 1, "friend": 1, "trickster": 1},
    "of_time_war": {"puppet": 1, "returner_enemy": 1,
                    "returner_friend": 1, "conspiracy": 1},
}
NEW_ROLES = {"puppet", "assassin", "terrorist", "returner_enemy",
             "returner_friend", "trickster"}
NEW_INCIDENTS = {"malicious_rumor", "poison_gas", "exposure",
                 "time_distortion", "confession"}


def _gender(cid):
    traits = set(CHARACTERS[cid].traits)
    if traits & {"boy", "man"}:
        return "male"
    if traits & {"girl", "woman"}:
        return "female"
    return None


def scenario(main="of_dream_beauty", subplots=None, *, holders=None,
             days=2, loops=2, incidents=None):
    """Build a valid OF scenario and optionally pin roles to character IDs."""
    subplots = list(subplots or ("of_blue_cat", "of_lavender"))
    needed = Counter()
    for plot in (main, *subplots):
        needed.update(PLOTS[plot][2])
    for role, cap in MODULES["OF"].role_caps.items():
        needed[role] = min(needed[role], cap)

    cast = dict.fromkeys(MODULES["OF"].characters, "ordinary")
    holders = dict(holders or {})
    assigned = Counter(holders.values())
    if any(cid not in cast for cid in holders) or any(assigned[r] > needed[r] for r in assigned):
        raise AssertionError("fixture holders do not match the selected plots")
    cast.update(holders)

    free = [cid for cid in cast if cid not in holders]
    for role in sorted(needed):
        for _ in range(needed[role] - assigned[role]):
            candidates = free
            if role == "friend":
                used = {_gender(cid) for cid, value in cast.items() if value == "friend"}
                candidates = [cid for cid in free if _gender(cid) not in used]
            if not candidates:
                raise AssertionError(f"cannot assign fixture role {role}")
            cid = candidates[0]
            free.remove(cid)
            cast[cid] = role

    return {
        "id": "old-fashion-test",
        "title": "OldFashion 规则测试",
        "module": "OF",
        "days": days,
        "loops": loops,
        "main_plot": main,
        "subplots": subplots,
        "cast": cast,
        "incidents": list(incidents or ()),
        "table_talk": False,
    }


def make(*args, **kwargs):
    return Game(scenario(*args, **kwargs))


def role_holder(game, role):
    return next(cid for cid, value in game.scenario["cast"].items() if value == role)


def select(game, predicate, actor=None):
    actor = game.controller if actor is None else actor
    options = game.options(actor)
    index = next((i for i, choice in enumerate(options, 1) if predicate(choice)), None)
    if index is None:
        raise AssertionError(f"missing choice in {game.state.phase}: {options}")
    game.dispatch(actor, "choose", index=index)


def finish_day(game):
    game.state.round = game.scenario["days"]
    game.state.phase = "day_end"
    game.dispatch("m", "next")


def fire_incident(game):
    item = next(i for i in game.scenario["incidents"] if i["day"] == game._scheduled_day())
    culprit = item["culprit"]
    game.state.characters[culprit].paranoia = CHARACTERS[culprit].limit
    game.state.phase = "incident"
    game.dispatch("m", "next")


def effect_delta(choice, *, counter, sign=0):
    effects = choice.get("effects", ())
    values = [e.get("amount", 0) for e in effects if e.get("kind") == "counter"
              and e.get("counter") == counter]
    if sign > 0:
        values = [value for value in values if value > 0]
    elif sign < 0:
        values = [value for value in values if value < 0]
    return sum(values)


class OldFashionCatalogAndScenarioTests(unittest.TestCase):
    def test_example_json_matches_builtin_old_fashion_scenario(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "of-tutorial.json"
        self.assertEqual(load_scenario(path), example_scenario("OF"))

    def test_catalog_ids_slots_and_module_metadata(self):
        self.assertEqual({plot: PLOTS[plot][2] for plot in Y_SLOTS}, Y_SLOTS)
        self.assertEqual({plot: PLOTS[plot][2] for plot in X_SLOTS}, X_SLOTS)
        self.assertEqual({plot for plot in MODULE_PLOTS["OF"] if PLOTS[plot][1] == "Y"}, set(Y_SLOTS))
        self.assertEqual({plot for plot in MODULE_PLOTS["OF"] if PLOTS[plot][1] == "X"}, set(X_SLOTS))
        self.assertTrue(NEW_ROLES <= ROLE_NAMES.keys())
        self.assertTrue(NEW_ROLES <= ROLE_RULES.keys())
        self.assertTrue(NEW_INCIDENTS <= INCIDENT_NAMES.keys())
        self.assertTrue(NEW_INCIDENTS <= INCIDENT_RULES.keys())
        self.assertTrue(set(Y_SLOTS) | set(X_SLOTS) <= PLOT_RULES.keys())
        spec = MODULES["OF"]
        self.assertEqual(spec.subplot_count, 2)
        self.assertTrue(spec.final_guess)
        self.assertTrue(spec.early_final_guess)
        self.assertTrue(spec.gui_supported)
        self.assertEqual(set(spec.incidents), {"murder", "suicide", "hospital", *NEW_INCIDENTS})

    def test_all_105_plot_combinations_validate(self):
        count = 0
        for main in Y_SLOTS:
            for subplots in combinations(X_SLOTS, 2):
                with self.subTest(main=main, subplots=subplots):
                    data = validate_scenario(scenario(main, subplots))
                    self.assertEqual(data["module"], "OF")
                    self.assertEqual(data["subplots"], list(subplots))
                    count += 1
        self.assertEqual(count, 105)

    def test_of_rejects_wrong_plot_count_foreign_content_and_character(self):
        changes = [
            {"subplots": ["of_truman"]},
            {"subplots": ["of_truman", "rumor"]},
            {"main_plot": "murder_plan"},
            {"incidents": [{"day": 1, "kind": "butterfly", "culprit": "student"}]},
        ]
        for change in changes:
            with self.subTest(change=change):
                data = {**scenario(), **change}
                with self.assertRaises(RuleError):
                    validate_scenario(data)

        data = scenario()
        data["cast"]["teacher"] = data["cast"].pop("idol")
        with self.assertRaises(RuleError):
            validate_scenario(data)

    def test_all_five_new_incidents_validate_and_friend_gender_limit_is_enforced(self):
        incidents = [{"day": day, "kind": kind, "culprit": cid}
                     for day, (kind, cid) in enumerate(zip(sorted(NEW_INCIDENTS),
                                                           MODULES["OF"].characters), 1)]
        data = scenario(days=5, incidents=incidents)
        self.assertEqual(len(validate_scenario(data)["incidents"]), 5)

        valid = scenario("of_retry", ("of_lavender", "of_doomsday"),
                         holders={"student": "friend", "girl": "friend"})
        validate_scenario(valid)
        invalid = scenario("of_retry", ("of_lavender", "of_doomsday"),
                           holders={"student": "friend", "worker": "friend"})
        with self.assertRaises(RuleError):
            validate_scenario(invalid)


class OldFashionMainAndPlotRuleTests(unittest.TestCase):
    def test_dream_beauty_needs_living_brain_and_two_intrigue_on_key(self):
        for brain_alive, intrigue, loses in ((True, 2, True), (False, 2, False), (True, 1, False)):
            with self.subTest(brain_alive=brain_alive, intrigue=intrigue):
                game = make(days=1)
                brain, key = role_holder(game, "brain"), role_holder(game, "key")
                game.state.characters[brain].alive = brain_alive
                game.state.characters[key].intrigue = intrigue
                finish_day(game)
                self.assertEqual(game.state.phase, "loop_end" if loses else "game_over")
                self.assertEqual(game.winner, None if loses else "protagonists")

    def test_retry_forces_final_loop_failure_and_keeps_authored_incident_days(self):
        event = {"day": 2, "kind": "confession", "culprit": "student"}
        game = make("of_retry", ("of_blue_cat", "of_lavender"), days=2, loops=1,
                    incidents=[event])
        finish_day(game)
        self.assertEqual(game.state.phase, "final_guess")

        game = make("of_retry", ("of_blue_cat", "of_lavender"), days=2, loops=3,
                    incidents=[event])
        game.state.phase = "loop_end"
        game.dispatch("m", "next")
        self.assertEqual(game.state.loop, 2)
        self.assertEqual(game.view()["schedule"], [{"day": 2, "kind": "confession"}])
        game.state.round = 2
        fire_incident(game)
        self.assertEqual(game.incident_records[-1]["kind"], "confession")
        self.assertTrue(game.incident_records[-1]["happened"])

    def test_endless_and_time_patrol_loss_conditions(self):
        game = make("of_endless", ("of_truman", "of_lavender"), days=1)
        game.state.locations["shrine"] = 2
        finish_day(game)
        self.assertEqual(game.state.phase, "loop_end")

        for intrigue, loses in ((1, False), (2, True)):
            with self.subTest(terrorist_intrigue=intrigue):
                game = make("of_time_patrol", ("of_truman", "of_lavender"), days=1)
                terrorist = role_holder(game, "terrorist")
                game.state.characters[terrorist].intrigue = intrigue
                game.state.characters[terrorist].alive = False  # The condition explicitly includes corpses.
                finish_day(game)
                self.assertEqual(game.state.phase, "loop_end" if loses else "game_over")

    def test_terminator_and_no_rule_subplots_add_no_extra_loss(self):
        game = make("of_terminator", ("of_lavender", "of_time_war"), days=1)
        finish_day(game)
        self.assertEqual(game.winner, "protagonists")

    def test_delorean_checks_loved_character_goodwill(self):
        for goodwill, loses in ((2, False), (3, True)):
            with self.subTest(goodwill=goodwill):
                game = make("of_terminator", ("of_delorean", "of_truman"), days=1)
                game.state.characters[role_holder(game, "loved")].goodwill = goodwill
                finish_day(game)
                self.assertEqual(game.state.phase, "loop_end" if loses else "game_over")

    def test_blue_cat_places_one_intrigue_anywhere_once_per_loop(self):
        game = make()
        game.state.phase = "master_abilities"
        choices = [choice for choice in game.options("m") if choice.get("key") == "plot:of_blue_cat"]
        targets = {effect["target"] for choice in choices for effect in choice["effects"]
                   if effect.get("kind") == "counter"}
        self.assertEqual(targets, set(game.state.characters) | set(LOCATIONS))
        select(game, lambda choice: choice.get("key") == "plot:of_blue_cat"
               and choice["effects"][0].get("target") == "school")
        self.assertEqual(game.state.locations["school"], 1)
        self.assertFalse(any(choice.get("key") == "plot:of_blue_cat" for choice in game.options("m")))

    def test_doomsday_kills_every_character_at_four_paranoia(self):
        game = make("of_terminator", ("of_doomsday", "of_lavender"), days=1)
        victims = [cid for cid, role in game.roles.items() if role == "ordinary"][:2]
        for cid in victims:
            game.state.characters[cid].paranoia = 4
        finish_day(game)
        self.assertTrue(all(not game.state.characters[cid].alive for cid in victims))

    def test_grandfather_kills_returner_enemy_if_friend_is_dead(self):
        game = make("of_terminator", ("of_grandfather", "of_lavender"), days=1)
        enemy, friend = role_holder(game, "returner_enemy"), role_holder(game, "friend")
        game.state.characters[friend].alive = False
        trickster = role_holder(game, "trickster")
        game.state.characters[trickster].location = "city"
        for cid, char in game.state.characters.items():
            if cid != trickster and char.location == "city":
                char.location = "hospital"
        finish_day(game)
        self.assertFalse(game.state.characters[enemy].alive)
        self.assertEqual(game.state.phase, "loop_end")


class OldFashionRoleTests(unittest.TestCase):
    def test_puppet_at_four_goodwill_must_refuse_die_and_remain_a_corpse(self):
        game = make(holders={"student": "puppet", "girl": "key", "doctor": "brain"})
        game.state.characters["student"].goodwill = 4
        game.state.phase = "goodwill"
        select(game, lambda choice: choice.get("source") == "student")
        self.assertEqual(game.state.phase, "refusal")
        self.assertTrue(game.options("m"))
        self.assertTrue(all(choice.get("refuse") for choice in game.options("m")))
        game.dispatch("m", "choose", index=1)
        self.assertFalse(game.state.characters["student"].alive)

        game.state.phase = "loop_end"
        game.dispatch("m", "next")
        self.assertFalse(game.state.characters["student"].alive)

    def test_truman_gives_ordinary_characters_the_puppet_ability(self):
        game = make("of_retry", ("of_truman", "of_blue_cat"))
        cid = next(cid for cid, role in game.scenario["cast"].items()
                   if role == "ordinary" and CHARACTERS[cid].abilities)
        self.assertEqual(game.roles[cid], "puppet")
        game.state.characters[cid].goodwill = 5
        game.state.phase = "goodwill"
        select(game, lambda choice: choice.get("source") == cid)
        self.assertTrue(all(choice.get("refuse") for choice in game.options("m")))
        game.dispatch("m", "choose", index=1)
        self.assertFalse(game.state.characters[cid].alive)

    def test_assassin_can_kill_heroes_at_three_intrigue(self):
        game = make("of_endless", ("of_truman", "of_lavender"))
        assassin = role_holder(game, "assassin")
        game.state.characters[assassin].intrigue = 3
        game.state.phase = "day_end"
        select(game, lambda choice: any(effect.get("kind") == "heroes_die"
                                         for effect in choice["effects"]))
        self.assertEqual(game.state.phase, "loop_end")
        self.assertFalse(any(event["kind"] == "heroes_died" for event in game.view()["events"]))

    def test_puppet_death_from_an_incident_also_persists(self):
        game = make("of_retry", ("of_time_war", "of_truman"), days=1,
                    holders={"worker": "puppet"},
                    incidents=[{"day": 1, "kind": "suicide", "culprit": "worker"}])
        fire_incident(game)
        self.assertEqual(game.state.phase, "loop_end")
        self.assertFalse(game.state.characters["worker"].alive)
        game.dispatch("m", "next")
        self.assertFalse(game.state.characters["worker"].alive)

    def test_terrorist_can_kill_heroes_or_a_character_from_an_intrigued_region(self):
        game = make("of_time_patrol", ("of_truman", "of_lavender"))
        terrorist = role_holder(game, "terrorist")
        location = game.state.characters[terrorist].location
        game.state.locations[location] = 3
        game.state.phase = "day_end"
        select(game, lambda choice: any(effect.get("kind") == "heroes_die"
                                         for effect in choice["effects"]))
        self.assertEqual(game.state.phase, "loop_end")

        game = make("of_time_patrol", ("of_truman", "of_lavender"))
        terrorist = role_holder(game, "terrorist")
        location = game.state.characters[terrorist].location
        victim = next(cid for cid, char in game.state.characters.items()
                      if cid != terrorist and char.location == location)
        game.state.locations[location] = 2
        game.state.phase = "day_end"
        select(game, lambda choice: any(effect.get("kind") == "kill" and effect.get("target") == victim
                                         for effect in choice["effects"]))
        self.assertFalse(game.state.characters[victim].alive)

    def test_returner_enemy_cancels_one_hero_card_in_its_region_once_per_loop(self):
        game = make("of_retry", ("of_blue_cat", "of_lavender"),
                    holders={"doctor": "returner_enemy", "student": "conspiracy",
                             "girl": "returner_friend", "rich": "friend", "patient": "key"})
        game.dispatch("m", "next")
        for actor, card, target in (
                ("m", "p1a", "student"), ("m", "p1b", "city"), ("m", "h", "shrine"),
                ("a", "g1", "patient"), ("b", "g1", "student"), ("c", "g1", "rich")):
            game.dispatch(actor, "play", card=card, target=target)
        game.dispatch("m", "resolve")
        self.assertEqual(game.state.phase, "action_counters")
        select(game, lambda choice: choice.get("source") == "doctor"
               and any(effect.get("kind") in ("cancel_card", "ignore_card")
                       for effect in choice["effects"]))
        game.dispatch("m", "next")
        self.assertEqual(game.state.characters["patient"].goodwill, 0)
        self.assertFalse(any(choice.get("source") == "doctor" for choice in game.options("m")))

    def test_returner_friend_inherits_all_counters_only_after_qualifying(self):
        game = make(holders={"girl": "returner_friend", "student": "key",
                             "worker": "puppet", "doctor": "brain"})
        friend = game.state.characters["girl"]
        friend.goodwill, friend.paranoia, friend.intrigue = 3, 1, 2
        game.guards["girl"] = 1
        game.state.characters["student"].intrigue = 2  # Dream Beauty supplies a failed loop.
        finish_day(game)
        self.assertEqual(game.state.phase, "loop_end")
        game.dispatch("m", "next")
        inherited = game.state.characters["girl"]
        self.assertEqual((inherited.goodwill, inherited.paranoia, inherited.intrigue), (3, 1, 2))
        self.assertEqual(game.guards["girl"], 1)

    def test_trickster_kills_a_companion_or_dies_when_alone(self):
        game = make("of_terminator", ("of_doomsday", "of_lavender"), days=1)
        trickster = role_holder(game, "trickster")
        location = game.state.characters[trickster].location
        companions = [cid for cid, char in game.state.characters.items()
                      if cid != trickster and char.location == location][:3]
        self.assertEqual(len(companions), 3)
        finish_day(game)
        self.assertEqual(game.state.phase, "decision")
        select(game, lambda choice: any(effect.get("kind") == "kill"
                                         and effect.get("target") == companions[0]
                                         for effect in choice["effects"]))
        self.assertFalse(game.state.characters[companions[0]].alive)

        game = make("of_terminator", ("of_doomsday", "of_lavender"), days=1)
        trickster = role_holder(game, "trickster")
        for cid, char in game.state.characters.items():
            if cid != trickster and char.location == game.state.characters[trickster].location:
                char.location = "hospital" if char.location != "hospital" else "school"
        finish_day(game)
        self.assertFalse(game.state.characters[trickster].alive)

    def test_two_tricksters_recompute_targets_and_never_repeat_a_designation(self):
        game = make("of_terminator", ("of_doomsday", "of_grandfather"), days=1)
        tricksters = [cid for cid, role in game.roles.items() if role == "trickster"]
        self.assertEqual(len(tricksters), 2)
        for char in game.state.characters.values():
            char.location = "school"
        victims = [cid for cid, role in game.roles.items()
                   if role == "ordinary" and cid not in tricksters]
        finish_day(game)
        self.assertEqual(game.state.phase, "decision")
        first = victims[0]
        select(game, lambda choice: any(effect.get("kind") == "kill" and effect.get("target") == first
                                         for effect in choice["effects"]))
        self.assertEqual(game.state.phase, "decision")
        available = {effect["target"] for choice in game.options("m") for effect in choice["effects"]
                     if effect.get("kind") == "kill"}
        self.assertNotIn(first, available)
        second = next(cid for cid in victims[1:] if cid in available)
        select(game, lambda choice: any(effect.get("kind") == "kill" and effect.get("target") == second
                                         for effect in choice["effects"]))
        self.assertFalse(game.state.characters[first].alive)
        self.assertFalse(game.state.characters[second].alive)


class OldFashionIncidentAndActionTests(unittest.TestCase):
    def incident_game(self, kind, *, culprit="student", days=1):
        return make(incidents=[{"day": 1, "kind": kind, "culprit": culprit}], days=days)

    def test_malicious_rumor_adds_two_paranoia_to_everyone_in_region(self):
        game = self.incident_game("malicious_rumor")
        same = [cid for cid, char in game.state.characters.items() if char.location == "school"]
        other = next(cid for cid, char in game.state.characters.items() if char.location != "school")
        fire_incident(game)
        self.assertTrue(all(game.state.characters[cid].paranoia == (4 if cid == "student" else 2)
                            for cid in same))
        self.assertEqual(game.state.characters[other].paranoia, 0)

    def test_poison_gas_adds_intrigue_to_culprit_region_and_one_other_region(self):
        game = self.incident_game("poison_gas")
        fire_incident(game)
        self.assertEqual(game.state.phase, "decision")
        select(game, lambda choice: any(effect.get("kind") == "counter"
                                         and effect.get("target") == "city"
                                         for effect in choice["effects"]))
        self.assertEqual(game.state.locations["school"], 1)
        self.assertEqual(game.state.locations["city"], 1)
        self.assertEqual(sum(game.state.locations.values()), 2)

    def test_exposure_can_add_or_remove_two_goodwill_in_culprit_region(self):
        game = self.incident_game("exposure")
        school = [cid for cid, char in game.state.characters.items() if char.location == "school"]
        fire_incident(game)
        select(game, lambda choice: effect_delta(choice, counter="goodwill", sign=1) == 2)
        self.assertEqual(sum(game.state.characters[cid].goodwill for cid in school), 2)

        game = self.incident_game("exposure")
        school = [cid for cid, char in game.state.characters.items() if char.location == "school"]
        game.state.characters[school[0]].goodwill = 2
        fire_incident(game)
        select(game, lambda choice: effect_delta(choice, counter="goodwill", sign=-1) == -2)
        self.assertEqual(sum(game.state.characters[cid].goodwill for cid in school), 0)

    def test_confession_publicly_reveals_culprit_role(self):
        game = self.incident_game("confession")
        fire_incident(game)
        self.assertEqual(game.known_roles["student"]["role"], game.roles["student"])
        self.assertIn("student", game.view()["known_roles"])
        self.assertTrue(any(event["kind"] == "role_revealed" for event in game.view()["events"]))

    def test_public_hospital_incident_still_announces_protagonist_death(self):
        game = self.incident_game("hospital")
        game.state.locations["hospital"] = 2
        fire_incident(game)
        self.assertTrue(any(event["kind"] == "heroes_died" for event in game.view()["events"]))

    def test_time_distortion_changes_the_next_day_to_four_vs_two_and_skips_leader(self):
        game = self.incident_game("time_distortion", days=2)
        fire_incident(game)
        self.assertEqual(game.state.phase, "day_end")
        game.dispatch("m", "next")
        game.dispatch("m", "next")
        self.assertEqual(game.state.round, 2)
        self.assertEqual(game.state.phase, "mastermind")
        self.assertEqual(game.view()["action_counts"], {"mastermind": 4, "protagonists": 2})

        for card, target in (("p1a", "student"), ("p1b", "city"),
                             ("h", "shrine"), ("i2", "hospital")):
            game.dispatch("m", "play", card=card, target=target)
        self.assertEqual(game.state.phase, "protagonists")
        leader = game.state.leader
        with self.assertRaises(RuleError):
            game.dispatch(leader, "play", card="g1", target="girl")
        leader_index = PROTAGONISTS.index(leader)
        expected = tuple(PROTAGONISTS[(leader_index + offset) % len(PROTAGONISTS)]
                         for offset in (1, 2))
        self.assertEqual(tuple(game.view()["protagonist_order"]), expected)
        game.dispatch(expected[0], "play", card="g1", target="girl")
        game.dispatch(expected[1], "play", card="g1", target="doctor")
        self.assertEqual(game.state.phase, "reveal")
        self.assertEqual(len(game.state.pending), 6)


class OldFashionFinalGuessAndCLITests(unittest.TestCase):
    def test_command_only_time_distortion_save_replays_exactly(self):
        data = scenario("of_retry", ("of_blue_cat", "of_lavender"), days=2,
                        incidents=[{"day": 1, "kind": "time_distortion", "culprit": "student"}])
        game = Game(data)
        game.dispatch("m", "next")
        for actor, card, target in (
                ("m", "p1a", "student"), ("m", "p1b", "city"), ("m", "h", "shrine"),
                ("a", "p1", "student"), ("b", "g1", "city"), ("c", "g1", "shrine")):
            game.dispatch(actor, "play", card=card, target=target)
        game.dispatch("m", "resolve")
        for actor in ("m", "m", "a", "m"):
            game.dispatch(actor, "next")
        self.assertEqual(game.state.phase, "day_end")
        game.dispatch("m", "next")
        game.dispatch("m", "next")
        self.assertEqual(game.view()["action_counts"], {"mastermind": 4, "protagonists": 2})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "of-save.json"
            game.save(path)
            loaded = Game.load(path)
        self.assertEqual(loaded.view("m"), game.view("m"))

    def test_exhausted_failure_enters_final_guess_and_correct_or_wrong_guess_ends_game(self):
        for correct in (True, False):
            with self.subTest(correct=correct):
                game = make("of_endless", ("of_truman", "of_lavender"), days=1, loops=1)
                game.state.locations["shrine"] = 2
                finish_day(game)
                self.assertEqual(game.state.phase, "final_guess")
                if correct:
                    while game.winner is None:
                        cid = game.view()["guess_remaining"][0]
                        game.dispatch(game.controller, "guess", character=cid,
                                      role=game.scenario["cast"][cid])
                    self.assertEqual(game.winner, "protagonists")
                else:
                    cid = game.view()["guess_remaining"][0]
                    wrong = next(role for role in ROLE_NAMES if role != game.scenario["cast"][cid])
                    game.dispatch(game.controller, "guess", character=cid, role=wrong)
                    self.assertEqual(game.winner, "mastermind")

    def test_of_leader_may_enter_final_guess_between_loops(self):
        game = make("of_endless", ("of_truman", "of_lavender"), days=1)
        game.state.locations["shrine"] = 2
        finish_day(game)
        with self.assertRaises(RuleError):
            game.dispatch("m", "final")
        game.dispatch(game.state.leader, "final")
        self.assertEqual(game.state.phase, "final_guess")

    def run_cli(self, *args, commands=""):
        return subprocess.run([sys.executable, "-m", "tragedy_sim", *args], input=commands,
                              capture_output=True, encoding="utf-8", timeout=15,
                              cwd=Path(__file__).resolve().parents[1])

    def test_cli_rules_lists_of_content(self):
        result = self.run_cli("--module", "OF", commands="rules\nquit\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OF 模组公开资料", result.stdout)
        for content_id in (*Y_SLOTS, *X_SLOTS, *sorted(NEW_ROLES), *sorted(NEW_INCIDENTS)):
            self.assertIn(f"[{content_id}]", result.stdout)
        self.assertNotIn("�", result.stdout)

    def test_cli_demo_completes_old_fashion(self):
        result = self.run_cli("--demo", "--module", "OF")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("演示完成", result.stdout)
        self.assertIn("OF", result.stdout)
        self.assertNotIn("�", result.stdout)


if __name__ == "__main__":
    unittest.main()
