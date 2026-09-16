"""FS/BTX hard-witness regression tests."""

from copy import deepcopy
import random
import unittest

from tragedy_sim import Game
from tragedy_sim.belief import (ConstraintBeliefSampler, HiddenWorldHypothesis,
                                PublicEvidence)
from tragedy_sim.scenario import example_scenario
from tragedy_sim.witness import (FsbtxWitnessCompiler, FsbtxWitnessMatcher,
                                 WitnessVerdict)


class FsbtxWitnessTests(unittest.TestCase):
    def setUp(self):
        self.game = Game(example_scenario("BTX"))
        self.view = self.game.view("a")
        self.hypothesis = HiddenWorldHypothesis.from_scenario(self.game.scenario)

    def test_explicit_reveals_are_hard_constraints(self):
        view = deepcopy(self.view)
        role = dict(self.hypothesis.roles)["girl"]
        culprit = next(item[3] for item in self.hypothesis.incidents
                       if item[0] == 2)
        view["known_roles"] = {"girl": {"role": role}}
        view["known_culprits"] = {"2": culprit}
        view["known_plots"] = [self.hypothesis.main_plot]
        witnesses = FsbtxWitnessCompiler().compile(view)
        evaluation = FsbtxWitnessMatcher().evaluate(self.hypothesis, witnesses)
        self.assertTrue(evaluation.compatible)
        self.assertTrue(all(verdict == WitnessVerdict.SATISFIED
                            for _, verdict in evaluation.verdicts))

        wrong = deepcopy(view)
        wrong["known_roles"] = {"girl": {"role": "ordinary"}}
        self.assertFalse(FsbtxWitnessMatcher().matches(
            self.hypothesis, FsbtxWitnessCompiler().compile(wrong)))

    def test_happened_incident_rejects_below_threshold_culprit(self):
        view = deepcopy(self.view)
        view["round"] = 2
        view["timing"] = "incident"
        view["incidents"] = [{"day": 2, "kind": "murder",
                              "happened": True, "effective": False}]
        witnesses = FsbtxWitnessCompiler().compile(view)
        incident = next(item for item in witnesses
                        if item.kind == "incident_happened")
        self.assertEqual(FsbtxWitnessMatcher().verdict(
            self.hypothesis, incident), WitnessVerdict.CONTRADICTED)

        culprit = next(item[3] for item in self.hypothesis.incidents
                       if item[0] == 2)
        view["characters"][culprit]["paranoia"] = \
            view["characters"][culprit]["paranoia_limit"]
        incident = next(item for item in FsbtxWitnessCompiler().compile(view)
                        if item.kind == "incident_happened")
        self.assertEqual(FsbtxWitnessMatcher().verdict(
            self.hypothesis, incident), WitnessVerdict.SATISFIED)

    def test_nonoccurrence_is_not_an_unsafe_negative_identity_inference(self):
        view = deepcopy(self.view)
        view["round"] = 2
        view["incidents"] = [{"day": 2, "kind": "murder",
                              "happened": False, "effective": False}]
        witness = next(item for item in FsbtxWitnessCompiler().compile(view)
                       if item.kind == "incident_not_happened")
        self.assertEqual(FsbtxWitnessMatcher().verdict(
            self.hypothesis, witness), WitnessVerdict.UNKNOWN)
        self.assertTrue(FsbtxWitnessMatcher().matches(self.hypothesis, (witness,)))

    def test_part_timer_replacement_uses_visible_replacement_threshold(self):
        scenario = example_scenario("BTX")
        scenario["cast"].pop(next(iter(scenario["cast"])))
        scenario["cast"]["part_timer"] = "ordinary"
        scenario["incidents"][0]["culprit"] = "part_timer"
        hypothesis = HiddenWorldHypothesis.from_scenario(scenario)
        view = deepcopy(self.view)
        view["round"] = scenario["incidents"][0]["day"]
        view["incidents"] = [{"day": view["round"], "kind": "murder",
                              "happened": True, "effective": False}]
        view["characters"]["part_timer_question"] = {
            "paranoia": 3, "goodwill": 0, "intrigue": 0, "guard": 0,
            "present": True, "alive": True,
        }
        witness = next(item for item in FsbtxWitnessCompiler().compile(view)
                       if item.kind == "incident_happened")
        self.assertEqual(FsbtxWitnessMatcher().verdict(hypothesis, witness),
                         WitnessVerdict.SATISFIED)

    def test_constraint_sampler_applies_witnesses_without_catalog_lookup(self):
        view = deepcopy(self.view)
        view["known_roles"] = {"girl": {"role": "key"}}
        evidence = PublicEvidence.from_view(view)
        witnesses = FsbtxWitnessCompiler().compile(view)
        worlds = ConstraintBeliefSampler().sample(
            evidence, 5, rng=random.Random(44), witnesses=witnesses)
        self.assertEqual(len(worlds), 5)
        self.assertTrue(all(dict(world.roles)["girl"] == "key"
                            for world in worlds))

    def test_other_rulesets_compile_no_fs_btx_assumptions(self):
        self.view["module"] = "MZ"
        self.assertEqual(FsbtxWitnessCompiler().compile(self.view), ())


if __name__ == "__main__":
    unittest.main()
