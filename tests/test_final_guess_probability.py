"""Independent printed enumeration verifies cast-marginal weighted counting."""

from collections import Counter
from dataclasses import replace
from math import fsum, prod
import unittest
from unittest.mock import patch

from tragedy_sim.final_guess_probability import JointGuessProbabilitySolver
from tragedy_sim.witness import FsbtxWitnessMatcher, PublicWitness, WitnessStrength
from tests.test_belief_posterior import evidence, enumerate_printed
from tests.test_role_support_solver import independent_extra_casts


def reference(setup, facts=()):
    initial = replace(setup, known_roles=(), known_initial_roles=(), known_plots=(),
                      known_culprits=(), schedule=())
    worlds = (independent_extra_casts(initial) if {"irregular", "copycat"} & set(initial.characters)
              else enumerate_printed(initial))
    sizes = Counter((w.main_plot, w.subplots) for w in worlds)
    matcher, masses = FsbtxWitnessMatcher(), Counter()
    for world in worlds:
        if (setup.matches_roles(world.main_plot, world.subplots, world.roles)
                and matcher.matches(world, facts)):
            masses[world.roles] += 2 ** matcher.soft_score(world, facts) / sizes[world.main_plot, world.subplots]
    total = fsum(masses.values())
    return masses, total


class FinalGuessProbabilityTests(unittest.TestCase):
    def assert_reference(self, setup, facts=()):
        masses, total = reference(setup, facts)
        result = JointGuessProbabilitySolver().solve(setup, facts)
        self.assertTrue(result.exact, result.to_dict())
        self.assertAlmostEqual(result.total_mass, total, places=10)
        self.assertEqual(result.support_count, len(masses))
        for cast, mass in masses.items():
            self.assertAlmostEqual(result.probability_for(dict(cast)), mass / total, places=11)
        self.assertAlmostEqual(fsum(result.probability_for(dict(cast)) for cast in masses), 1, places=11)
        best = max(masses, key=lambda cast: (masses[cast], cast))
        # Floating addition of tied latent weights may differ by a few ulps.
        self.assertAlmostEqual(masses[result.best_guess], masses[best], places=11)
        self.assertAlmostEqual(result.best_guess_probability, masses[best] / total, places=11)
        self.assertAlmostEqual(result.probability_for(dict(result.best_guess)), result.best_guess_probability, places=11)
        return result

    def test_entire_fs_btx_space_and_latent_plot_aggregation(self):
        for module in ("FS", "BTX"):
            with self.subTest(module=module), patch(
                    "tragedy_sim.belief.FactorizedBeliefState.exact_role_map",
                    side_effect=AssertionError("top MAP representatives are not a partition")):
                self.assert_reference(evidence(module))

    def test_hard_soft_and_repeated_capped_evidence(self):
        for module in ("FS", "BTX"):
            facts = (PublicWitness("role_pressure", "brain", {"candidates": ["doctor", "girl"]},
                                   1, 1, "test", "hard"),
                     PublicWitness("role_pressure", "friend", {"candidates": ["doctor"]},
                                   1, 1, "test", "soft", WitnessStrength.SOFT))
            with self.subTest(module=module):
                self.assert_reference(evidence(module), facts)
                self.assert_reference(evidence(module), (facts[0], *(facts[1],) * 30))

    def test_printed_extra_identities_and_gender_constraints(self):
        for module in ("FS", "BTX"):
            for extras in (("copycat",), ("irregular",), ("copycat", "irregular")):
                setup = replace(evidence(module), characters=(*evidence(module).characters, *extras))
                with self.subTest(module=module, extras=extras):
                    self.assert_reference(setup)

    def test_extra_partitions_remain_disjoint_after_public_role_constraints(self):
        setup = replace(evidence("BTX"), characters=(*evidence("BTX").characters, "copycat", "irregular"))
        for fact in (
            PublicWitness("role_in", "copycat", ["ordinary", "friend"], 1, 1, "test", "test"),
            PublicWitness("role_pressure", "friend", {"candidates": ["irregular", "girl"]},
                          1, 1, "test", "test", WitnessStrength.SOFT),
            PublicWitness("mandatory_serial_route", "death", {
                "serial": ["copycat"], "virus_ordinary": ["doctor"]}, 1, 1, "test", "test"),
        ):
            with self.subTest(kind=fact.kind):
                self.assert_reference(setup, (fact,))

    def test_large_extra_cast_counts_without_full_identity_enumeration(self):
        from tragedy_sim import Game
        from tragedy_sim.belief import PublicEvidence
        from tragedy_sim.belief_posterior import RolePosteriorTarget
        from tragedy_sim.scenario_library import ScenarioLibrary
        library = ScenarioLibrary()
        for sid, cast_count in (("official-tragic-aiplay-btx-02g", 763140),
                                ("community-tragic-aiplay-btx-41", 27370080)):
            with self.subTest(scenario=sid):
                setup = PublicEvidence.from_view(Game(library.get(sid)).protagonist_team_view())
                result = JointGuessProbabilitySolver(node_limit=1000).solve(setup)
                self.assertTrue(result.exact, result.to_dict())
                self.assertEqual(result.support_count, cast_count)
                self.assertLess(result.nodes, 1000)
                # With no evidence, every latent plot's prior sums to one.
                self.assertAlmostEqual(result.total_mass,
                                       len(RolePosteriorTarget(setup).plot_sizes), places=10)

    def test_current_and_initial_identity_are_distinct_conditions(self):
        setup = replace(evidence("BTX"), known_roles=(("girl", "serial"),),
                        known_plots=("virus",))
        result = self.assert_reference(setup)
        masses, _ = reference(setup)
        self.assertTrue(any(dict(cast)["girl"] == "ordinary" for cast in masses))
        self.assertTrue(any(dict(cast)["girl"] == "serial" for cast in masses))
        initial = replace(setup, known_initial_roles=(("girl", "ordinary"),))
        self.assert_reference(initial)
        current_fact = PublicWitness("role_is", "girl", "serial", 1, 1, "test", "test")
        self.assert_reference(evidence("BTX"), (current_fact,))
        self.assertGreater(result.probability_for(dict(result.best_guess)), 0)

    def test_complete_identity_probability_is_not_product_of_marginals(self):
        setup = evidence("BTX")
        result = self.assert_reference(setup)
        masses, total = reference(setup)
        guess = dict(result.best_guess)
        marginal_product = prod(fsum(mass for cast, mass in masses.items()
                                     if dict(cast)[cid] == role) / total
                                for cid, role in guess.items())
        self.assertNotAlmostEqual(result.best_guess_probability, marginal_product, places=7)

    def test_incident_dimension_cancels_if_feasible_and_fails_if_empty(self):
        setup = replace(evidence(), days=2, schedule=((1, "suicide"), (2, "hospital")))
        plain = JointGuessProbabilitySolver().solve(setup)
        fact = PublicWitness("culprit_is", "1", "doctor", 1, 1, "incident", "test")
        known = JointGuessProbabilitySolver().solve(setup, (fact,))
        self.assertEqual(plain.best_guess_probability, known.best_guess_probability)
        self.assertEqual(plain.total_mass, known.total_mass)
        conflict = JointGuessProbabilitySolver().solve(setup, (
            fact, replace(fact, subject="2")))
        self.assertEqual(conflict.status, "no_compatible_worlds")
        self.assertIsNone(conflict.best_guess_probability)

    def test_empty_limit_and_unknown_factors_never_return_fake_probabilities(self):
        setup = evidence()
        for result, status in (
            (JointGuessProbabilitySolver(node_limit=1).solve(setup), "work_limit"),
            (JointGuessProbabilitySolver().solve(replace(setup, module="MZ")), "unsupported_module"),
            (JointGuessProbabilitySolver().solve(setup, (PublicWitness(
                "future_cross_factor", "girl", True, 1, 1, "test", "test"),)), "unsupported_witness"),
            (JointGuessProbabilitySolver().solve(replace(setup, known_initial_roles=(
                ("girl", "brain"), ("doctor", "brain"), ("maiden", "brain"), ("student", "brain")))),
             "no_compatible_worlds"),
        ):
            with self.subTest(status=status):
                self.assertEqual(result.status, status)
                self.assertIsNone(result.total_mass)
                self.assertIsNone(result.probability_for(dict.fromkeys(setup.characters, "ordinary")))
        for value in (0, -1, True, "1"):
            with self.subTest(limit=value), self.assertRaises(ValueError):
                JointGuessProbabilitySolver(node_limit=value)

    def test_guess_queries_are_complete_read_only_and_can_be_impossible(self):
        result = JointGuessProbabilitySolver().solve(evidence())
        before = result.to_dict()
        with self.assertRaises(ValueError):
            result.probability_for({"girl": "key"})
        self.assertEqual(result.probability_for(dict.fromkeys(evidence().characters, "brain")), 0)
        self.assertEqual(result.to_dict(), before)

    def test_loop_end_disjunction_uses_every_required_character(self):
        setup = evidence("BTX")
        fact = PublicWitness("loop_end_plot_explanation", "BTX", {
            "location_intrigue": {"hospital": 2}, "initial_locations": {"doctor": "hospital"},
            "character_intrigue": {"girl": 2}, "butterfly_happened": False},
            1, 1, "loop_end", "test")
        self.assert_reference(setup, (fact,))

    def test_role_route_predicates_have_sound_partition_dependencies(self):
        cases = (
            ("role_route_pressure", "death", {"key": ["girl"], "factor": ["girl"]}),
            ("mastermind_ability_route", "death", {"roles": {"killer": ["doctor"]}, "plots": ["sign"]}),
            ("mandatory_serial_route", "death", {"serial": ["doctor"], "virus_ordinary": ["girl"]}),
            ("day_end_death_companion", "girl", {"character": "doctor", "virus_eligible": True}),
            ("day_end_killer_candidate", "girl", "doctor"),
            ("loss_after_death", "girl", {"factor_key_possible": True}),
            ("joint_plot_role_pressure", "sign", {"role": "key", "candidates": ["girl", "student"]}),
        )
        for module in ("FS", "BTX"):
            for kind, subject, value in cases:
                with self.subTest(module=module, kind=kind):
                    fact = PublicWitness(kind, subject, value, 1, 1, "test", "test", WitnessStrength.SOFT)
                    self.assert_reference(evidence(module), (fact,))

    def test_special_character_printed_and_query_constraints(self):
        for characters in (("little_sister", "ai", "maiden", "student"),
                           ("part_timer", "girl", "doctor", "student")):
            for module in ("FS", "BTX"):
                with self.subTest(characters=characters, module=module):
                    self.assert_reference(replace(evidence(module), characters=characters))


if __name__ == "__main__":
    unittest.main()
