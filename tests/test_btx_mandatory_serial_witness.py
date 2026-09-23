"""A completed mandatory day-end window can identify serial-killer routes."""

from copy import deepcopy
from dataclasses import replace
import unittest

from tragedy_sim import Game
from tragedy_sim.belief import (FactorizedBeliefState, HiddenWorldHypothesis,
                                PublicEvidence)
from tragedy_sim.scenario import example_scenario
from tragedy_sim.witness import FsbtxWitnessCompiler, FsbtxWitnessMatcher


SOURCE = "public_btx_mandatory_serial_route"


def scenario(*, virus=False):
    result = example_scenario("BTX")
    result["main_plot"] = "change"
    result["subplots"] = ["virus" if virus else "lurking", "threads"]
    result["cast"] = {
        "student": "ordinary" if virus else "serial",
        "girl": "ordinary" if virus else "friend",
        "doctor": "time_traveler", "worker": "conspiracy" if virus else "ordinary",
        "maiden": "cultist", "patient": "ordinary"}
    return result


class BtxMandatorySerialWitnessTests(unittest.TestCase):
    def test_real_serial_death_and_ablated_source(self):
        game = Game(scenario())
        game._begin_night()
        view = game.protagonist_team_view()
        self.assertTrue(any(e["kind"] == "mandatory_window_resolved"
                            for e in view["events"]))
        clues = [w for w in FsbtxWitnessCompiler().compile(view)
                 if w.source == SOURCE]
        self.assertEqual(len(clues), 1)
        self.assertEqual(clues[0].subject, "girl")
        self.assertEqual(clues[0].value,
                         {"serial": ("student",), "virus_ordinary": ()})
        truth = HiddenWorldHypothesis.from_scenario(game.scenario)
        self.assertTrue(FsbtxWitnessMatcher().matches(truth, clues))
        no_serial = replace(truth, roles=tuple(sorted({
            **dict(truth.roles), "student": "ordinary"}.items())))
        self.assertFalse(FsbtxWitnessMatcher().matches(no_serial, clues))
        self.assertFalse(any(w.source == SOURCE for w in
                             FsbtxWitnessCompiler(
                                 disabled_sources={SOURCE}).compile(view)))

    def test_virus_converted_ordinary_remains_a_hard_alternative(self):
        game = Game(scenario(virus=True))
        game._change("student", "paranoia", 3)
        game._begin_night()
        view = game.protagonist_team_view()
        clue = next(w for w in FsbtxWitnessCompiler().compile(view)
                    if w.source == SOURCE)
        self.assertEqual(clue.value["virus_ordinary"], ("student",))
        truth = HiddenWorldHypothesis.from_scenario(game.scenario)
        self.assertTrue(FsbtxWitnessMatcher().matches(truth, (clue,)))
        self.assertFalse(FsbtxWitnessMatcher().matches(
            replace(truth, subplots=("lurking", "threads")), (clue,)))
        solved = FactorizedBeliefState(capacity=1, seed=1).exact_role_map(
            PublicEvidence.from_view(view), FsbtxWitnessCompiler().compile(view))
        self.assertTrue(solved.ranked)

    def test_guard_spent_identifies_attack_without_death(self):
        game = Game(scenario())
        game.guards["girl"] = 1
        game._begin_night()
        view = game.protagonist_team_view()
        self.assertTrue(game.state.characters["girl"].alive)
        self.assertTrue(any(e["kind"] == "guard_spent" for e in view["events"]))
        self.assertEqual([w.subject for w in FsbtxWitnessCompiler().compile(view)
                          if w.source == SOURCE], ["girl"])

    def test_optional_killer_and_old_journal_are_not_attributed(self):
        game = Game(example_scenario("BTX"))
        game.state.characters["worker"].location = "school"
        game.state.characters["girl"].intrigue = 2
        game._begin_night()
        self.assertFalse(any(w.source == SOURCE for w in
                             FsbtxWitnessCompiler().compile(
                                 game.protagonist_team_view())))
        option = next(i for i, choice in enumerate(game.options("m"), 1)
                      if choice.get("key") == "killer:character:worker")
        game.dispatch("m", "choose", index=option)
        self.assertFalse(any(w.source == SOURCE for w in
                             FsbtxWitnessCompiler().compile(
                                 game.protagonist_team_view())))
        view = deepcopy(Game(scenario()).protagonist_team_view())
        view["events"] = [
            {"kind": "loop_started", "loop": 1, "round": 1},
            {"kind": "phase_changed", "loop": 1, "round": 1,
             "timing": "day_end"},
            {"kind": "character_died", "loop": 1, "round": 1,
             "timing": "day_end", "target": "girl"},
        ]
        self.assertFalse(any(w.source == SOURCE for w in
                             FsbtxWitnessCompiler().compile(view)))

    def test_replacement_is_ambiguous_and_later_batches_are_ignored(self):
        view = deepcopy(Game(scenario()).protagonist_team_view())
        events = [
            {"kind": "loop_started", "loop": 1, "round": 1},
            {"kind": "phase_changed", "loop": 1, "round": 1,
             "timing": "day_end"},
            {"kind": "character_died", "loop": 1, "round": 1,
             "timing": "day_end", "target": "girl"},
            {"kind": "character_died", "loop": 1, "round": 1,
             "timing": "day_end", "target": "patient"},
            {"kind": "mandatory_window_resolved", "loop": 1, "round": 1,
             "timing": "day_end"},
        ]
        view["events"] = events
        self.assertEqual([w.subject for w in FsbtxWitnessCompiler().compile(view)
                          if w.source == SOURCE], ["girl"])
        events.insert(2, {"kind": "death_replaced", "loop": 1, "round": 1,
                          "timing": "day_end", "protected": ["girl"]})
        self.assertFalse(any(w.source == SOURCE for w in
                             FsbtxWitnessCompiler().compile(view)))


if __name__ == "__main__":
    unittest.main()
