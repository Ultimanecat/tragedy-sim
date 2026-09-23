"""FS/BTX hard-witness regression tests."""

from copy import deepcopy
from dataclasses import replace
import random
import unittest

from tragedy_sim import Game
from tragedy_sim.belief import (CatalogBeliefSampler, ConstraintBeliefSampler,
                                FactorizedBeliefState, HiddenWorldHypothesis,
                                PublicEvidence)
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

    def test_refused_goodwill_ability_is_a_hard_role_set_witness(self):
        view = deepcopy(self.view)
        view["events"] = [{
            "kind": "goodwill_refused", "loop": 1, "round": 1,
            "timing": "protagonist_ability", "source": "worker",
            "ability": "reveal", "ability_kind": "reveal",
        }]
        witness = next(item for item in FsbtxWitnessCompiler().compile(view)
                       if item.source == "public_goodwill_refusal")
        self.assertEqual(witness.kind, "role_in")
        self.assertEqual(witness.subject, "worker")
        self.assertEqual(witness.strength, WitnessStrength.HARD)

        roles = dict(self.hypothesis.roles)
        roles["worker"] = "brain"
        refusing = replace(
            self.hypothesis, roles=tuple(sorted(roles.items())))
        roles["worker"] = "ordinary"
        unable = replace(self.hypothesis, roles=tuple(sorted(roles.items())))
        matcher = FsbtxWitnessMatcher()
        self.assertEqual(matcher.verdict(refusing, witness),
                         WitnessVerdict.SATISFIED)
        self.assertEqual(matcher.verdict(unable, witness),
                         WitnessVerdict.CONTRADICTED)

    def test_accepted_refusable_goodwill_excludes_mandatory_refusers(self):
        view = deepcopy(self.view)
        view["events"] = [{
            "kind": "goodwill_accepted", "loop": 1, "round": 1,
            "timing": "protagonist_ability", "source": "worker",
            "ability": "reveal", "ability_kind": "reveal",
            "unrefusable": False,
        }]
        compiler = FsbtxWitnessCompiler()
        witness = next(item for item in compiler.compile(view)
                       if item.source == "public_refusable_goodwill_accepted")
        self.assertEqual(witness.kind, "role_not_in")
        self.assertEqual(set(witness.value), {"cultist", "witch"})
        self.assertEqual(witness.strength, WitnessStrength.HARD)

        roles = dict(self.hypothesis.roles)
        roles["worker"] = "cultist"
        mandatory = replace(
            self.hypothesis, roles=tuple(sorted(roles.items())))
        roles["worker"] = "ordinary"
        allowed = replace(self.hypothesis, roles=tuple(sorted(roles.items())))
        matcher = FsbtxWitnessMatcher()
        self.assertEqual(matcher.verdict(mandatory, witness),
                         WitnessVerdict.CONTRADICTED)
        self.assertEqual(matcher.verdict(allowed, witness),
                         WitnessVerdict.SATISFIED)

        view["events"][0]["unrefusable"] = True
        self.assertFalse(any(item.kind == "role_not_in"
                             for item in compiler.compile(view)))
        del view["events"][0]["unrefusable"]
        self.assertFalse(any(item.kind == "role_not_in"
                             for item in compiler.compile(view)))

    def test_witness_source_can_be_ablated(self):
        view = deepcopy(self.view)
        view["events"] = [{
            "kind": "goodwill_accepted", "loop": 1, "round": 1,
            "source": "worker", "unrefusable": False,
        }]
        enabled = FsbtxWitnessCompiler().compile(view)
        disabled = FsbtxWitnessCompiler(disabled_sources={
            "public_refusable_goodwill_accepted"}).compile(view)
        self.assertEqual(len(enabled), len(disabled) + 1)
        self.assertFalse(any(
            item.source == "public_refusable_goodwill_accepted"
            for item in disabled))

    def test_accepted_goodwill_witness_reduces_exact_role_space(self):
        view = deepcopy(self.view)
        view["events"] = [{
            "kind": "goodwill_accepted", "loop": 1, "round": 1,
            "source": "worker", "unrefusable": False,
        }]
        evidence = PublicEvidence.from_view(view)
        source = "public_refusable_goodwill_accepted"
        enabled_witnesses = FsbtxWitnessCompiler().compile(view)
        ablated_witnesses = FsbtxWitnessCompiler(
            disabled_sources={source}).compile(view)
        enabled = FactorizedBeliefState(capacity=100_000, seed=1) \
            .role_posterior(evidence, enabled_witnesses)
        ablated = FactorizedBeliefState(capacity=100_000, seed=1) \
            .role_posterior(evidence, ablated_witnesses)
        forbidden = {"cultist", "witch"}
        self.assertLess(len(enabled), len(ablated))
        self.assertFalse(any(dict(world.roles).get("worker") in forbidden
                             for world, _ in enabled))
        self.assertTrue(any(dict(world.roles).get("worker") in forbidden
                            for world, _ in ablated))

    def test_successful_suicide_death_identifies_the_culprit(self):
        view = deepcopy(self.view)
        view["events"] = [
            {"kind": "incident_status", "loop": 2, "round": 3,
             "timing": "incident", "incident": "suicide",
             "happened": True},
            {"kind": "character_died", "loop": 2, "round": 3,
             "timing": "incident", "target": "doctor"},
            {"kind": "incident_ended", "loop": 2, "round": 3},
        ]
        source = "public_suicide_victim"
        compiler = FsbtxWitnessCompiler()
        witness = next(item for item in compiler.compile(view)
                       if item.source == source)
        self.assertEqual(
            (witness.kind, witness.subject, witness.value, witness.strength),
            ("culprit_is", "3", "doctor", WitnessStrength.HARD))

        matching = replace(
            self.hypothesis,
            incidents=((3, "suicide", "suicide", "doctor"),))
        wrong = replace(
            self.hypothesis,
            incidents=((3, "suicide", "suicide", "girl"),))
        matcher = FsbtxWitnessMatcher()
        self.assertEqual(matcher.verdict(matching, witness),
                         WitnessVerdict.SATISFIED)
        self.assertEqual(matcher.verdict(wrong, witness),
                         WitnessVerdict.CONTRADICTED)
        self.assertFalse(any(item.source == source for item in
                             FsbtxWitnessCompiler(
                                 disabled_sources={source}).compile(view)))

    def test_prevented_or_unfinished_suicide_makes_no_culprit_claim(self):
        source = "public_suicide_victim"
        view = deepcopy(self.view)
        view["events"] = [{
            "kind": "incident_status", "loop": 1, "round": 2,
            "timing": "incident", "incident": "suicide",
            "happened": True,
        }, {
            "kind": "incident_ended", "loop": 1, "round": 2,
            "effective": False,
        }]
        self.assertFalse(any(item.source == source
                             for item in FsbtxWitnessCompiler().compile(view)))

        view["events"][0]["happened"] = False
        view["events"].insert(1, {
            "kind": "character_died", "loop": 1, "round": 2,
            "timing": "day_end", "target": "doctor",
        })
        self.assertFalse(any(item.source == source
                             for item in FsbtxWitnessCompiler().compile(view)))

    def test_suicide_replacement_maps_question_mark_to_part_timer(self):
        view = deepcopy(self.view)
        view["events"] = [{
            "kind": "incident_status", "loop": 1, "round": 2,
            "incident": "suicide", "happened": True,
        }, {
            "kind": "character_died", "loop": 1, "round": 2,
            "target": "part_timer_question",
        }]
        witness = next(item for item in FsbtxWitnessCompiler().compile(view)
                       if item.source == "public_suicide_victim")
        self.assertEqual(witness.value, "part_timer")

    def test_suicide_victim_collapses_the_culprit_dimension(self):
        view = deepcopy(self.view)
        view["schedule"] = [{"day": 3, "kind": "suicide"}]
        view["events"] = [{
            "kind": "incident_status", "loop": 1, "round": 3,
            "incident": "suicide", "happened": True,
        }, {
            "kind": "character_died", "loop": 1, "round": 3,
            "target": "doctor",
        }]
        evidence = PublicEvidence.from_view(view)
        source = "public_suicide_victim"
        enabled = FsbtxWitnessCompiler().compile(view)
        ablated = FsbtxWitnessCompiler(
            disabled_sources={source}).compile(view)
        belief = FactorizedBeliefState(capacity=64, seed=1)
        self.assertEqual(belief._culprits(evidence, enabled)[3], ("doctor",))
        self.assertGreater(len(belief._culprits(evidence, ablated)[3]), 1)

    def test_missing_move_identifies_the_culprit(self):
        view = deepcopy(self.view)
        view["schedule"] = [{"day": 2, "kind": "missing"}]
        view["events"] = [
            {"kind": "incident_status", "loop": 1, "round": 2,
             "incident": "missing", "happened": True},
            {"kind": "character_moved", "loop": 1, "round": 2,
             "target": "worker", "location": "city"},
            {"kind": "counter_changed", "loop": 1, "round": 2,
             "target": "city", "counter": "intrigue", "after": 1},
            {"kind": "incident_ended", "loop": 1, "round": 2},
        ]
        witnesses = FsbtxWitnessCompiler().compile(view)
        direct = next(item for item in witnesses
                      if item.source == "public_missing_moved_culprit")
        self.assertEqual(
            (direct.subject, direct.value),
            ("2", "worker"))

        evidence = PublicEvidence.from_view(view)
        belief = FactorizedBeliefState(capacity=64, seed=1)
        culprits = belief._culprits(evidence, witnesses)
        self.assertEqual(culprits[2], ("worker",))

    def test_blocked_missing_move_makes_no_culprit_claim(self):
        source = "public_missing_moved_culprit"
        view = deepcopy(self.view)
        view["events"] = [
            {"kind": "incident_status", "loop": 1, "round": 2,
             "incident": "missing", "happened": True},
            {"kind": "movement_blocked", "loop": 1, "round": 2},
            {"kind": "incident_ended", "loop": 1, "round": 2,
             "effective": False},
        ]
        self.assertFalse(any(item.source == source
                             for item in FsbtxWitnessCompiler().compile(view)))

    def test_missing_culprit_source_maps_replacement_and_is_ablatable(self):
        view = deepcopy(self.view)
        view["events"] = [
            {"kind": "incident_status", "loop": 1, "round": 2,
             "incident": "missing", "happened": True},
            {"kind": "character_moved", "loop": 1, "round": 2,
             "character": "part_timer_question"},
            {"kind": "incident_ended", "loop": 1, "round": 2},
        ]
        missing = "public_missing_moved_culprit"
        witnesses = FsbtxWitnessCompiler(
            disabled_sources={missing}).compile(view)
        self.assertFalse(any(item.source == missing for item in witnesses))
        self.assertEqual(next(item.value for item in
                              FsbtxWitnessCompiler().compile(view)
                              if item.source == missing), "part_timer")

    def test_murder_and_butterfly_targets_restrict_culprit_location(self):
        view = deepcopy(self.view)
        characters = {
            cid: {
                "location": ("school" if cid in {"girl", "doctor"}
                             else "city"),
                "paranoia": CHARACTERS[cid].limit, "goodwill": 0,
                "intrigue": 0, "guard": 0,
                "present": True, "alive": True,
            }
            for cid in view["characters"]
        }
        view["schedule"] = [
            {"day": 2, "kind": "murder"},
            {"day": 3, "kind": "butterfly"},
        ]
        view["events"] = [
            {"kind": "incident_status", "loop": 1, "round": 2,
             "incident": "murder", "happened": True,
             "characters": characters},
            {"kind": "character_died", "loop": 1, "round": 2,
             "target": "girl"},
            {"kind": "incident_ended", "loop": 1, "round": 2},
            {"kind": "incident_status", "loop": 1, "round": 3,
             "incident": "butterfly", "happened": True,
             "characters": characters},
            {"kind": "counter_changed", "loop": 1, "round": 3,
             "target": "girl", "counter": "goodwill", "after": 1},
            {"kind": "incident_ended", "loop": 1, "round": 3},
        ]
        source = "public_incident_effect_location"
        witnesses = [item for item in FsbtxWitnessCompiler().compile(view)
                     if item.source == source]
        self.assertEqual([(item.subject, item.value) for item in witnesses], [
            ("2", ("doctor",)),
            ("3", ("doctor", "girl")),
        ])

        evidence = PublicEvidence.from_view(view)
        culprits = FactorizedBeliefState(capacity=64, seed=1)._culprits(
            evidence, FsbtxWitnessCompiler().compile(view))
        self.assertEqual(culprits[2], ("doctor",))
        self.assertEqual(culprits[3], ("doctor", "girl"))

    def test_incident_location_witness_requires_snapshot_and_is_ablatable(self):
        view = deepcopy(self.view)
        view["events"] = [{
            "kind": "incident_status", "loop": 1, "round": 2,
            "incident": "murder", "happened": True,
            "characters": {
                "girl": {"present": True, "alive": True},
                "doctor": {"present": True, "alive": True},
            },
        }, {
            "kind": "character_died", "loop": 1, "round": 2,
            "target": "girl",
        }]
        source = "public_incident_effect_location"
        self.assertFalse(any(item.source == source
                             for item in FsbtxWitnessCompiler().compile(view)))

        view["events"][0]["characters"]["girl"]["location"] = "school"
        view["events"][0]["characters"]["doctor"]["location"] = "school"
        self.assertTrue(any(item.source == source
                            for item in FsbtxWitnessCompiler().compile(view)))
        self.assertFalse(any(item.source == source for item in
                             FsbtxWitnessCompiler(
                                 disabled_sources={source}).compile(view)))

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

    def test_btx_virus_transformed_ordinary_explains_serial_death(self):
        view = deepcopy(self.view)
        companion = "student"
        victim = "girl"
        view["events"] = [
            {"kind": "loop_started", "loop": 1, "round": 1},
            {"kind": "character_moved", "loop": 1, "round": 1,
             "character": companion,
             "location": view["characters"][victim]["initial_location"]},
            {"kind": "counter_changed", "loop": 1, "round": 1,
             "target": companion, "counter": "paranoia", "after": 3},
            {"kind": "character_died", "loop": 1, "round": 1,
             "timing": "day_end", "target": victim},
        ]
        witness = next(item for item in FsbtxWitnessCompiler().compile(view)
                       if item.kind == "day_end_death_companion")
        roles = dict(self.hypothesis.roles)
        roles[companion] = "ordinary"
        virus = replace(self.hypothesis, subplots=("virus", "rumor"),
                        roles=tuple(sorted(roles.items())))
        matcher = FsbtxWitnessMatcher()
        self.assertEqual(matcher.verdict(virus, witness),
                         WitnessVerdict.SATISFIED)
        no_virus = replace(virus, subplots=("lurking", "rumor"))
        self.assertEqual(matcher.verdict(no_virus, witness),
                         WitnessVerdict.UNKNOWN)

    def test_btx_city_pressure_allows_factor_key_death_explanation(self):
        view = deepcopy(self.view)
        victim = "girl"
        view["events"] = [
            {"kind": "loop_started", "loop": 1, "round": 1},
            {"kind": "counter_changed", "loop": 1, "round": 1,
             "target": "city", "counter": "intrigue", "after": 2},
            {"kind": "character_died", "loop": 1, "round": 1,
             "timing": "day_end", "target": victim},
            {"kind": "loop_lost", "loop": 1, "round": 1},
        ]
        witness = next(item for item in FsbtxWitnessCompiler().compile(view)
                       if item.kind == "loss_after_death")
        roles = dict(self.hypothesis.roles)
        roles[victim] = "factor"
        factor = replace(self.hypothesis,
                         roles=tuple(sorted(roles.items())))
        self.assertEqual(FsbtxWitnessMatcher().verdict(factor, witness),
                         WitnessVerdict.SATISFIED)

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
            "location", "paranoia", "goodwill", "intrigue", "guard",
            "present", "alive",
        })
        self.assertEqual(observed["location"],
                         game.state.characters[culprit].location)
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
                         {"sealed", "change", "bomb"})
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

    def test_normal_loop_end_loss_requires_a_legal_main_plot_explanation(self):
        view = deepcopy(self.view)
        view["events"] = [
            {"kind": "loop_started", "loop": 1, "round": 1},
            {"kind": "counter_changed", "loop": 1,
             "round": view["days"], "target": "shrine",
             "counter": "intrigue", "after": 2},
            {"kind": "day_ended", "loop": 1, "round": view["days"]},
            {"kind": "loop_lost", "loop": 1, "round": view["days"]},
        ]
        witness = next(
            item for item in FsbtxWitnessCompiler().compile(view)
            if item.source == "public_normal_loop_end_loss")
        self.assertEqual(witness.kind, "loop_end_plot_explanation")
        self.assertEqual(witness.strength, WitnessStrength.HARD)
        matcher = FsbtxWitnessMatcher()
        sealed = replace(self.hypothesis, main_plot="sealed")
        change = replace(self.hypothesis, main_plot="change")
        self.assertEqual(matcher.verdict(sealed, witness),
                         WitnessVerdict.SATISFIED)
        self.assertEqual(matcher.verdict(change, witness),
                         WitnessVerdict.CONTRADICTED)

        # A Friend reveal between day end and loss is another complete cause;
        # do not incorrectly require a main-plot explanation in that case.
        view["events"].insert(-1, {
            "kind": "role_revealed", "loop": 1, "round": view["days"],
            "character": "girl", "role": "friend",
        })
        self.assertFalse(any(
            item.source == "public_normal_loop_end_loss"
            for item in FsbtxWitnessCompiler().compile(view)))

    def test_normal_loop_end_explanation_source_can_be_ablated(self):
        view = deepcopy(self.view)
        view["events"] = [
            {"kind": "loop_started", "loop": 1, "round": 1},
            {"kind": "counter_changed", "loop": 1,
             "round": view["days"], "target": "shrine",
             "counter": "intrigue", "after": 2},
            {"kind": "day_ended", "loop": 1, "round": view["days"]},
            {"kind": "loop_lost", "loop": 1, "round": view["days"]},
        ]
        source = "public_normal_loop_end_loss"
        self.assertTrue(any(item.source == source
                            for item in FsbtxWitnessCompiler().compile(view)))
        self.assertFalse(any(item.source == source for item in
                             FsbtxWitnessCompiler(disabled_sources={source})
                             .compile(view)))

        evidence = PublicEvidence.from_view(view)
        enabled = FactorizedBeliefState(capacity=100_000, seed=1) \
            .role_posterior(evidence,
                            FsbtxWitnessCompiler().compile(view))
        ablated = FactorizedBeliefState(capacity=100_000, seed=1) \
            .role_posterior(evidence,
                            FsbtxWitnessCompiler(disabled_sources={source})
                            .compile(view))
        self.assertLess(len(enabled), len(ablated))
        self.assertEqual({world.main_plot for world, _ in enabled},
                         {"sealed", "bomb"})

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
        plot_pressure = [item for item in witnesses
                         if item.kind == "plot_pressure"]
        self.assertEqual({item.subject for item in plot_pressure}, {"bomb"})
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

    def test_btx_final_day_declared_loss_supports_time_traveler(self):
        view = deepcopy(self.view)
        view["events"] = [
            {"kind": "loop_started", "loop": 1, "round": 1},
            {"kind": "counter_changed", "loop": 1,
             "round": view["days"], "target": "girl",
             "counter": "goodwill", "after": 1},
            {"kind": "counter_changed", "loop": 1,
             "round": view["days"], "target": "student",
             "counter": "goodwill", "after": 3},
            {"kind": "protagonists_lost", "loop": 1,
             "round": view["days"], "timing": "day_end"},
            {"kind": "loop_lost", "loop": 1,
             "round": view["days"], "timing": "loop_end"},
        ]
        witnesses = FsbtxWitnessCompiler().compile(view)
        traveler = next(item for item in witnesses
                        if item.kind == "role_pressure"
                        and item.subject == "time_traveler")
        self.assertIn("girl", traveler.value["candidates"])
        self.assertNotIn("student", traveler.value["candidates"])
        self.assertEqual(traveler.timing, "loop_end")
        self.assertEqual(traveler.strength, WitnessStrength.HARD)

        roles = dict(self.hypothesis.roles)
        for cid, role in tuple(roles.items()):
            if role == "time_traveler":
                roles[cid] = "ordinary"
        roles["student"] = "time_traveler"
        wrong = replace(self.hypothesis, roles=tuple(sorted(roles.items())))
        self.assertFalse(FsbtxWitnessMatcher().matches(wrong, (traveler,)))

    def test_btx_ignored_goodwill_forbid_reveals_time_traveler(self):
        view = deepcopy(self.view)
        view["events"] = [
            {"kind": "cards_revealed", "loop": 1, "round": 1,
             "cards": [
                 {"actor": "m", "card": "fg", "target": "girl"},
                 {"actor": "a", "card": "g2", "target": "girl"},
             ]},
            {"kind": "counter_changed", "loop": 1, "round": 1,
             "timing": "action_resolution", "target": "girl",
             "counter": "goodwill", "before": 0, "after": 2},
            {"kind": "actions_resolved", "loop": 1, "round": 1},
        ]
        witnesses = FsbtxWitnessCompiler().compile(view)
        reveal = next(item for item in witnesses
                      if item.kind == "role_is" and item.subject == "girl")
        self.assertEqual(reveal.value, "time_traveler")
        self.assertEqual(reveal.strength, WitnessStrength.HARD)

    def test_ignored_intrigue_forbid_proves_a_local_cultist(self):
        view = deepcopy(self.view)
        location = view["characters"]["girl"]["initial_location"]
        view["events"] = [
            {"kind": "loop_started", "loop": 1, "round": 1},
            {"kind": "character_moved", "loop": 1, "round": 1,
             "character": "worker", "location": location},
            {"kind": "cards_revealed", "loop": 1, "round": 1,
             "cards": [
                 {"actor": "m", "card": "i1", "target": "girl"},
                 {"actor": "a", "card": "fi", "target": "girl"},
             ]},
            {"kind": "counter_changed", "loop": 1, "round": 1,
             "target": "girl", "counter": "intrigue",
             "before": 0, "after": 1},
            {"kind": "actions_resolved", "loop": 1, "round": 1},
        ]
        source = "public_intrigue_forbid_ignored"
        witness = next(item for item in FsbtxWitnessCompiler().compile(view)
                       if item.source == source)
        self.assertEqual(witness.kind, "role_pressure")
        self.assertEqual(witness.subject, "cultist")
        self.assertIn("girl", witness.value["candidates"])
        self.assertIn("worker", witness.value["candidates"])
        self.assertEqual(witness.strength, WitnessStrength.HARD)

        matcher = FsbtxWitnessMatcher()
        roles = dict(self.hypothesis.roles)
        for cid in witness.value["candidates"]:
            if cid in roles and roles[cid] == "cultist":
                roles[cid] = "ordinary"
        wrong = replace(self.hypothesis, roles=tuple(sorted(roles.items())))
        self.assertEqual(matcher.verdict(wrong, witness),
                         WitnessVerdict.CONTRADICTED)

        disabled = FsbtxWitnessCompiler(
            disabled_sources={source}).compile(view)
        self.assertFalse(any(item.source == source for item in disabled))

        # Two FI cards cancel globally; their failure reveals no Cultist.
        view["events"][2]["cards"].append(
            {"actor": "b", "card": "fi", "target": "student"})
        self.assertFalse(any(item.source == source
                             for item in FsbtxWitnessCompiler().compile(view)))

    def test_day_end_hero_death_requires_killer_or_lover_route(self):
        view = deepcopy(self.view)
        view["events"] = [
            {"kind": "loop_started", "loop": 1, "round": 1},
            {"kind": "counter_changed", "loop": 1, "round": 1,
             "target": "girl", "counter": "intrigue", "after": 4},
            {"kind": "counter_changed", "loop": 1, "round": 1,
             "target": "worker", "counter": "intrigue", "after": 1},
            {"kind": "counter_changed", "loop": 1, "round": 1,
             "target": "worker", "counter": "paranoia", "after": 3},
            {"kind": "heroes_died", "loop": 1, "round": 1,
             "timing": "day_end"},
            {"kind": "loop_lost", "loop": 1, "round": 1},
        ]
        source = "public_day_end_hero_death"
        witness = next(item for item in FsbtxWitnessCompiler().compile(view)
                       if item.source == source)
        self.assertEqual(witness.value,
                         {"killer": ("girl",), "lover": ("worker",)})
        self.assertEqual(witness.strength, WitnessStrength.HARD)
        matcher = FsbtxWitnessMatcher()

        roles = dict(self.hypothesis.roles)
        roles["girl"] = "killer"
        roles["worker"] = "ordinary"
        killer = replace(self.hypothesis,
                         roles=tuple(sorted(roles.items())))
        self.assertEqual(matcher.verdict(killer, witness),
                         WitnessVerdict.SATISFIED)
        roles["girl"] = "ordinary"
        roles["worker"] = "lover"
        lover = replace(self.hypothesis,
                        roles=tuple(sorted(roles.items())))
        self.assertEqual(matcher.verdict(lover, witness),
                         WitnessVerdict.SATISFIED)
        roles["worker"] = "ordinary"
        wrong = replace(self.hypothesis,
                        roles=tuple(sorted(roles.items())))
        self.assertEqual(matcher.verdict(wrong, witness),
                         WitnessVerdict.CONTRADICTED)

        disabled = FsbtxWitnessCompiler(
            disabled_sources={source}).compile(view)
        self.assertFalse(any(item.source == source for item in disabled))

        # Hospital accidents happen at the incident timing and must not be
        # mistaken for a day-end identity ability.
        view["events"][4]["timing"] = "incident"
        self.assertFalse(any(item.source == source
                             for item in FsbtxWitnessCompiler().compile(view)))

    def test_btx_immediate_death_loss_requires_key_ability(self):
        view = deepcopy(self.view)
        view["events"] = [
            {"kind": "loop_started", "loop": 1, "round": 1},
            {"kind": "counter_changed", "loop": 1, "round": 1,
             "target": "city", "counter": "intrigue", "after": 2},
            {"kind": "character_died", "loop": 1, "round": 1,
             "target": "girl", "timing": "day_end"},
            {"kind": "character_died", "loop": 1, "round": 1,
             "target": "student", "timing": "day_end"},
            {"kind": "incident_ended", "loop": 1, "round": 1},
            {"kind": "loop_lost", "loop": 1, "round": 1,
             "timing": "loop_end"},
        ]
        source = "public_btx_immediate_death_loss"
        witness = next(item for item in FsbtxWitnessCompiler().compile(view)
                       if item.source == source)
        expected = ("girl", "student")
        self.assertEqual(witness.value,
                         {"key": expected, "factor": expected})
        matcher = FsbtxWitnessMatcher()
        roles = dict(self.hypothesis.roles)
        roles["girl"] = "ordinary"
        roles["student"] = "factor"
        factor = replace(self.hypothesis,
                         roles=tuple(sorted(roles.items())))
        self.assertEqual(matcher.verdict(factor, witness),
                         WitnessVerdict.SATISFIED)
        roles["student"] = "ordinary"
        wrong = replace(self.hypothesis,
                        roles=tuple(sorted(roles.items())))
        self.assertEqual(matcher.verdict(wrong, witness),
                         WitnessVerdict.CONTRADICTED)

        disabled = FsbtxWitnessCompiler(
            disabled_sources={source}).compile(view)
        self.assertFalse(any(item.source == source for item in disabled))

        # A normal day boundary means the later loop loss may be a plot or
        # Friend route rather than an immediate Key death.
        view["events"].insert(-1, {
            "kind": "day_ended", "loop": 1, "round": 1})
        self.assertFalse(any(item.source == source
                             for item in FsbtxWitnessCompiler().compile(view)))

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
        self.assertEqual(len(scenario_ids), 21)
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
        # Isolate the older soft repetition channel by ablating the newer,
        # logically stronger immediate-loss constraint in this test.
        witnesses = FsbtxWitnessCompiler(disabled_sources={
            "public_btx_immediate_death_loss"}).compile(view)
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
