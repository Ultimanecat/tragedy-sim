from dataclasses import replace
import unittest

from benchmarks.ai_matrix_posterior_accuracy import compare_case, marginals, posterior_errors, printed_worlds, reference_posterior
from tests.test_belief_posterior import evidence
from tragedy_sim.belief import HiddenWorldHypothesis
from tragedy_sim.witness import PublicWitness


class PosteriorAccuracyTests(unittest.TestCase):
    def test_reference_and_small_exact_paths_match_with_hard_knowledge(self):
        setup = replace(evidence(), known_plots=("avenger", "rumor"))
        worlds = printed_worlds(setup)
        observed = replace(setup, known_initial_roles=(("girl", "brain"),))
        reference = reference_posterior(observed, (), worlds)
        self.assertEqual(len(reference), 3)
        self.assertTrue(all(dict(world.roles)["girl"] == "brain" for world, _ in reference))
        row = compare_case("small", observed, (), worlds, trials=2, capacity=192)
        for variant in row["summary"].values():
            self.assertEqual(variant["mean_role_tv"], 0)
            self.assertEqual(variant["plot_tv"], 0)

    def test_distance_includes_missing_support_and_counts_joint_identities(self):
        first = HiddenWorldHypothesis("a", "avenger", ("hideous",),
                                      (("girl", "brain"), ("doctor", "curmudgeon")), ())
        second = HiddenWorldHypothesis("b", "avenger", ("rumor",),
                                       (("girl", "ordinary"), ("doctor", "brain")), ())
        reference = marginals(((first, 3), (second, 1)))
        errors = posterior_errors(reference, marginals(((second, 1),)))
        self.assertEqual(errors["mean_role_tv"], 0.75)
        self.assertEqual(errors["plot_tv"], 0.75)
        self.assertEqual(errors["optional_count_tv"], 0.75)
        self.assertEqual(reference["optional"], {0: 0.25, 1: 0.75})
        with self.assertRaises(ValueError):
            marginals(())

    def test_reference_applies_witness_and_rejects_unsupported_diagnostics(self):
        setup = replace(evidence(), known_plots=("avenger", "rumor"))
        worlds = printed_worlds(setup)
        hard = PublicWitness("role_is", "girl", "brain", 1, 1, "query", "test")
        self.assertEqual(len(reference_posterior(setup, (hard,), worlds)), 3)
        with self.assertRaises(ValueError):
            printed_worlds(replace(setup, schedule=((1, "suicide"),)))
