"""FS/BTX integration and edge-case rules, with explicit board fixtures.

Fixture mutations set up rare positions. All tested choices use the public command
dispatcher; replay tests start from unmodified scenarios and use dispatch only.
"""

from collections import Counter
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
from itertools import combinations
import json
from pathlib import Path
import random
import re
import subprocess
import sys
import tempfile
import unittest

from tragedy_sim import Game, RuleError
from tragedy_sim.cards import ACTORS, LOCATIONS, deck
from tragedy_sim.catalog import CHARACTERS, INCIDENT_NAMES, MODULES, MODULE_PLOTS, PLOTS
from tragedy_sim.scenario import example_scenario, validate_scenario


def make(module="FS", main=None, subplots=None, roles=None, kind=None, culprit="doctor", days=3, loops=3):
    main = main or ("avenger" if module == "FS" else "bomb")
    subplots = subplots or (["rumor"] if module == "FS" else ["rumor", "threads"])
    roles = roles or ({"doctor": "brain", "maiden": "conspiracy"} if module == "FS"
                      else {"worker": "witch", "maiden": "conspiracy"})
    return Game({"id": "test", "title": "规则测试", "module": module, "days": days, "loops": loops,
                 "main_plot": main, "subplots": subplots,
                 "cast": {c: roles.get(c, "ordinary") for c in CHARACTERS},
                 "incidents": [] if kind is None else [{"day": 1, "kind": kind, "culprit": culprit}]})


def select(game, predicate):
    choices = game.options(game.controller)
    index = next((i for i, choice in enumerate(choices, 1) if predicate(choice)), None)
    if index is None:
        raise AssertionError(f"Missing choice in {game.state.phase}: {choices}")
    game.dispatch(game.controller, "choose", index=index)


def target(game, cid, kind=None):
    select(game, lambda c: any(e.get("target") == cid and (kind is None or e["kind"] == kind)
                               for e in c["effects"]))


def incident(game, panic=True):
    game.state.phase = "incident"
    if panic:
        cid = game.scenario["incidents"][0]["culprit"]
        game.state.characters[cid].paranoia = CHARACTERS[cid].limit
    game.dispatch("m", "next")


def ability(game, source, aid, target_id=None):
    select(game, lambda c: c.get("source") == source and c.get("ability") == aid
           and (target_id is None or any(e.get("target") == target_id for e in c["effects"])))


def accept(game):
    select(game, lambda c: c.get("accept"))


def idle_step(game):
    """Legal harmless actions, skip optional effects, never skip mandatory choices."""
    actor, phase = game.controller, game.state.phase
    if phase == "mastermind":
        n = len(game.state.pending)
        card, t = (("p1a", "school"), ("p1b", "city"), ("h", "shrine"))[n]
        game.dispatch(actor, "play", card=card, target=t)
    elif phase == "protagonists":
        n = sum(p.actor != "m" for p in game.state.pending)
        game.dispatch(actor, "play", card="g1", target=("school", "city", "shrine")[n])
    elif phase == "reveal":
        game.dispatch(actor, "resolve")
    elif phase in ("decision", "refusal"):
        game.dispatch(actor, "choose", index=1)
    elif phase == "final_guess":
        cid = game.view()["guess_remaining"][0]
        game.dispatch(actor, "guess", character=cid, role=game.scenario["cast"][cid])
    else:
        game.dispatch(actor, "next")


class IncidentTests(unittest.TestCase):
    def test_requires_living_culprit_at_limit(self):
        for alive, panic, expected in ((True, False, False), (False, True, False), (True, True, True)):
            with self.subTest(alive=alive, panic=panic):
                game = make(kind="murder")
                game.state.characters["doctor"].alive = alive
                incident(game, panic)
                self.assertEqual(game.incident_records[0]["happened"], expected)
                self.assertNotIn("culprit", game.view()["incidents"][0])
                self.assertEqual(game.state.phase, "decision" if expected else "day_end")

    def test_murder_targets_other_living_same_location(self):
        game = make(kind="murder")
        game.state.characters["nurse"].alive = False
        incident(game)
        self.assertEqual(game.view()["phase"], "incident")
        self.assertEqual(game.view("m")["phase"], "decision")
        targets = {c["effects"][0]["target"] for c in game.options("m")}
        self.assertEqual(targets, {"patient", "soldier"})
        target(game, "patient")
        self.assertFalse(game.state.characters["patient"].alive)
        self.assertEqual(game.state.phase, "day_end")
        self.assertEqual(game.state.leader, "b")

    def test_murder_without_victim_still_happens(self):
        game = make(kind="murder")
        for c in game.state.characters.values():
            if c.id != "doctor":
                c.location = "city"
        incident(game)
        self.assertEqual(game.incident_records[0], {"day": 1, "kind": "murder", "happened": True, "effective": False})
        self.assertEqual(game.state.phase, "day_end")

    def test_unease_order_and_distinct_targets(self):
        game = make(kind="unease")
        incident(game)
        target(game, "student")
        self.assertEqual(game.state.characters["student"].paranoia, 2)
        self.assertFalse(any(c["effects"][0].get("target") == "student" for c in game.options("m")))
        target(game, "girl")
        self.assertEqual(game.state.characters["girl"].intrigue, 1)
        self.assertEqual(game.state.phase, "day_end")

    def test_suicide_preserves_counters_and_corpse(self):
        game = make(kind="suicide")
        game.state.characters["doctor"].goodwill = 3
        incident(game)
        c = game.state.characters["doctor"]
        self.assertEqual((c.alive, c.location, c.goodwill, c.paranoia), (False, "hospital", 3, 2))

    def test_hospital_thresholds(self):
        for intrigue in (0, 1, 2):
            with self.subTest(intrigue=intrigue):
                game = make(kind="hospital")
                game.state.locations["hospital"] = intrigue
                incident(game)
                self.assertTrue(game.incident_records[0]["happened"])
                self.assertEqual(game.incident_records[0]["effective"], intrigue > 0)
                self.assertEqual(game.state.characters["patient"].alive, intrigue == 0)
                self.assertEqual(game.state.characters["girl"].alive, True)
                self.assertEqual(game.state.phase, "loop_end" if intrigue == 2 else "day_end")

    def test_hospital_key_death_stops_later_protagonist_death(self):
        game = Game(example_scenario())
        game.scenario["incidents"] = [{"day": 1, "kind": "hospital", "culprit": "doctor"}]
        game.state.characters["girl"].location = "hospital"
        game.state.locations["hospital"] = 2
        incident(game)
        self.assertEqual(game.state.phase, "loop_end")
        self.assertTrue(all(not c.alive for c in game.state.characters.values() if c.location == "hospital"))
        self.assertFalse(any(e["kind"] == "heroes_died" for e in game.state.events))
        self.assertFalse(any(e["kind"] == "leader_changed" for e in game.state.events))

    def test_faraway_targets_by_intrigue_not_location_or_culprit(self):
        game = make(kind="faraway")
        game.state.characters["girl"].intrigue = 2
        game.state.characters["student"].intrigue = 1
        incident(game)
        self.assertEqual(len(game.options("m")), 1)
        target(game, "girl")
        self.assertFalse(game.state.characters["girl"].alive)

    def test_missing_respects_forbidden_and_allows_staying(self):
        game = make(kind="missing", culprit="patient")
        incident(game)
        self.assertEqual(len(game.options("m")), 1)
        game.dispatch("m", "choose", index=1)
        self.assertEqual(game.state.characters["patient"].location, "hospital")
        self.assertEqual(game.state.locations["hospital"], 1)
        game = make(kind="missing")
        incident(game)
        select(game, lambda c: c["effects"][0].get("location") == "school")
        self.assertEqual(game.state.characters["doctor"].location, "school")
        self.assertEqual(game.state.locations["school"], 1)

    def test_spreading_partial_removal_still_adds_two(self):
        for available in (0, 1, 3):
            with self.subTest(available=available):
                game = make(kind="spreading")
                game.state.characters["student"].goodwill = available
                incident(game)
                target(game, "student")
                target(game, "girl")
                self.assertEqual(game.state.characters["student"].goodwill, max(0, available - 2))
                self.assertEqual(game.state.characters["girl"].goodwill, 2)

    def test_btx_events(self):
        game = make("BTX", kind="foul_play")
        incident(game)
        self.assertEqual(game.state.locations["shrine"], 2)
        game = make("BTX", kind="butterfly")
        incident(game)
        choices = game.options("m")
        self.assertEqual(len(choices), 12)  # Four hospital characters, three counters.
        select(game, lambda c: c["effects"][0].get("target") == "doctor"
               and c["effects"][0].get("counter") == "goodwill")
        self.assertEqual(game.state.characters["doctor"].goodwill, 1)


class VictoryTests(unittest.TestCase):
    def test_all_loop_end_main_plot_conditions(self):
        cases = [
            ("FS", "avenger", {"doctor": "brain", "maiden": "conspiracy"}, "hospital"),
            ("FS", "protect", {"girl": "key", "doctor": "cultist", "maiden": "conspiracy"}, "school"),
            ("BTX", "sealed", {"doctor": "brain", "girl": "cultist", "maiden": "conspiracy"}, "shrine"),
            ("BTX", "sign", {"girl": "key", "maiden": "conspiracy"}, "girl"),
            ("BTX", "bomb", {"worker": "witch", "maiden": "conspiracy"}, "city"),
        ]
        for module, main, roles, t in cases:
            for amount in (1, 2):
                with self.subTest(main=main, amount=amount):
                    game = make(module, main, roles=roles, days=1)
                    # The initial region matters even when its role-holder has moved.
                    game.state.characters["doctor"].location = "school"
                    game.state.characters["worker"].location = "hospital"
                    if t in LOCATIONS:
                        game.state.locations[t] = amount
                    else:
                        game.state.characters[t].intrigue = amount
                    game.state.phase = "day_end"
                    game.dispatch("m", "next")
                    self.assertEqual(game.state.phase, "loop_end" if amount == 2 else "game_over")
                    self.assertEqual(game.winner, None if amount == 2 else "protagonists")

    def test_butterfly_occurrence_not_effect_is_loss_condition(self):
        game = make("BTX", "change", roles={"doctor": "cultist", "girl": "time_traveler", "maiden": "conspiracy"}, days=1)
        game.incident_records = [{"day": 1, "kind": "butterfly", "happened": True, "effective": False}]
        game.state.phase = "day_end"
        game.dispatch("m", "next")
        self.assertEqual(game.state.phase, "loop_end")

    def test_key_death_is_immediate_and_reason_is_private(self):
        game = Game(example_scenario())
        game.scenario["incidents"] = [{"day": 1, "kind": "suicide", "culprit": "girl"}]
        incident(game)
        self.assertEqual(game.state.phase, "loop_end")
        self.assertFalse(game.view()["known_roles"])
        self.assertNotIn("关键人物", json.dumps(game.view()["events"], ensure_ascii=False))
        self.assertTrue(game.view("m")["secret"]["loss_reasons"])

    def test_fs_exhausts_without_final_guess(self):
        game = make(kind="hospital", loops=1)
        game.state.locations["hospital"] = 2
        incident(game)
        self.assertEqual(game.winner, "mastermind")
        self.assertEqual(game.state.phase, "game_over")
        with self.assertRaises(RuleError):
            game.dispatch("m", "next")

    def test_btx_final_guess_correct_wrong_and_original_roles(self):
        for correct in (True, False):
            game = make("BTX", kind="hospital", loops=1)
            game.state.locations["hospital"] = 2
            game.roles["student"] = "serial"
            incident(game)
            self.assertEqual(game.state.phase, "final_guess")
            self.assertEqual(game.roles["student"], "ordinary")
            self.assertTrue(all(c.alive for c in game.state.characters.values()))
            self.assertTrue(game.view()["incidents"][0]["happened"])
            if correct:
                while game.winner is None:
                    idle_step(game)
                self.assertEqual(game.winner, "protagonists")
            else:
                game.dispatch(game.controller, "guess", character="student", role="key")
                self.assertEqual(game.winner, "mastermind")

    def test_early_guess_only_btx_between_loops_and_by_leader(self):
        game = make("BTX", kind="hospital")
        with self.assertRaises(RuleError):
            game.dispatch("a", "final")
        game.state.locations["hospital"] = 2
        incident(game)
        with self.assertRaises(RuleError):
            game.dispatch("m", "final")
        game.dispatch("a", "final")
        self.assertEqual(game.state.phase, "final_guess")
        game = make(kind="hospital")
        game.state.locations["hospital"] = 2
        incident(game)
        with self.assertRaises(RuleError):
            game.dispatch("a", "final")

    def test_dead_friend_reveals_even_after_early_failure_and_gains_goodwill(self):
        game = make(main="protect", subplots=["hideous"],
                    roles={"girl": "key", "doctor": "cultist", "maiden": "conspiracy", "patient": "friend"}, kind="hospital")
        game.state.locations["hospital"] = 2
        incident(game)
        self.assertEqual(game.known_roles["patient"]["role"], "friend")
        game.dispatch("m", "next")
        self.assertTrue(game.state.characters["patient"].alive)
        self.assertEqual(game.state.characters["patient"].goodwill, 1)
        self.assertEqual(game.state.loop, 2)

    def test_dead_friend_fails_natural_loop_end_without_immediate_loss(self):
        game = make(subplots=["hideous"], roles={"doctor": "brain", "maiden": "conspiracy", "patient": "friend"},
                    kind="suicide", culprit="patient", days=1)
        incident(game)
        self.assertEqual(game.state.phase, "day_end")
        game.dispatch("m", "next")
        self.assertEqual(game.state.phase, "loop_end")
        self.assertEqual(game.known_roles["patient"]["role"], "friend")

    def test_loop_reset_clears_temporary_state_preserves_knowledge_and_threads(self):
        game = make("BTX", kind="hospital")
        game.state.characters["patient"].goodwill = 3
        game.state.characters["patient"].forbidden = ()
        game.state.locations["hospital"] = 2
        game.guards["girl"] = 1
        game.loop_used.add("test")
        game.roles["student"] = "serial"
        incident(game)
        old_events = deepcopy(game.state.events)
        game.dispatch("m", "next")
        self.assertEqual(game.state.characters["patient"].paranoia, 2)
        self.assertEqual(game.state.characters["patient"].goodwill, 0)
        self.assertEqual(game.state.characters["patient"].forbidden, CHARACTERS["patient"].forbidden)
        self.assertEqual(game.roles["student"], "ordinary")
        self.assertFalse(game.loop_used)
        self.assertFalse(any(game.guards.values()))
        self.assertEqual(game.state.events[:len(old_events)], old_events)
        self.assertTrue(all(len(game.state.hands[a]) == len(deck(a)) for a in ACTORS))


class AbilityTests(unittest.TestCase):
    def test_threshold_daily_limit_no_goodwill_cost_and_refusal_source(self):
        game = make()
        game.state.phase = "goodwill"
        game.state.characters["doctor"].paranoia = 2  # Brain can refuse its own power, not Nurse's.
        self.assertFalse(any(c.get("source") == "nurse" for c in game.options("a")))
        game.state.characters["nurse"].goodwill = 2
        ability(game, "nurse", "calm", "doctor")
        accept(game)
        self.assertEqual(game.state.characters["doctor"].paranoia, 1)
        self.assertEqual(game.state.characters["nurse"].goodwill, 2)
        self.assertFalse(any(c.get("source") == "nurse" for c in game.options("a")))

    def test_optional_and_mandatory_refusals(self):
        for role, expected in (("brain", 2), ("cultist", 1), ("ordinary", 1)):
            with self.subTest(role=role):
                game = make()
                game.roles["worker"] = role
                game.state.characters["worker"].goodwill = 3
                game.state.phase = "goodwill"
                ability(game, "worker", "reveal")
                self.assertEqual(game.state.phase, "refusal")
                self.assertEqual(len(game.options("m")), expected)
                if role != "ordinary":
                    select(game, lambda c: c.get("refuse"))
                    self.assertNotIn("worker", game.known_roles)
                else:
                    accept(game)
                    self.assertIn("worker", game.known_roles)
                self.assertFalse(any(c.get("source") == "worker" for c in game.options("a")))

    def test_nurse_cannot_be_refused_even_as_cultist(self):
        game = make()
        game.roles["nurse"] = "cultist"
        game.state.characters["nurse"].goodwill = 2
        game.state.characters["patient"].paranoia = 2
        game.state.phase = "goodwill"
        ability(game, "nurse", "calm", "patient")
        self.assertEqual(len(game.options("m")), 1)
        accept(game)
        self.assertEqual(game.state.characters["patient"].paranoia, 1)

    def test_doctor_master_use_does_not_leak_usage_or_allow_double_use(self):
        game = make()
        game.state.phase = "master_abilities"
        game.state.characters["doctor"].goodwill = 2
        ability(game, "doctor", "adjust", "patient")
        self.assertEqual(game.state.characters["patient"].paranoia, 1)
        self.assertFalse(game.view()["ability_day_used"])
        game.dispatch("m", "next")
        ability(game, "doctor", "adjust", "patient")
        self.assertTrue(game.options("m")[0].get("refuse"))
        game.dispatch("m", "choose", index=1)
        self.assertEqual(game.state.characters["patient"].paranoia, 1)

    def test_master_abilities_once_per_day_plot_once_per_loop(self):
        game = make()
        game.state.phase = "master_abilities"
        select(game, lambda c: c.get("key") == "brain:doctor" and c["effects"][0]["target"] == "hospital")
        self.assertEqual(game.state.locations["hospital"], 1)
        self.assertFalse(any(c.get("key") == "brain:doctor" for c in game.options("m")))
        select(game, lambda c: c.get("key") == "conspiracy:maiden")
        select(game, lambda c: c.get("key") == "plot:rumor")
        self.assertIn("plot:rumor", game.loop_used)
        game.day_used.clear()
        self.assertTrue(any(c.get("key") == "brain:doctor" for c in game.options("m")))
        self.assertFalse(any(c.get("key") == "plot:rumor" for c in game.options("m")))
        self.assertNotIn("主谋", json.dumps(game.view()["events"], ensure_ascii=False))

    def test_class_rep_returns_current_leaders_limited_card(self):
        game = make()
        game.state.phase = "goodwill"
        game.state.leader = "b"
        game.state.characters["class_rep"].goodwill = 2
        game.state.hands["b"].remove("g2")
        game.state.discarded["b"].append("g2")
        ability(game, "class_rep", "recover")
        accept(game)
        self.assertIn("g2", game.state.hands["b"])
        self.assertFalse(game.state.discarded["b"])
        self.assertIn("goodwill:class_rep:recover", game.public_loop_used)

    def test_outsider_kill_revive_guard_and_counters(self):
        game = make()
        game.state.phase = "goodwill"
        game.state.characters["outsider"].goodwill = 5
        game.state.characters["maiden"].intrigue = 2
        ability(game, "outsider", "kill", "maiden")
        accept(game)
        self.assertFalse(game.state.characters["maiden"].alive)
        ability(game, "outsider", "revive", "maiden")
        accept(game)
        self.assertTrue(game.state.characters["maiden"].alive)
        self.assertEqual(game.state.characters["maiden"].intrigue, 2)

    def test_guard_replaces_one_death(self):
        game = make(kind="suicide", culprit="worker")
        game.state.phase = "goodwill"
        game.state.characters["police"].goodwill = 5
        ability(game, "police", "guard", "worker")
        accept(game)
        self.assertEqual(game.guards["worker"], 1)
        incident(game)
        self.assertTrue(game.state.characters["worker"].alive)
        self.assertEqual(game.guards["worker"], 0)
        incident(game)
        self.assertFalse(game.state.characters["worker"].alive)

    def test_soldier_protection_blocks_death_but_not_other_losses(self):
        game = make(kind="hospital")
        game.state.characters["soldier"].goodwill = 5
        game.state.phase = "goodwill"
        ability(game, "soldier", "protect")
        accept(game)
        game.state.locations["hospital"] = 2
        incident(game)
        self.assertEqual(game.state.phase, "day_end")
        self.assertIsNone(game.winner)
        self.assertFalse(game.state.characters["soldier"].alive)
        self.assertTrue(game.protected)
        game.state.round = game.scenario["days"]
        game.dispatch("m", "next")  # Avenger still loses, even under protection.
        self.assertEqual(game.state.phase, "loop_end")

    def test_police_can_reveal_occurred_ineffective_incident(self):
        game = make(kind="hospital")
        incident(game)
        self.assertFalse(game.incident_records[0]["effective"])
        game.state.phase = "goodwill"
        game.state.characters["police"].goodwill = 4
        ability(game, "police", "culprit")
        accept(game)
        self.assertEqual(game.view()["known_culprits"], {"1": "doctor"})

    def test_informer_excludes_declared_plot_and_does_not_reveal_other_one(self):
        game = make("BTX")
        game.state.phase = "goodwill"
        game.state.characters["informer"].goodwill = 5
        select(game, lambda c: c.get("source") == "informer" and c["effects"][0]["excluded"] == "rumor")
        accept(game)
        self.assertEqual(len(game.options("m")), 1)
        game.dispatch("m", "choose", index=1)
        self.assertEqual(game.known_plots, ["threads"])

    def test_forensic_transfers_guard_and_reveals_remote_corpse(self):
        game = make()
        game.state.phase = "goodwill"
        game.state.characters["forensic"].goodwill = 5
        game.guards["police"] = 1
        ability(game, "forensic", "transfer", "worker")
        accept(game)
        self.assertEqual((game.guards["police"], game.guards["worker"]), (0, 1))
        game.state.characters["doctor"].alive = False
        ability(game, "forensic", "reveal_dead", "doctor")
        accept(game)
        self.assertEqual(game.known_roles["doctor"]["role"], "brain")

    def test_doctor_releases_patient_for_entire_loop(self):
        game = make()
        game.state.phase = "goodwill"
        game.state.characters["doctor"].goodwill = 3
        ability(game, "doctor", "release")
        accept(game)
        self.assertEqual(game.state.characters["patient"].forbidden, ())

    def test_student_teacher_rich_and_maiden_scopes(self):
        game = make()
        game.state.phase = "goodwill"
        for c in game.state.characters.values():
            c.goodwill = 5
        opts = game.options("a")
        self.assertEqual({c["effects"][0]["target"] for c in opts if c.get("source") == "student"},
                         {"girl", "rich", "class_rep"})
        teacher = [c for c in opts if c.get("source") == "teacher" and c.get("ability") == "adjust"]
        self.assertEqual(len(teacher), 8)  # Four students, both signs.
        self.assertFalse(any(c["effects"][0]["target"] == "teacher" for c in teacher))
        ability(game, "rich", "befriend", "rich")
        accept(game)
        self.assertEqual(game.state.characters["rich"].goodwill, 6)
        game.state.characters["rich"].location = "hospital"
        game.public_day_used.clear()
        self.assertFalse(any(c.get("source") == "rich" for c in game.options("a")))
        game.state.locations["shrine"] = 2
        ability(game, "maiden", "purify")
        accept(game)
        self.assertEqual(game.state.locations["shrine"], 1)
        ability(game, "teacher", "reveal", "girl")
        accept(game)
        self.assertEqual(game.known_roles["girl"]["role"], "ordinary")

    def test_idol_and_journalist_powers_and_separate_daily_limits(self):
        game = make()
        game.state.phase = "goodwill"
        game.state.characters["idol"].goodwill = 4
        game.state.characters["journalist"].goodwill = 2
        game.state.characters["worker"].paranoia = 2
        ability(game, "idol", "calm", "worker")
        accept(game)
        self.assertEqual(game.state.characters["worker"].paranoia, 1)
        ability(game, "idol", "befriend", "worker")
        accept(game)
        self.assertEqual(game.state.characters["worker"].goodwill, 1)
        ability(game, "journalist", "alarm", "girl")
        accept(game)
        self.assertEqual(game.state.characters["girl"].paranoia, 1)
        ability(game, "journalist", "intrigue", "city")
        accept(game)
        self.assertEqual(game.state.locations["city"], 1)

    def test_loop_limited_ability_remains_public_on_later_days(self):
        from tragedy_sim.cli import match_board
        game = make()
        game.state.phase = "goodwill"
        game.state.characters["teacher"].goodwill = 4
        ability(game, "teacher", "reveal", "girl")
        accept(game)
        game.dispatch("a", "next")
        game.dispatch("m", "next")
        game.dispatch("m", "next")
        self.assertEqual(game.state.round, 2)
        self.assertFalse(game.public_day_used)
        self.assertIn("goodwill:teacher:reveal", game.view()["ability_loop_used"])
        out = StringIO()
        with redirect_stdout(out):
            match_board(game)
        self.assertIn("本轮已声明能力：教师 / reveal", out.getvalue())


class RoleInteractionTests(unittest.TestCase):
    def test_two_serial_killers_activate_together_and_both_die(self):
        game = make("BTX", subplots=["virus", "threads"])
        for c in game.state.characters.values():
            c.location = "hospital"
        for cid in ("student", "girl"):
            game.state.characters[cid].location = "school"
            game.roles[cid] = "serial"
        game.state.characters["rich"].location = "school"
        game.state.characters["rich"].alive = False
        game.state.phase = "incident"
        game.dispatch("m", "next")
        self.assertEqual(game.state.phase, "day_end")
        self.assertEqual(game.view("m")["phase"], "day_end")
        self.assertEqual(game.view()["phase"], "day_end")
        self.assertEqual(game.view("a")["phase"], "day_end")
        self.assertEqual(game.options("a"), [])
        self.assertNotIn("杀人狂", json.dumps(game.view(), ensure_ascii=False))
        self.assertFalse(game.state.characters["student"].alive)
        self.assertFalse(game.state.characters["girl"].alive)
        self.assertNotIn("杀人狂", json.dumps(game.view(), ensure_ascii=False))

    def test_serial_does_not_kill_if_two_other_living_characters(self):
        game = make()
        game.roles["maiden"] = "serial"
        game.state.characters["student"].location = "shrine"  # Maiden, Outsider, Student.
        game.state.phase = "incident"
        game.dispatch("m", "next")
        self.assertTrue(all(c.alive for c in game.state.characters.values()))

    def test_mandatory_serial_resolves_before_killers_optional_day_end_ability(self):
        game = make("BTX", subplots=["virus", "threads"])
        for character in game.state.characters.values():
            character.location = "hospital"
        game.roles["student"] = "serial"
        game.roles["girl"] = "killer"
        game.state.characters["student"].location = "school"
        game.state.characters["girl"].location = "school"
        game.state.characters["girl"].intrigue = 4
        game.state.phase = "incident"
        game.dispatch("m", "next")
        self.assertFalse(game.state.characters["girl"].alive)
        self.assertTrue(game.state.characters["student"].alive)
        self.assertEqual(game.state.phase, "day_end")
        self.assertFalse(any(choice.get("key") == "killer:heroes:girl"
                             for choice in game.options("m")))
        self.assertFalse(any(event["kind"] == "heroes_died" for event in game.state.events))

    def test_lovers_react_and_lover_can_kill_heroes(self):
        for dead, survivor in (("worker", "doctor"), ("doctor", "worker")):
            game = make("BTX", subplots=["love", "threads"], roles={"girl": "witch", "worker": "loved", "doctor": "lover"},
                        kind="suicide", culprit=dead)
            incident(game)
            self.assertEqual(game.state.characters[survivor].paranoia, 6)
            if survivor == "doctor":
                game.state.characters["doctor"].intrigue = 1
                select(game, lambda c: c.get("key") == "lover:doctor")
                self.assertEqual(game.state.phase, "loop_end")
                self.assertTrue(any(e["kind"] == "heroes_died" for e in game.state.events))

    def test_killer_uses_targets_intrigue_and_factor_is_not_key_identity(self):
        game = Game(example_scenario("BTX"))
        game.scenario["subplots"] = ["unknown", "threads"]
        game.roles["maiden"] = "factor"
        for cid in ("worker", "girl", "maiden"):
            game.state.characters[cid].location = "city"
        game.state.characters["worker"].intrigue = 2
        game.state.characters["maiden"].intrigue = 2
        game.state.locations["city"] = 2
        game.state.phase = "day_end"
        self.assertFalse(any(c.get("key", "").startswith("killer:") for c in game.options("m")))
        game.state.characters["girl"].intrigue = 2
        target(game, "girl", "kill")
        self.assertEqual(game.state.phase, "loop_end")

    def test_factor_gains_and_loses_abilities_not_identity(self):
        for city in (1, 2):
            game = make("BTX", subplots=["unknown", "threads"], roles={"worker": "witch", "doctor": "factor"}, kind="suicide")
            game.state.phase = "master_abilities"
            game.state.locations["school"] = 1
            self.assertFalse(any(c.get("key") == "conspiracy:doctor" for c in game.options("m")))
            game.state.locations["school"] = 2
            self.assertTrue(any(c.get("key") == "conspiracy:doctor" for c in game.options("m")))
            game.state.locations["city"] = city
            incident(game)
            self.assertEqual(game.roles["doctor"], "factor")
            self.assertEqual(game.state.phase, "loop_end" if city == 2 else "day_end")

    def test_time_traveler_immunity_and_optional_final_day_loss(self):
        game = make("BTX", "change", roles={"doctor": "time_traveler", "girl": "cultist", "maiden": "conspiracy"}, kind="suicide")
        incident(game)
        self.assertTrue(game.state.characters["doctor"].alive)
        self.assertFalse(any(c.get("key") == "time_traveler:doctor" for c in game.options("m")))
        game.state.round = 3
        game.protected = True
        game.state.characters["doctor"].goodwill = 3
        self.assertFalse(any(c.get("key") == "time_traveler:doctor" for c in game.options("m")))
        game.state.characters["doctor"].goodwill = 2
        select(game, lambda c: c.get("key") == "time_traveler:doctor")
        self.assertEqual(game.state.phase, "loop_end")
        self.assertFalse(any(e["kind"] == "heroes_died" for e in game.state.events))

    def test_cultist_after_movement_and_time_traveler_ignore_forbids(self):
        game = make("BTX", "change", roles={"doctor": "cultist", "girl": "time_traveler", "maiden": "conspiracy"})
        game.dispatch("m", "next")
        for actor, card, t in (("m", "h", "doctor"), ("m", "i2", "shrine"), ("m", "fg", "girl"),
                               ("a", "fi", "shrine"), ("b", "g2", "girl"), ("c", "g1", "student")):
            game.dispatch(actor, "play", card=card, target=t)
        game.dispatch("m", "resolve")
        self.assertEqual(game.state.characters["doctor"].location, "shrine")
        self.assertTrue(all(p["card"] for p in game.view()["pending"]))
        select(game, lambda c: c.get("key") == "cultist:doctor")
        game.dispatch("m", "next")
        self.assertEqual(game.state.locations["shrine"], 2)
        self.assertEqual(game.state.characters["girl"].goodwill, 2)
        self.assertEqual(game.state.phase, "master_abilities")

    def test_virus_triggers_at_temporary_three_before_paranoia_removed(self):
        game = make("BTX", subplots=["virus", "threads"])
        game.state.characters["student"].paranoia = 2
        game.dispatch("m", "next")
        for actor, card, t in (("m", "p1a", "student"), ("m", "p1b", "city"), ("m", "h", "shrine"),
                               ("a", "p-1", "student"), ("b", "g1", "girl"), ("c", "g1", "doctor")):
            game.dispatch(actor, "play", card=card, target=t)
        game.dispatch("m", "resolve")
        game.dispatch("m", "next")
        self.assertEqual(game.state.characters["student"].paranoia, 2)
        self.assertEqual(game.roles["student"], "serial")
        self.assertFalse(game.known_roles)
        self.assertTrue(any(e.get("target") == "student" and e.get("steps") == [2, 3, 2] for e in game.state.events))


class MatchAndVisibilityTests(unittest.TestCase):
    def test_complete_both_modules_without_fixture_mutations(self):
        for module in ("FS", "BTX"):
            game = Game(example_scenario(module))
            for _ in range(200):
                if game.winner:
                    break
                idle_step(game)
            self.assertEqual(game.winner, "protagonists")
            self.assertEqual(game.state.round, 3)
            self.assertEqual(game.state.leader, "a")
            self.assertEqual(len(game.incident_records), 2)

    def test_bad_commands_rollback_and_cannot_skip_decisions(self):
        game = make(kind="unease")
        incident(game)
        for actor, command, args in (("m", "next", {}), ("a", "choose", {"index": 1}),
                                      ("m", "choose", {"index": 999}), ("m", "choose", {"index": True}),
                                      ("m", "play", {"card": "i1", "target": "doctor"})):
            snapshot = deepcopy(game.__dict__)
            with self.assertRaises(RuleError):
                game.dispatch(actor, command, **args)
            self.assertEqual(snapshot, game.__dict__)
        with self.assertRaises(RuleError):
            game.next_round()
        with self.assertRaises(RuleError):
            game.reset_loop()

    def test_public_projection_no_secret_and_detached(self):
        game = Game(example_scenario())
        public = game.view()
        self.assertNotIn("secret", public)
        self.assertEqual(public["schedule"], [{"day": 2, "kind": "murder"}, {"day": 3, "kind": "suicide"}])
        self.assertEqual(public["characters"]["girl"]["paranoia_limit"], 3)
        self.assertEqual(public["characters"]["doctor"]["traits"], ["成人", "男性"])
        self.assertTrue(public["characters"]["doctor"]["passive"])
        public["characters"]["girl"]["alive"] = False
        public["events"].clear()
        self.assertTrue(game.state.characters["girl"].alive)
        self.assertTrue(game.state.events)
        self.assertEqual(game.view("m")["secret"]["roles"], game.roles)
        game.state.phase = "master_abilities"
        self.assertTrue(game.options("m"))
        self.assertEqual(game.options("a"), [])

    def test_public_views_do_not_disclose_alternative_secret_script(self):
        a = Game(example_scenario())
        s = example_scenario()
        s["cast"]["girl"], s["cast"]["student"] = s["cast"]["student"], s["cast"]["girl"]
        s["incidents"][0]["culprit"] = "student"
        b = Game(s)
        self.assertEqual(a.view(), b.view())
        for game in (a, b):
            game.state.phase = "goodwill"
            game.state.characters["doctor"].goodwill = 3
            ability(game, "doctor", "release")
        self.assertEqual(a.view(), b.view())

    def test_save_resume_mid_reveal_and_no_overwrite(self):
        game = Game(example_scenario())
        for _ in range(8):
            idle_step(game)
        self.assertEqual(game.state.phase, "action_counters")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            game.save(path)
            restored = Game.load(path)
            self.assertEqual(game.view("m"), restored.view("m"))
            self.assertEqual(game.history, restored.history)
            with self.assertRaises(FileExistsError):
                game.save(path)
            while not restored.winner:
                idle_step(restored)
            self.assertEqual(restored.winner, "protagonists")

    def test_invalid_save_format_and_commands_are_rejected(self):
        data = {"version": 1, "scenario": example_scenario(), "commands": []}
        changes = [{"version": True}, {"version": 999}, {"commands": {}},
                   {"commands": [{"actor": "m", "action": "__class__"}]},
                   {"commands": [{"actor": "a", "action": "next"}]},
                   {"commands": [{"actor": "m", "action": "next", "unrecognized": 1}]}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.json"
            for change in changes:
                with self.subTest(change=change):
                    path.write_text(json.dumps({**data, **change}), encoding="utf-8")
                    with self.assertRaises(RuleError):
                        Game.load(path)

    def test_save_resume_necessary_incident_choice_and_goodwill_confirmation(self):
        for stage in ("refusal", "decision"):
            game = make(kind="unease")
            game.dispatch("m", "next")
            for actor, card, t in (("m", "p1a", "doctor"), ("m", "h", "city"), ("m", "p1b", "shrine"),
                                   ("a", "p1", "doctor"), ("b", "g2", "student"), ("c", "g1", "girl")):
                game.dispatch(actor, "play", card=card, target=t)
            game.dispatch("m", "resolve")
            game.dispatch("m", "next")
            game.dispatch("m", "next")
            if stage == "refusal":
                ability(game, "student", "calm", "girl")
            else:
                game.dispatch("a", "next")
                game.dispatch("m", "next")
                target(game, "student")  # Save between the two separate event targets.
            self.assertEqual(game.state.phase, stage)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "pending.json"
                game.save(path)
                loaded = Game.load(path)
                self.assertEqual(game.options("m"), loaded.options("m"))
                self.assertEqual(game.view("m"), loaded.view("m"))
                loaded.dispatch("m", "choose", index=1)
                self.assertEqual(loaded.state.phase, "goodwill" if stage == "refusal" else "day_end")

    def test_seeded_legal_playouts_and_replay(self):
        # Explore combinations without depending on a bot or any random engine rules.
        for seed in range(18):
            rng = random.Random(seed)
            module = "FS" if seed % 2 else "BTX"
            mains = [p for p in MODULE_PLOTS[module] if PLOTS[p][1] == "Y"]
            xs = [p for p in MODULE_PLOTS[module] if PLOTS[p][1] == "X"]
            main = rng.choice(mains)
            chosen = rng.sample(xs, 1 if module == "FS" else 2)
            data = generated_scenario(module, main, chosen)
            allowed = list(MODULES[module].incidents)
            data["incidents"] = [{"day": n, "kind": rng.choice(allowed), "culprit": c}
                                 for n, c in enumerate(rng.sample(list(CHARACTERS), 3), 1)]
            game = Game(data)
            for step in range(600):
                if game.winner:
                    break
                phase, actor = game.state.phase, game.controller
                if phase in ("mastermind", "protagonists"):
                    used = {p.target for p in game.state.pending if (p.actor == "m") == (actor == "m")}
                    targets = [c.id for c in game.state.characters.values() if c.alive] + list(LOCATIONS)
                    game.dispatch(actor, "play", card=rng.choice(game.state.hands[actor]),
                                  target=rng.choice([t for t in targets if t not in used]))
                elif phase == "reveal":
                    game.dispatch(actor, "resolve")
                elif game.options(actor):
                    game.dispatch(actor, "choose", index=rng.randint(1, len(game.options(actor))))
                else:
                    idle_step(game)
                self.assertTrue(all(getattr(c, counter) >= 0 for c in game.state.characters.values()
                                    for counter in ("paranoia", "goodwill", "intrigue")))
                for a in ACTORS:
                    all_cards = game.state.hands[a] + game.state.discarded[a] + [p.card for p in game.state.pending if p.actor == a]
                    self.assertEqual(Counter(all_cards), Counter(list(deck(a))))
            self.assertIsNotNone(game.winner, f"stuck seed={seed}, phase={game.state.phase}")
            replay = Game(data)
            for cmd in game.history:
                cmd = dict(cmd)
                replay.dispatch(cmd.pop("actor"), cmd.pop("action"), **cmd)
            self.assertEqual(game.view("m"), replay.view("m"))


def generated_scenario(module, main, xs):
    needed = Counter()
    for p in [main, *xs]:
        needed.update(PLOTS[p][2])
    for role, cap in (("conspiracy", 1), ("friend", 2)):
        needed[role] = min(needed[role], cap)
    roles = list(needed.elements())
    # A girl is first so Sign With Me gets a valid Key Person.
    cast_order = ["girl", *[c for c in CHARACTERS if c != "girl"]]
    cast = {cid: roles[i] if i < len(roles) else "ordinary" for i, cid in enumerate(cast_order)}
    return {"id": "generated", "title": "组合测试", "module": module, "days": 3, "loops": 2,
            "main_plot": main, "subplots": xs, "cast": cast, "incidents": []}


class ScenarioAndCLITests(unittest.TestCase):
    def test_printed_role_slots_not_similar_english_sets(self):
        self.assertEqual(PLOTS["change"][2], {"cultist": 1, "time_traveler": 1})
        self.assertEqual(PLOTS["lurking"][2], {"friend": 1, "serial": 1})
        self.assertEqual(PLOTS["hideous"][2], {"conspiracy": 1, "friend": 1})
        self.assertEqual(PLOTS["friends"][2], {"friend": 2, "conspiracy": 1})

    def test_all_114_plot_combinations_validate(self):
        total = 0
        for module in ("FS", "BTX"):
            mains = [p for p in MODULE_PLOTS[module] if PLOTS[p][1] == "Y"]
            xs = [p for p in MODULE_PLOTS[module] if PLOTS[p][1] == "X"]
            for main in mains:
                for chosen in combinations(xs, 1 if module == "FS" else 2):
                    validate_scenario(generated_scenario(module, main, list(chosen)))
                    total += 1
        self.assertEqual(total, 114)

    def test_invalid_scripts_fail_closed(self):
        alterations = [{"special_rules": "unsupported"}, {"module": "BT"}, {"days": True}, {"days": 0},
                       {"subplots": ["rumor", "ripper"]}, {"subplots": ["murder_plan"]},
                       {"cast": {"doctor": "key"}}, {"incidents": [{"day": 1, "kind": "butterfly", "culprit": "doctor"}]},
                       {"incidents": [{"day": 1, "kind": "murder", "culprit": "doctor"},
                                      {"day": 2, "kind": "suicide", "culprit": "doctor"}]}]
        for change in alterations:
            with self.subTest(change=change), self.assertRaises(RuleError):
                validate_scenario({**example_scenario(), **change})

    def test_example_json_files_match_builtins(self):
        from tragedy_sim.scenario import load_scenario
        root = Path(__file__).resolve().parents[1]
        for module in ("FS", "BTX"):
            self.assertEqual(load_scenario(root / "examples" / f"{module.lower()}-tutorial.json"), example_scenario(module))

    def test_demo_reaches_second_loop_after_actual_incident(self):
        for module in ("FS", "BTX"):
            result = subprocess.run([sys.executable, "-m", "tragedy_sim", "--module", module, "--demo"],
                                    capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            for expected in ("「谋杀」：发生", "第 1 轮回失败", "第 2 轮回开始", "胜方：主人公"):
                self.assertIn(expected, result.stdout)

    def test_cli_public_output_rules_errors_and_quoted_save_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "my session.json"
            commands = f'rules\ninspect doctor\nnext\nplay b g1 doctor\nnext\nboard\nsave "{path}"\nquit\n'
            result = subprocess.run([sys.executable, "-m", "tragedy_sim", "--module", "BTX"],
                                    input=commands, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("无法执行", result.stdout)
            self.assertIn("被动特性", result.stdout)
            self.assertIn("事件日程", result.stdout)
            self.assertIn("不披露剧本选择", result.stdout)
            self.assertNotIn("规则 Y：谋杀计划", result.stdout)
            self.assertTrue(path.exists())
            loaded = Game.load(path)
            self.assertEqual(loaded.state.phase, "mastermind")

    def test_readme_first_day_transcript_runs_as_documented(self):
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        commands = "\n".join(re.findall(r"```text\n(.*?)```", readme, re.DOTALL)) + "\nboard\nquit\n"
        result = subprocess.run([sys.executable, "-m", "tragedy_sim"], input=commands,
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("无法执行", result.stdout)
        self.assertIn("住院患者：不安 0 → 1", result.stdout)
        self.assertIn("第 2/3 天 · 日初", result.stdout)


if __name__ == "__main__":
    unittest.main()
