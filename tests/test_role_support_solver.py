from collections import Counter
from dataclasses import replace
from itertools import permutations
import random
import unittest
from unittest.mock import patch

from tragedy_sim import Game
from tragedy_sim.belief import ConstraintBeliefSampler, FactorizedBeliefState, HiddenWorldHypothesis, PublicEvidence
from tragedy_sim.belief_matrix_sampler import MatrixWorldSampler
from tragedy_sim.belief_posterior import RolePosteriorTarget
from tragedy_sim.catalog import MODULES, PLOTS
from tragedy_sim.engine import RuleError
from tragedy_sim.effects.characters import learn_role
from tragedy_sim.belief_matrix import BeliefMatrixProjection, HardStatus
from tragedy_sim.scenario import validate_scenario
from tragedy_sim.witness import FsbtxWitnessMatcher, PublicWitness, WitnessStrength
from tests.test_belief_posterior import evidence


def independent_extra_casts(setup):
    """Permutation/printed validator reference, independent of matrix counts."""
    regular = tuple(cid for cid in setup.characters if cid not in {"irregular", "copycat"})
    module_roles = {role for p in MODULES[setup.module].plots for role in PLOTS[p][2]}
    result = {}
    for main, subs, slots in ConstraintBeliefSampler._plot_slot_sets(setup):
        if sum(slots.values()) > len(regular):
            continue
        bag = list(slots.elements()) + ["ordinary"] * (len(regular) - sum(slots.values()))
        selected = {role for p in (main, *subs) for role in PLOTS[p][2]}
        extras = sorted(module_roles - selected) if "irregular" in setup.characters else (None,)
        for roles in sorted(set(permutations(bag))):
            for irregular in extras:
                cast = dict(zip(regular, roles))
                if irregular is not None:
                    cast["irregular"] = irregular
                copies = sorted(set(cast.values())) if "copycat" in setup.characters else (None,)
                for copy in copies:
                    candidate = {**cast, **({"copycat": copy} if copy is not None else {})}
                    try:
                        scenario = validate_scenario({
                            "id": "independent-extra-reference", "title": "reference", "module": setup.module,
                            "days": setup.days, "loops": setup.loops, "table_talk": setup.table_talk,
                            "main_plot": main, "subplots": list(subs), "cast": candidate,
                            "incidents": [], **setup.setup_fields()})
                    except RuleError:
                        continue
                    world = HiddenWorldHypothesis.from_scenario(scenario)
                    result[FactorizedBeliefState._key(world)] = world
    return tuple(result.values())


class RoleSupportSolverTests(unittest.TestCase):
    def copy_setup(self):
        scenario = validate_scenario({
            "id": "extra-copy", "title": "copy", "module": "FS", "days": 2, "loops": 2,
            "main_plot": "avenger", "subplots": ["hideous"],
            "cast": {"girl": "friend", "doctor": "brain", "student": "conspiracy",
                     "maiden": "ordinary", "copycat": "friend"}, "incidents": []})
        setup = PublicEvidence.from_view(Game(scenario).protagonist_team_view())
        return scenario, setup

    def test_known_copycat_has_exact_library_and_valid_map_without_recovery(self):
        scenario, setup = self.copy_setup()
        setup = replace(setup, known_roles=tuple(scenario["cast"].items()),
                        known_plots=("avenger", "hideous"))
        state = FactorizedBeliefState(matrix_recovery=False)
        library = state.role_posterior(setup, ())
        self.assertEqual(len(library), 1)
        self.assertTrue(state.proposal_summary()["exact"])
        self.assertEqual(state.matrix_recovery_attempts, 0)
        solved = state.exact_role_map(setup, ())
        self.assertEqual(dict(solved.selected.roles), scenario["cast"])
        solved.selected.materialize(setup)

    def test_random_invalid_incident_placeholders_cannot_remove_role_space(self):
        setup = replace(evidence(), days=2, schedule=((1, "suicide"), (2, "hospital")))
        bad = [{"day": day, "kind": kind, "culprit": "doctor"} for day, kind in setup.schedule]
        state = FactorizedBeliefState(matrix_recovery=False, seed=13)
        with patch.object(state.sampler, "_incidents", return_value=bad):
            actual = state.role_posterior(setup, ())
        expected = independent_extra_casts(replace(setup, schedule=()))
        actual_keys, expected_keys = {state._key(w) for w, _ in actual}, {state._key(w) for w in expected}
        self.assertTrue(actual_keys == expected_keys,
                        f"Actual {len(actual_keys)} / reference {len(expected_keys)} role worlds")
        for world, _ in actual:
            world.materialize(setup)
        before = state.rng.getstate()
        repeated = FactorizedBeliefState(matrix_recovery=False, seed=100).role_posterior(setup, ())
        self.assertEqual(actual, repeated)
        self.assertEqual(state.rng.getstate(), before)

    def test_extra_initial_prior_counts_equal_independent_printed_enumeration(self):
        for module in ("FS", "BTX"):
            for extras in (("copycat",), ("irregular",), ("irregular", "copycat")):
                with self.subTest(module=module, extras=extras):
                    setup = replace(evidence(module), characters=(*evidence(module).characters, *extras))
                    reference = independent_extra_casts(setup)
                    self.assertTrue(reference)
                    self.assertEqual(RolePosteriorTarget(setup).plot_sizes, Counter(
                        (w.main_plot, w.subplots) for w in reference))

    def test_extra_map_agrees_with_exhaustive_hard_and_soft_reference(self):
        for module, plots in (("FS", ("avenger", "hideous")),
                              ("BTX", ("sealed", "unknown", "virus"))):
            for extras in (("copycat",), ("irregular",), ("irregular", "copycat")):
                with self.subTest(module=module, extras=extras):
                    setup = replace(evidence(module), characters=(*evidence(module).characters, *extras),
                                    known_plots=plots)
                    facts = (PublicWitness("role_pressure", "brain", {"candidates": ["doctor", "girl"]},
                                           1, 1, "test", "test"),
                             PublicWitness("role_pressure", "friend", {"candidates": ["copycat", "maiden"]},
                                           1, 1, "test", "test", WitnessStrength.SOFT))
                    target = RolePosteriorTarget(setup)
                    reference = [(w, target.weight(w, facts)) for w in independent_extra_casts(setup)
                                 if FsbtxWitnessMatcher().matches(w, facts)]
                    self.assertTrue(reference)
                    expected = max(reference, key=lambda pair: (
                        pair[1], pair[0].roles, pair[0].main_plot, pair[0].subplots))
                    state = FactorizedBeliefState(matrix_recovery=False)
                    actual = state.exact_role_map(setup, facts)
                    self.assertEqual(actual.ranked[0][1], expected[1])
                    self.assertEqual(actual.selected.roles, expected[0].roles)
                    actual.selected.materialize(setup)

    def test_future_known_incident_is_reserved_in_map_placeholder(self):
        setup = replace(evidence(), days=2, schedule=((1, "suicide"), (2, "hospital")),
                        known_culprits=((2, "doctor"),))
        solved = FactorizedBeliefState().exact_role_map(setup, ())
        self.assertTrue(solved.ranked)
        self.assertEqual(solved.selected.incidents[1][3], "doctor")
        self.assertNotEqual(solved.selected.incidents[0][3], "doctor")
        for world, _ in solved.ranked:
            world.materialize(setup)

    def test_private_part_timer_identity_survives_matrix_proposals(self):
        scenario = validate_scenario({
            "id": "private-temp", "title": "private", "module": "FS", "days": 2, "loops": 2,
            "main_plot": "avenger", "subplots": ["rumor"],
            "cast": {"part_timer": "brain", "maiden": "conspiracy", "doctor": "ordinary"},
            "incidents": []})
        view = Game(scenario).protagonist_team_view()
        view["protagonist_knowledge"] = {"roles": {"part_timer_question": "brain"}}
        setup = PublicEvidence.from_view(view)
        self.assertEqual(setup.known_initial_roles, (("part_timer", "brain"),))
        draws = MatrixWorldSampler().propose_roles(setup, (), 32, rng=random.Random(3))
        self.assertEqual(len(draws), 32)
        self.assertTrue(all(dict(draw.world.roles)["part_timer"] == "brain" for draw in draws))

    def test_private_initial_serial_answer_is_more_precise_than_virus_public_reveal(self):
        scenario = validate_scenario({
            "id": "private-serial", "title": "private", "module": "BTX", "days": 2, "loops": 2,
            "main_plot": "bomb", "subplots": ["lurking", "virus"],
            "cast": {"girl": "witch", "doctor": "serial", "student": "friend",
                     "maiden": "conspiracy", "patient": "ordinary"}, "incidents": []})
        view = Game(scenario).protagonist_team_view()
        view["known_roles"] = {"doctor": {"role": "serial"}}
        view["known_plots"] = ["bomb", "lurking", "virus"]
        observed = PublicEvidence.from_view(view)
        view["protagonist_knowledge"] = {"initial_roles": {"doctor": "serial"}}
        answered = PublicEvidence.from_view(view)
        truth = HiddenWorldHypothesis.from_scenario(scenario)
        roles = dict(truth.roles)
        roles["doctor"], roles["patient"] = roles["patient"], roles["doctor"]
        alternative = replace(truth, roles=tuple(sorted(roles.items())))
        alternative.materialize(answered)
        self.assertTrue(observed.matches_roles(alternative.main_plot, alternative.subplots, alternative.roles))
        self.assertFalse(answered.matches_roles(alternative.main_plot, alternative.subplots, alternative.roles))
        target = RolePosteriorTarget(answered)
        self.assertEqual(target.weight(alternative, ()), 0)
        self.assertEqual(target.plot_sizes, RolePosteriorTarget(observed).plot_sizes)
        draws = MatrixWorldSampler().propose_roles(answered, (), 32, rng=random.Random(7))
        self.assertEqual(len(draws), 32)
        self.assertTrue(all(dict(p.world.roles)["doctor"] == "serial" for p in draws))
        state = FactorizedBeliefState(matrix_recovery=False)
        initial = state.role_posterior(observed, ())
        self.assertTrue(any(dict(w.roles)["doctor"] == "ordinary" for w, _ in initial))
        posterior = state.role_posterior(answered, ())
        self.assertTrue(posterior)
        self.assertTrue(all(dict(w.roles)["doctor"] == "serial" for w, _ in posterior))
        # Multiple observations must not overwrite the private-answer map
        # while selecting the next initial identity in the legacy generator.
        several = replace(answered, known_roles=(("girl", "witch"), ("doctor", "serial")))
        for seed in range(16):
            cast = ConstraintBeliefSampler._cast(
                several, Counter(witch=1, friend=1, serial=1, conspiracy=1),
                ("bomb", "lurking", "virus"), random.Random(seed))
            self.assertIsNotNone(cast)
            self.assertEqual(cast["doctor"], "serial")

    def test_later_known_roles_condition_exact_pool_without_separate_witness(self):
        setup = evidence()
        state = FactorizedBeliefState(matrix_recovery=False)
        initial = state.role_posterior(setup, ())
        self.assertTrue(any(dict(w.roles)["girl"] != "brain" for w, _ in initial))
        posterior = state.role_posterior(replace(setup, known_roles=(("girl", "brain"),)), ())
        self.assertTrue(posterior)
        self.assertTrue(all(dict(w.roles)["girl"] == "brain" for w, _ in posterior))

    def virus_game(self):
        return Game({"id": "query-virus", "title": "query", "module": "BTX", "days": 2, "loops": 2,
                     "main_plot": "bomb", "subplots": ["lurking", "virus"],
                     "cast": {"girl": "witch", "doctor": "serial", "student": "friend",
                              "maiden": "conspiracy", "patient": "ordinary"}, "incidents": []})

    def test_actual_virus_query_keeps_true_initial_ordinary_world(self):
        game = self.virus_game()
        game._change("patient", "paranoia", 3)
        self.assertEqual(game.roles["patient"], "serial")
        learn_role(game, {"target": "patient"})
        view = game.protagonist_team_view()
        setup = PublicEvidence.from_view(view)
        self.assertEqual(dict(setup.known_roles)["patient"], "serial")
        self.assertNotIn("patient", dict(setup.known_initial_roles))
        truth = HiddenWorldHypothesis.from_scenario(game.scenario)
        self.assertGreater(RolePosteriorTarget(setup).weight(truth, ()), 0)
        matrix = BeliefMatrixProjection.from_view(view, ())
        self.assertEqual(matrix.roles["patient"]["ordinary"].hard_status, HardStatus.UNKNOWN)
        draws = MatrixWorldSampler().propose_roles(setup, (), 64, rng=random.Random(8))
        self.assertTrue(any(dict(p.world.roles)["patient"] == "ordinary" for p in draws))
        self.assertTrue(all(dict(p.world.roles)["patient"] != "ordinary" or "virus" in p.world.subplots
                            for p in draws))

    def test_safe_initial_deduction_survives_later_transformed_query(self):
        game = self.virus_game()
        learn_role(game, {"target": "patient"})
        self.assertEqual(game.protagonist_knowledge["initial_roles"]["patient"], "ordinary")
        for viewer in ("m", "spectator"):
            projection = game.view(viewer)
            self.assertNotIn("protagonist_knowledge", projection)
            event = projection["events"][-1]
            self.assertEqual(event["kind"], "private_information_gained")
            self.assertNotIn("role", event)
            self.assertNotIn("initial_roles", event)
        game._change("patient", "paranoia", 3)
        learn_role(game, {"target": "patient"})
        view = game.protagonist_team_view()
        setup = PublicEvidence.from_view(view)
        self.assertEqual(dict(setup.known_roles)["patient"], "serial")
        self.assertEqual(dict(setup.known_initial_roles)["patient"], "ordinary")
        matrix = BeliefMatrixProjection.from_view(view, ())
        self.assertEqual(matrix.roles["patient"]["ordinary"].hard_status, HardStatus.ALWAYS)
        draws = MatrixWorldSampler().propose_roles(setup, (), 32, rng=random.Random(1))
        self.assertTrue(draws)
        self.assertTrue(all(dict(p.world.roles)["patient"] == "ordinary" and "virus" in p.world.subplots
                            for p in draws))

    def test_original_part_timer_current_query_does_not_reveal_initial_role(self):
        game = Game({"id": "original-temp", "title": "temp", "module": "FS", "days": 2,
                     "loops": 2, "main_plot": "avenger", "subplots": ["rumor"],
                     "cast": {"part_timer": "brain", "maiden": "conspiracy", "doctor": "ordinary"},
                     "incidents": []})
        self.assertEqual(game.roles["part_timer"], "ordinary")
        learn_role(game, {"target": "part_timer"})
        view = game.protagonist_team_view()
        setup = PublicEvidence.from_view(view)
        self.assertNotIn("part_timer", dict(setup.known_roles))
        self.assertNotIn("part_timer", dict(setup.known_initial_roles))
        truth = HiddenWorldHypothesis.from_scenario(game.scenario)
        self.assertGreater(RolePosteriorTarget(setup).weight(truth, ()), 0)
        self.assertNotEqual(BeliefMatrixProjection.from_view(view, ()).roles[
            "part_timer"]["brain"].hard_status, HardStatus.NEVER)
