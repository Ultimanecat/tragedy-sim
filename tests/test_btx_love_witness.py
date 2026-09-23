"""Romance death evidence must stay hard only when attribution is unique."""

from copy import deepcopy
from dataclasses import replace
import unittest

from tragedy_sim import Game
from tragedy_sim.belief import (FactorizedBeliefState, HiddenWorldHypothesis,
                                PublicEvidence)
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.witness import FsbtxWitnessCompiler, FsbtxWitnessMatcher


SOURCE = "public_love_death_reaction"


class BtxLoveWitnessTests(unittest.TestCase):
    def setUp(self):
        self.game = Game(ScenarioLibrary().get(
            "official-btx-01-machina-solar-cogwheel"))

    def test_real_death_reveals_subplot_and_both_partner_roles(self):
        self.game._kill(["informer"])
        view = self.game.protagonist_team_view()
        evidence = [item for item in FsbtxWitnessCompiler().compile(view)
                    if item.source == SOURCE]
        self.assertEqual({(item.kind, item.subject) for item in evidence}, {
            ("plot_present", "love"), ("role_in", "informer"),
            ("role_in", "scholar")})
        truth = HiddenWorldHypothesis.from_scenario(self.game.scenario)
        self.assertTrue(FsbtxWitnessMatcher().matches(truth, evidence))
        no_love = replace(truth, subplots=("friends", "virus"))
        self.assertFalse(FsbtxWitnessMatcher().matches(no_love, evidence))
        self.assertFalse(any(item.source == SOURCE for item in
                             FsbtxWitnessCompiler(
                                 disabled_sources={SOURCE}).compile(view)))

    def test_multi_death_identifies_recipient_not_a_specific_victim(self):
        self.game._kill(["informer", "patient"])
        evidence = [item for item in FsbtxWitnessCompiler().compile(
            self.game.protagonist_team_view()) if item.source == SOURCE]
        self.assertEqual({(item.kind, item.subject) for item in evidence}, {
            ("plot_present", "love"), ("role_in", "scholar")})

    def test_positive_reaction_shrinks_exact_guess_space(self):
        self.game._kill(["informer"])
        view = self.game.protagonist_team_view()
        evidence = PublicEvidence.from_view(view)
        enabled = FsbtxWitnessCompiler().compile(view)
        ablated = FsbtxWitnessCompiler(
            disabled_sources={SOURCE}).compile(view)
        solver = FactorizedBeliefState(capacity=1, seed=1)
        yes = solver.exact_role_map(evidence, enabled)
        no = solver.exact_role_map(evidence, ablated)
        self.assertTrue(yes.ranked)
        self.assertLess(yes.compatible_count, no.compatible_count)

    def test_old_or_unrelated_logs_do_not_forge_pair(self):
        view = deepcopy(self.game.protagonist_team_view())
        view["events"] = [
            {"kind": "character_died", "loop": 1, "round": 2,
             "target": "informer"},
            {"kind": "counter_changed", "loop": 1, "round": 2,
             "counter": "paranoia", "target": "scholar",
             "before": 0, "after": 5},
        ]
        self.assertFalse(any(item.source == SOURCE for item in
                             FsbtxWitnessCompiler().compile(view)))
        view["events"][1]["after"] = 6
        view["events"].insert(1, {"kind": "incident_ended", "loop": 1,
                                  "round": 2})
        self.assertFalse(any(item.source == SOURCE for item in
                             FsbtxWitnessCompiler().compile(view)))
        view["module"] = "FS"
        self.assertFalse(any(item.source == SOURCE for item in
                             FsbtxWitnessCompiler().compile(view)))


if __name__ == "__main__":
    unittest.main()
