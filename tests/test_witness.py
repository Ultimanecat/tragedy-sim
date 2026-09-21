"""FS/BTX hard-witness regression tests."""

from copy import deepcopy
from dataclasses import replace
import random
import unittest

from tragedy_sim import Game
from tragedy_sim.belief import (CatalogBeliefSampler, ConstraintBeliefSampler,
                                HiddenWorldHypothesis, PublicEvidence)
from tragedy_sim.catalog import CHARACTERS
from tragedy_sim.scenario import example_scenario
from tragedy_sim.scenario_library import ScenarioLibrary
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

    def test_virus_role_reveal_does_not_rewrite_initial_identity(self):
        ordinary = next(cid for cid, role in self.hypothesis.roles
                        if role == "ordinary")
        view = deepcopy(self.view)
        view["known_roles"] = {ordinary: {"role": "serial"}}
        witness = next(item for item in FsbtxWitnessCompiler().compile(view)
                       if item.kind == "role_is")
        virus_world = replace(
            self.hypothesis,
            subplots=tuple({*self.hypothesis.subplots, "virus"}),
        )
        matcher = FsbtxWitnessMatcher()
        self.assertEqual(matcher.verdict(virus_world, witness),
                         WitnessVerdict.SATISFIED)
        self.assertEqual(matcher.verdict(self.hypothesis, witness),
                         WitnessVerdict.CONTRADICTED)

        serial_roles = dict(self.hypothesis.roles)
        serial_roles[ordinary] = "serial"
        initial_serial = replace(
            self.hypothesis, roles=tuple(sorted(serial_roles.items())))
        self.assertEqual(matcher.verdict(initial_serial, witness),
                         WitnessVerdict.SATISFIED)

    def test_catalog_match_keeps_virus_transformed_ordinary_world(self):
        library = ScenarioLibrary()
        scenario = library.get("official-btx-08-mirror-passcode")
        ordinary = next(cid for cid, role in scenario["cast"].items()
                        if role == "ordinary")
        game = Game(scenario)
        view = game.protagonist_team_view()
        view["known_roles"] = {ordinary: {"role": "serial"}}
        evidence = PublicEvidence.from_view(view)
        candidates = CatalogBeliefSampler(library).candidates(
            evidence, witnesses=FsbtxWitnessCompiler().compile(view))
        self.assertTrue(candidates)
        self.assertTrue(all(FsbtxWitnessMatcher().matches(
            candidate, FsbtxWitnessCompiler().compile(view))
            for candidate in candidates))
        self.assertTrue(any(candidate.scenario_id == scenario["id"]
                            and dict(candidate.roles).get(ordinary) == "ordinary"
                            and "virus" in candidate.subplots
                            for candidate in candidates))

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

    def test_incident_event_freezes_snapshot_across_later_days_and_loops(self):
        culprit = next(item[3] for item in self.hypothesis.incidents
                       if item[0] == 2)
        characters = {
            cid: {
                "paranoia": 0, "goodwill": 0, "intrigue": 0, "guard": 0,
                "present": True, "alive": True,
            }
            for cid in self.view["characters"]
        }
        characters[culprit]["paranoia"] = CHARACTERS[culprit].limit
        view = deepcopy(self.view)
        view["loop"] = 3
        view["round"] = 1
        view["incidents"] = []
        view["events"] = [{
            "kind": "incident_status", "loop": 1, "round": 2,
            "timing": "incident", "incident": "murder", "happened": True,
            "characters": characters,
        }]
        witness = next(item for item in FsbtxWitnessCompiler().compile(view)
                       if item.kind == "incident_happened")
        self.assertEqual((witness.loop, witness.day), (1, 2))
        self.assertEqual(witness.value["characters"][culprit]["paranoia"],
                         CHARACTERS[culprit].limit)
        self.assertEqual(FsbtxWitnessMatcher().verdict(
            self.hypothesis, witness), WitnessVerdict.SATISFIED)

        wrong_incidents = tuple(
            (entry[0], entry[1], entry[2], "girl")
            if entry[0] == 2 else entry
            for entry in self.hypothesis.incidents
        )
        wrong = replace(self.hypothesis, incidents=wrong_incidents)
        self.assertEqual(FsbtxWitnessMatcher().verdict(wrong, witness),
                         WitnessVerdict.CONTRADICTED)

    def test_game_incident_event_contains_only_public_threshold_state(self):
        game = Game(example_scenario("BTX"))
        culprit = game.scenario["incidents"][0]["culprit"]
        game.state.round = game.scenario["incidents"][0]["day"]
        game.state.characters[culprit].paranoia = CHARACTERS[culprit].limit
        game._incident()
        event = next(item for item in game.protagonist_team_view()["events"]
                     if item["kind"] == "incident_status")
        observed = event["characters"][culprit]
        self.assertEqual(set(observed), {
            "paranoia", "goodwill", "intrigue", "guard", "present", "alive",
        })
        self.assertEqual(observed["paranoia"], CHARACTERS[culprit].limit)

    def test_nonoccurrence_is_not_an_unsafe_negative_identity_inference(self):
        view = deepcopy(self.view)
        view["round"] = 2
        view["incidents"] = [{"day": 2, "kind": "murder",
                              "happened": False, "effective": False}]
        witness = next(item for item in FsbtxWitnessCompiler().compile(view)
                       if item.kind == "incident_not_happened")
        self.assertEqual(witness.strength, WitnessStrength.SOFT)
        self.assertEqual(FsbtxWitnessMatcher().verdict(
            self.hypothesis, witness), WitnessVerdict.SATISFIED)
        self.assertTrue(FsbtxWitnessMatcher().matches(self.hypothesis, (witness,)))
        culprit = next(item[3] for item in self.hypothesis.incidents
                       if item[0] == 2)
        view["characters"][culprit]["paranoia"] = \
            view["characters"][culprit]["paranoia_limit"]
        pressured = next(item for item in FsbtxWitnessCompiler().compile(view)
                         if item.kind == "incident_not_happened")
        self.assertEqual(FsbtxWitnessMatcher().verdict(
            self.hypothesis, pressured), WitnessVerdict.UNKNOWN)
        self.assertTrue(FsbtxWitnessMatcher().matches(self.hypothesis, (pressured,)))
        matcher = FsbtxWitnessMatcher()
        self.assertGreater(matcher.soft_score(self.hypothesis, (witness,)),
                           matcher.soft_score(self.hypothesis, (pressured,)))

    def test_fs_school_pressure_at_loop_end_is_soft_plot_evidence(self):
        library = ScenarioLibrary()
        protect = HiddenWorldHypothesis.from_scenario(
            library.get("official-fs-02-prevailing-secrecy"))
        other = HiddenWorldHypothesis.from_scenario(
            library.get("official-fs-01-first-script"))
        view = Game(library.get("official-fs-02-prevailing-secrecy"))\
            .protagonist_team_view()
        view["events"] = [
            {"kind": "loop_started", "loop": 1, "round": 1},
            {"kind": "counter_changed", "loop": 1, "round": 5,
             "target": "school", "counter": "intrigue", "after": 2},
            {"kind": "day_ended", "loop": 1, "round": 5},
            {"kind": "loop_lost", "loop": 1, "round": 5},
        ]
        witnesses = [item for item in FsbtxWitnessCompiler().compile(view)
                     if item.kind == "plot_pressure"]
        self.assertEqual(len(witnesses), 1)
        self.assertEqual(witnesses[0].strength, WitnessStrength.SOFT)
        matcher = FsbtxWitnessMatcher()
        self.assertTrue(matcher.matches(other, witnesses))
        self.assertGreater(matcher.soft_score(protect, witnesses),
                           matcher.soft_score(other, witnesses))
        view["events"][-2]["kind"] = "character_died"
        self.assertFalse(any(item.kind == "plot_pressure"
                             for item in FsbtxWitnessCompiler().compile(view)))

    def test_btx_public_loop_end_routes_are_soft_plot_evidence(self):
        sealed = replace(self.hypothesis, main_plot="sealed")
        change = replace(self.hypothesis, main_plot="change")
        other = replace(self.hypothesis, main_plot="murder_plan")
        view = deepcopy(self.view)
        view["events"] = [
            {"kind": "loop_started", "loop": 1, "round": 1},
            {"kind": "counter_changed", "loop": 1, "round": 2,
             "target": "shrine", "counter": "intrigue", "after": 2},
            {"kind": "incident_status", "loop": 1, "round": 3,
             "incident": "butterfly", "happened": True},
            {"kind": "day_ended", "loop": 1, "round": 4},
            {"kind": "loop_lost", "loop": 1, "round": 4},
        ]
        witnesses = [item for item in FsbtxWitnessCompiler().compile(view)
                     if item.kind == "plot_pressure"]
        self.assertEqual({item.subject for item in witnesses},
                         {"sealed", "change"})
        self.assertTrue(all(item.strength == WitnessStrength.SOFT
                            for item in witnesses))
        matcher = FsbtxWitnessMatcher()
        self.assertGreater(matcher.soft_score(sealed, witnesses),
                           matcher.soft_score(other, witnesses))
        self.assertGreater(matcher.soft_score(change, witnesses),
                           matcher.soft_score(other, witnesses))
        self.assertTrue(matcher.matches(other, witnesses))

        # Neither an unfinished day nor a non-occurring butterfly may create
        # this loop-end evidence.
        view["events"][-2]["kind"] = "character_died"
        self.assertFalse(any(item.kind == "plot_pressure"
                             for item in FsbtxWitnessCompiler().compile(view)))

    def test_btx_joint_loop_end_evidence_preserves_role_plot_correlation(self):
        view = deepcopy(self.view)
        candidate = "girl"
        initial_board = view["characters"][candidate]["initial_location"]
        view["events"] = [
            {"kind": "loop_started", "loop": 1, "round": 1},
            {"kind": "counter_changed", "loop": 1, "round": 4,
             "target": candidate, "counter": "intrigue", "after": 2},
            {"kind": "counter_changed", "loop": 1, "round": 4,
             "target": initial_board, "counter": "intrigue", "after": 2},
            {"kind": "day_ended", "loop": 1, "round": view["days"]},
            {"kind": "loop_lost", "loop": 1, "round": view["days"]},
        ]
        witnesses = FsbtxWitnessCompiler().compile(view)
        joint = [item for item in witnesses
                 if item.kind == "joint_plot_role_pressure"]
        self.assertEqual({item.subject for item in joint}, {"sign", "bomb"})
        traveler = next(item for item in witnesses
                        if item.kind == "role_pressure")
        self.assertEqual(traveler.subject, "time_traveler")
        self.assertEqual(joint[0].strength, WitnessStrength.SOFT)

        roles = dict(self.hypothesis.roles)
        roles[candidate] = "key"
        sign = replace(self.hypothesis, main_plot="sign",
                       roles=tuple(sorted(roles.items())))
        wrong_place = next(cid for cid in roles if cid != candidate)
        roles[candidate] = "ordinary"
        roles[wrong_place] = "key"
        sign_wrong = replace(self.hypothesis, main_plot="sign",
                             roles=tuple(sorted(roles.items())))
        matcher = FsbtxWitnessMatcher()
        self.assertGreater(matcher.soft_score(sign, joint),
                           matcher.soft_score(sign_wrong, joint))
        # Correlation evidence remains soft and therefore never deletes the
        # alternative explanation.
        self.assertTrue(matcher.matches(sign_wrong, joint))
        ablated = FsbtxWitnessCompiler(include_joint=False).compile(view)
        self.assertFalse(any(item.kind in {
            "joint_plot_role_pressure", "role_pressure"} for item in ablated))
        self.assertEqual(len(ablated), len(witnesses) - 3)

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
        view["characters"]["part_timer"] = {
            "paranoia": 0, "goodwill": 0, "intrigue": 0, "guard": 0,
            "present": True, "alive": False,
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

    def test_true_world_survives_every_public_checkpoint_in_recorded_btx(self):
        library = ScenarioLibrary()
        compiler = FsbtxWitnessCompiler()
        matcher = FsbtxWitnessMatcher()
        scenario_ids = [
            item["id"] for item in library.list("BTX")
            if item["source"] == "library"
        ]
        self.assertEqual(len(scenario_ids), 11)
        for scenario_id in scenario_ids:
            with self.subTest(scenario=scenario_id):
                scenario = library.get(scenario_id)
                truth = HiddenWorldHypothesis.from_scenario(scenario)
                game = Game(scenario)
                decisions = 0
                while game.winner is None and decisions < 1200:
                    view = game.protagonist_team_view()
                    evaluation = matcher.evaluate(truth, compiler.compile(view))
                    self.assertTrue(
                        evaluation.compatible,
                        (scenario_id, game.state.loop, game.state.round,
                         game.state.phase, evaluation.contradicted),
                    )
                    if game.state.phase == "final_guess":
                        game.dispatch(game.controller, "guess_all",
                                      guesses=dict(scenario["cast"]))
                    elif game.state.phase == "mastermind":
                        index = len(game.state.pending)
                        card, target = (("p1a", "school"), ("p1b", "city"),
                                        ("h", "shrine"))[index]
                        game.dispatch(game.controller, "play", card=card,
                                      target=target)
                    elif game.state.phase == "protagonists":
                        index = sum(item.actor != "m"
                                    for item in game.state.pending)
                        game.dispatch(game.controller, "play", card="g1",
                                      target=("school", "city", "shrine")[index])
                    elif game.state.phase == "reveal":
                        game.dispatch(game.controller, "resolve")
                    elif game.state.phase in {"decision", "refusal"}:
                        game.dispatch(game.controller, "choose", index=1)
                    else:
                        game.dispatch(game.controller, "next")
                    decisions += 1
                self.assertIsNotNone(game.winner,
                                     (scenario_id, decisions, game.phase_cursor))
                final = matcher.evaluate(
                    truth, compiler.compile(game.protagonist_team_view()))
                self.assertTrue(final.compatible,
                                (scenario_id, final.contradicted))

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
