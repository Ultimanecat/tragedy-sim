"""FS/BTX hard-witness regression tests."""

from copy import deepcopy
from dataclasses import replace
import random
import unittest

from tragedy_sim import Game
from tragedy_sim.belief import (ConstraintBeliefSampler, HiddenWorldHypothesis,
                                PublicEvidence)
from tragedy_sim.scenario import example_scenario
from tragedy_sim.witness import (FsbtxWitnessCompiler, FsbtxWitnessMatcher,
                                 PublicEvidenceLedger,
                                 WitnessStrength, WitnessVerdict)


class FsbtxWitnessTests(unittest.TestCase):
    def setUp(self):
        self.game = Game(example_scenario("BTX"))
        self.view = self.game.view("a")
        self.hypothesis = HiddenWorldHypothesis.from_scenario(self.game.scenario)

    def test_evidence_ledger_is_a_separate_idempotent_dimension(self):
        ledger = PublicEvidenceLedger()
        compiler = FsbtxWitnessCompiler()
        first = ledger.update(self.view, compiler)
        self.assertEqual(first, ledger.witnesses)
        self.assertEqual(ledger.updates, 1)
        ledger.update(self.view, compiler)
        self.assertEqual(ledger.updates, 1)

        changed = deepcopy(self.view)
        changed["known_roles"] = {"girl": {"role": "key"}}
        ledger.update(changed, compiler)
        self.assertEqual(ledger.updates, 2)
        self.assertEqual(ledger.hard_count, 1)

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

    def test_immediate_fs_death_loss_certifies_key_but_normal_end_does_not(self):
        view = Game(example_scenario("FS")).view("a")
        events = [
            {"kind": "character_died", "loop": 1, "round": 1,
             "timing": "day_end", "target": "girl"},
            {"kind": "loop_lost", "loop": 1, "round": 1,
             "timing": "loop_end"},
        ]
        view["events"] = events
        hard = [item for item in FsbtxWitnessCompiler().compile(view)
                if item.source == "immediate_fs_death_loss"]
        self.assertEqual([(item.kind, item.subject, item.value)
                          for item in hard], [("role_is", "girl", "key")])
        ordinary = replace(HiddenWorldHypothesis.from_scenario(
            Game(example_scenario("FS")).scenario),
            roles=(("girl", "ordinary"),))
        self.assertFalse(FsbtxWitnessMatcher().matches(ordinary, hard))

        view["events"] = [events[0],
                          {"kind": "incident_ended", "loop": 1, "round": 1},
                          events[1]]
        self.assertEqual(
            [item.subject for item in FsbtxWitnessCompiler().compile(view)
             if item.source == "immediate_fs_death_loss"], ["girl"])

        view["events"] = [events[0],
                          {"kind": "day_ended", "loop": 1, "round": 1},
                          events[1]]
        self.assertFalse(any(item.source == "immediate_fs_death_loss"
                             for item in FsbtxWitnessCompiler().compile(view)))
        view["module"] = "BTX"
        view["events"] = events
        self.assertFalse(any(item.source == "immediate_fs_death_loss"
                             for item in FsbtxWitnessCompiler().compile(view)))

    def test_fs_lone_day_end_death_certifies_serial_when_intrigue_is_low(self):
        view = Game(example_scenario("FS")).view("a")
        view["events"] = [
            {"kind": "loop_started", "loop": 1, "round": 1},
            {"kind": "character_moved", "loop": 1, "round": 1,
             "character": "student",
             "location": view["characters"]["girl"]["initial_location"]},
            {"kind": "character_died", "loop": 1, "round": 1,
             "timing": "day_end", "target": "girl"},
        ]
        serial = [item for item in FsbtxWitnessCompiler().compile(view)
                  if item.source == "fs_lone_companion_death"]
        self.assertEqual([(item.subject, item.value) for item in serial],
                         [("student", "serial")])
        view["events"].insert(2, {
            "kind": "counter_changed", "loop": 1, "round": 1,
            "target": "girl", "counter": "intrigue", "after": 2})
        self.assertFalse(any(item.source == "fs_lone_companion_death"
                             for item in FsbtxWitnessCompiler().compile(view)))

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

    def test_repeated_day_end_death_is_soft_role_evidence(self):
        view = deepcopy(self.view)
        view["events"] = []
        for loop in (1, 2, 3):
            view["events"].extend([
                {"kind": "loop_started", "loop": loop, "round": 1,
                 "timing": "loop_start"},
                {"kind": "character_moved", "loop": loop, "round": 1,
                 "timing": "action_resolution", "character": "student",
                 "location": view["characters"]["girl"]["initial_location"]},
                {"kind": "character_died", "loop": loop, "round": 1,
                 "timing": "day_end", "target": "girl"},
                {"kind": "loop_lost", "loop": loop, "round": 1,
                 "timing": "loop_end"},
            ])
        witnesses = FsbtxWitnessCompiler().compile(view)
        soft = [item for item in witnesses
                if item.strength == WitnessStrength.SOFT]
        self.assertTrue(soft)
        self.assertTrue(all(item.source.startswith("public_") for item in soft))

        roles = dict(self.hypothesis.roles)
        roles["student"] = "serial"
        roles["girl"] = "key"
        explanatory = replace(self.hypothesis, roles=tuple(sorted(roles.items())))
        matcher = FsbtxWitnessMatcher()
        self.assertGreater(matcher.soft_score(explanatory, witnesses),
                           matcher.soft_score(self.hypothesis, witnesses))
        # Soft evidence changes weight, never hard-rejects the alternative.
        self.assertTrue(matcher.matches(self.hypothesis, witnesses))

        evidence = PublicEvidence.from_view(view)
        worlds = ConstraintBeliefSampler().sample(
            evidence, 48, rng=random.Random(72), witnesses=witnesses)
        self.assertEqual(len(worlds), 48)
        student_serial = sum(dict(world.roles)["student"] == "serial"
                             for world in worlds)
        student_ordinary = sum(dict(world.roles)["student"] == "ordinary"
                               for world in worlds)
        other_serial = max(
            sum(dict(world.roles)[cid] == "serial" for world in worlds)
            for cid in evidence.characters if cid != "student")
        self.assertGreater(student_serial, other_serial)
        self.assertGreater(student_serial, student_ordinary,
                           (student_serial, student_ordinary))

    def test_multiple_companions_and_intrigue_support_optional_killer(self):
        view = deepcopy(self.view)
        view["events"] = [
            {"kind": "loop_started", "loop": 1, "round": 1},
            {"kind": "character_moved", "loop": 1, "round": 1,
             "character": "girl", "location": "city"},
            {"kind": "character_moved", "loop": 1, "round": 1,
             "character": "student", "location": "city"},
            {"kind": "counter_changed", "loop": 1, "round": 1,
             "target": "girl", "counter": "intrigue", "after": 2},
            {"kind": "character_died", "loop": 1, "round": 1,
             "timing": "day_end", "target": "girl"},
            {"kind": "loop_lost", "loop": 1, "round": 1},
        ]
        witnesses = FsbtxWitnessCompiler().compile(view)
        companions = [item for item in witnesses
                      if item.kind == "day_end_death_companion"]
        # A serial killer's mandatory ability requires exactly one living
        # companion; several co-located characters cannot justify that clue.
        self.assertFalse(companions)
        killer = [item for item in witnesses
                  if item.kind == "day_end_killer_candidate"]
        self.assertTrue(killer)
        self.assertTrue(all(item.strength == WitnessStrength.SOFT
                            for item in killer))
        roles = dict(self.hypothesis.roles)
        roles.update(girl="key", worker="killer")
        explanation = replace(self.hypothesis,
                              roles=tuple(sorted(roles.items())))
        self.assertGreater(FsbtxWitnessMatcher().soft_score(
            explanation, witnesses), 0)
        self.assertTrue(FsbtxWitnessMatcher().matches(
            self.hypothesis, witnesses))


if __name__ == "__main__":
    unittest.main()
