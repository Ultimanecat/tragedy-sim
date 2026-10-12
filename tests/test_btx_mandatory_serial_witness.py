"""A completed mandatory day-end window can identify serial-killer routes."""

from copy import deepcopy
from dataclasses import replace
import unittest

from tragedy_sim import Game
from tragedy_sim.belief import (FactorizedBeliefState, HiddenWorldHypothesis,
                                PublicEvidence)
from tragedy_sim.scenario import example_scenario
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.effects.movement import move
from tragedy_sim.witness import FsbtxWitnessCompiler, FsbtxWitnessMatcher


SOURCE = "public_btx_mandatory_serial_route"
ABSENCE_SOURCE = "public_btx_mandatory_serial_absence"
TERMINAL_SOURCE = "public_btx_terminal_mandatory_serial_route"


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
    @staticmethod
    def terminal_view(*, virus=False):
        setup = ScenarioLibrary().get("official-tragic-aiplay-btx-01g")
        if virus:
            setup["subplots"] = ["virus", "rumor"]
            setup["cast"]["student"] = "ordinary"
            setup["cast"]["maiden"] = "ordinary"
        game = Game(setup)
        move(game, {"target": "student", "location": "city"})
        if virus:
            game._change("student", "paranoia", 3)
        game._begin_night()
        return game, game.protagonist_team_view()

    def test_terminal_mandatory_death_keeps_serial_evidence_without_marker(self):
        from tragedy_sim.belief_matrix import BeliefMatrixProjection, HardStatus
        game, view = self.terminal_view()
        self.assertFalse(any(e["kind"] == "mandatory_window_resolved" for e in view["events"]))
        self.assertTrue(any(e["kind"] == "loop_lost" for e in view["events"]))
        clues = FsbtxWitnessCompiler().compile(view)
        routes = [w for w in clues if w.source == TERMINAL_SOURCE]
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].subject, "idol")
        self.assertEqual(routes[0].value, {"serial": ("student",), "virus_ordinary": ()})
        truth = HiddenWorldHypothesis.from_scenario(game.scenario)
        self.assertTrue(FsbtxWitnessMatcher().matches(truth, clues))
        wrong = replace(truth, roles=tuple(sorted({**dict(truth.roles), "student": "ordinary"}.items())))
        self.assertFalse(FsbtxWitnessMatcher().matches(wrong, routes))
        matrix = BeliefMatrixProjection.from_view(view, clues)
        self.assertEqual(matrix.roles["student"]["serial"].hard_status, HardStatus.ALWAYS)
        self.assertFalse(any(w.source == TERMINAL_SOURCE for w in
                             FsbtxWitnessCompiler(disabled_sources={TERMINAL_SOURCE}).compile(view)))

    def test_terminal_old_or_optional_phase_journal_is_not_attributed(self):
        _, view = self.terminal_view()
        for kind, phase in (("character_died", None), ("loop_lost", None),
                            ("character_died", "decision"), ("loop_lost", "decision")):
            altered = deepcopy(view)
            for event in altered["events"]:
                if event["kind"] == kind:
                    event["phase"] = phase
            self.assertFalse(any(w.source == TERMINAL_SOURCE for w in
                                 FsbtxWitnessCompiler().compile(altered)))
        altered = deepcopy(view)
        death = next(i for i, e in enumerate(altered["events"]) if e["kind"] == "character_died")
        altered["events"].insert(death, {"kind": "mandatory_window_resolved", "loop": 1,
                                         "round": 1, "timing": "day_end", "phase": "day_end"})
        self.assertFalse(any(w.source == TERMINAL_SOURCE for w in
                             FsbtxWitnessCompiler().compile(altered)))

    def test_terminal_replacement_preserves_ambiguity(self):
        _, view = self.terminal_view()
        death = next(i for i, e in enumerate(view["events"]) if e["kind"] == "character_died")
        view["events"].insert(death, {"kind": "death_replaced", "loop": 1, "round": 1,
                                      "timing": "day_end", "phase": "day_end"})
        self.assertFalse(any(w.source == TERMINAL_SOURCE for w in
                             FsbtxWitnessCompiler().compile(view)))

    def test_terminal_virus_keeps_ordinary_alternative(self):
        game, view = self.terminal_view(virus=True)
        route = next(w for w in FsbtxWitnessCompiler().compile(view) if w.source == TERMINAL_SOURCE)
        self.assertEqual(route.value["virus_ordinary"], ("student",))
        self.assertTrue(FsbtxWitnessMatcher().matches(
            HiddenWorldHypothesis.from_scenario(game.scenario), (route,)))

    def test_empty_mandatory_batch_excludes_serial_before_optional_kill(self):
        game = Game(ScenarioLibrary().get("official-btx-10-prologue"))
        move(game, {"target": "rich", "location": "shrine"})
        game._change("maiden", "intrigue", 2)
        game._begin_night()
        view = game.protagonist_team_view()
        clues = [w for w in FsbtxWitnessCompiler().compile(view)
                 if w.source == ABSENCE_SOURCE]
        self.assertIn("rich", [w.subject for w in clues])
        truth = HiddenWorldHypothesis.from_scenario(game.scenario)
        self.assertTrue(FsbtxWitnessMatcher().matches(truth, clues))
        wrong = replace(truth, roles=tuple(sorted({
            **dict(truth.roles), "rich": "serial"}.items())))
        self.assertFalse(FsbtxWitnessMatcher().matches(wrong, clues))
        option = next(i for i, choice in enumerate(game.options("m"), 1)
                      if choice.get("key") == "killer:character:rich")
        game.dispatch("m", "choose", index=option)
        self.assertFalse(game.state.characters["maiden"].alive)
        self.assertIn("rich", [w.subject for w in
                               FsbtxWitnessCompiler().compile(
                                   game.protagonist_team_view())
                               if w.source == ABSENCE_SOURCE])
        self.assertFalse(any(w.source == ABSENCE_SOURCE for w in
                             FsbtxWitnessCompiler(
                                 disabled_sources={ABSENCE_SOURCE}).compile(view)))
        old = deepcopy(view)
        old["events"] = [e for e in old["events"]
                         if e["kind"] != "mandatory_window_resolved"]
        self.assertFalse(any(w.source == ABSENCE_SOURCE for w in
                             FsbtxWitnessCompiler().compile(old)))

    def test_guarded_serial_attack_is_not_absence(self):
        game = Game(scenario())
        game.guards["girl"] = 1
        game._begin_night()
        self.assertFalse(any(w.source == ABSENCE_SOURCE for w in
                             FsbtxWitnessCompiler().compile(
                                 game.protagonist_team_view())))

    def test_immune_victim_still_counts_as_attempted_death(self):
        game = Game(scenario())
        move(game, {"target": "girl", "location": "hospital"})
        move(game, {"target": "doctor", "location": "school"})
        game._begin_night()
        view = game.protagonist_team_view()
        self.assertTrue(any(e["kind"] == "death_prevented" for e in view["events"]))
        self.assertFalse(any(w.source == ABSENCE_SOURCE for w in
                             FsbtxWitnessCompiler().compile(view)))

    def test_three_occupants_do_not_exclude_serial(self):
        game = Game(ScenarioLibrary().get("official-btx-10-prologue"))
        move(game, {"target": "rich", "location": "shrine"})
        move(game, {"target": "student", "location": "shrine"})
        game._begin_night()
        self.assertNotIn("rich", [w.subject for w in
                                  FsbtxWitnessCompiler().compile(
                                      game.protagonist_team_view())
                                  if w.source == ABSENCE_SOURCE])

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
