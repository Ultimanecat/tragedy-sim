"""Mastermind-phase counters reveal only a disjunction of legal sources."""

from copy import deepcopy
from dataclasses import replace
import unittest

from tragedy_sim import Game
from tragedy_sim.belief import (FactorizedBeliefState, HiddenWorldHypothesis,
                                PublicEvidence)
from tragedy_sim.scenario import example_scenario
from tragedy_sim.witness import FsbtxWitnessCompiler, FsbtxWitnessMatcher


class MastermindAbilityWitnessTests(unittest.TestCase):
    @staticmethod
    def choose(game, key, target):
        index = next(i for i, option in enumerate(game.options("m"), 1)
                     if option.get("key") == key
                     and option.get("effects")
                     and option["effects"][0].get("target") == target)
        game.dispatch("m", "choose", index=index)

    def test_character_intrigue_requires_a_brain_source(self):
        game = Game(example_scenario("FS"))
        game.state.phase = "master_abilities"
        self.choose(game, "brain:doctor", "patient")
        view = game.protagonist_team_view()
        source = "public_mastermind_intrigue_source"
        clues = [w for w in FsbtxWitnessCompiler().compile(view)
                 if w.source == source]
        self.assertEqual(len(clues), 1)
        self.assertEqual(clues[0].value["roles"],
                         {"brain": ("doctor", "patient")})
        truth = HiddenWorldHypothesis.from_scenario(game.scenario)
        self.assertTrue(FsbtxWitnessMatcher().matches(truth, clues))
        swapped = replace(truth, roles=tuple(sorted({
            **dict(truth.roles), "doctor": "ordinary", "worker": "brain"
        }.items())))
        self.assertFalse(FsbtxWitnessMatcher().matches(swapped, clues))
        self.assertFalse(any(w.source == source for w in
                             FsbtxWitnessCompiler(
                                 disabled_sources={source}).compile(view)))

    def test_board_intrigue_keeps_rumor_as_an_alternative(self):
        game = Game(example_scenario("FS"))
        game.state.phase = "master_abilities"
        self.choose(game, "plot:rumor", "school")
        clue = next(w for w in FsbtxWitnessCompiler().compile(
            game.protagonist_team_view())
            if w.source == "public_mastermind_intrigue_source")
        truth = HiddenWorldHypothesis.from_scenario(game.scenario)
        no_brain = replace(truth, roles=tuple(sorted({
            **dict(truth.roles), "doctor": "ordinary"
        }.items())))
        matcher = FsbtxWitnessMatcher()
        self.assertTrue(matcher.matches(no_brain, (clue,)))
        self.assertFalse(matcher.matches(
            replace(no_brain, subplots=()), (clue,)))

    def test_paranoia_preserves_doctor_and_factor_alternatives(self):
        game = Game(example_scenario("BTX"))
        game.state.phase = "master_abilities"
        game.state.characters["doctor"].goodwill = 2
        self.choose(game, "goodwill:doctor:adjust", "patient")
        view = game.protagonist_team_view()
        source = "public_mastermind_paranoia_source"
        clue = next(w for w in FsbtxWitnessCompiler().compile(view)
                    if w.source == source)
        self.assertIn("doctor", clue.value["roles"]["brain"])
        self.assertIn("factor", clue.value["roles"])
        truth = HiddenWorldHypothesis.from_scenario(game.scenario)
        self.assertTrue(FsbtxWitnessMatcher().matches(truth, (clue,)))
        self.assertFalse(any(w.source == source for w in
                             FsbtxWitnessCompiler(
                                 disabled_sources={source}).compile(view)))

    def test_exact_guess_solver_constructs_hard_route(self):
        game = Game(example_scenario("FS"))
        game.state.phase = "master_abilities"
        self.choose(game, "conspiracy:maiden", "maiden")
        view = game.protagonist_team_view()
        witnesses = FsbtxWitnessCompiler().compile(view)
        ablated = FsbtxWitnessCompiler(disabled_sources={
            "public_mastermind_paranoia_source"}).compile(view)
        solved = FactorizedBeliefState(capacity=1, seed=1).exact_role_map(
            PublicEvidence.from_view(view), witnesses)
        without = FactorizedBeliefState(capacity=1, seed=1).exact_role_map(
            PublicEvidence.from_view(view), ablated)
        self.assertTrue(solved.ranked)
        self.assertTrue(all(dict(world.roles)["maiden"] == "conspiracy"
                            for world, _ in solved.ranked))
        self.assertTrue(any(dict(world.roles)["maiden"] != "conspiracy"
                            for world, _ in without.ranked))

    def test_btx_factor_copy_preserves_the_real_world(self):
        scenario = example_scenario("BTX")
        scenario["main_plot"] = "change"
        scenario["subplots"] = ["unknown", "threads"]
        scenario["cast"] = {
            "student": "ordinary", "girl": "ordinary", "doctor": "factor",
            "worker": "time_traveler", "maiden": "cultist",
            "patient": "ordinary"}
        game = Game(scenario)
        game.state.phase = "master_abilities"
        game.state.locations["school"] = 2
        self.choose(game, "conspiracy:doctor", "patient")
        clues = [w for w in FsbtxWitnessCompiler().compile(
            game.protagonist_team_view())
            if w.source == "public_mastermind_paranoia_source"]
        self.assertEqual(len(clues), 1)
        self.assertIn("doctor", clues[0].value["roles"]["factor"])
        self.assertTrue(FsbtxWitnessMatcher().matches(
            HiddenWorldHypothesis.from_scenario(game.scenario), clues))

    def test_incomplete_or_ambiguous_logs_are_skipped(self):
        view = deepcopy(Game(example_scenario("FS")).protagonist_team_view())
        view["events"] = [{"kind": "counter_changed", "loop": 1,
                           "round": 1, "timing": "mastermind_ability",
                           "target": "patient", "counter": "intrigue",
                           "before": 0, "after": 1}]
        self.assertFalse(any("mastermind_" in w.source for w in
                             FsbtxWitnessCompiler().compile(view)))
        view["events"].insert(0, {"kind": "loop_started", "loop": 1})
        view["characters"]["sacred_tree"] = {}
        self.assertFalse(any("mastermind_" in w.source for w in
                             FsbtxWitnessCompiler().compile(view)))

    def test_public_movement_changes_the_candidate_area(self):
        game = Game(example_scenario("FS"))
        game.state.characters["doctor"].location = "city"
        game._event("character_moved", "", character="doctor",
                    location="city", timing="action_resolution")
        game.state.phase = "master_abilities"
        self.choose(game, "brain:doctor", "worker")
        clue = next(w for w in FsbtxWitnessCompiler().compile(
            game.protagonist_team_view())
            if w.source == "public_mastermind_intrigue_source")
        self.assertIn("doctor", clue.value["roles"]["brain"])
        self.assertNotIn("patient", clue.value["roles"]["brain"])


if __name__ == "__main__":
    unittest.main()
