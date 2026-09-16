"""Information-boundary tests for C3 hidden-world sampling."""

import random
import unittest

from tragedy_sim import Game
from tragedy_sim.belief import CatalogBeliefSampler, PublicEvidence
from tragedy_sim.scenario import example_scenario


class PublicEvidenceTests(unittest.TestCase):
    def test_evidence_ignores_scenario_identity_and_unrevealed_secrets(self):
        game = Game(example_scenario("BTX"))
        view = game.view("a")
        original = PublicEvidence.from_view(view)

        disguised = dict(view)
        disguised["scenario_id"] = "must-not-be-used"
        disguised["title"] = "must-not-be-used"
        self.assertEqual(PublicEvidence.from_view(disguised), original)
        self.assertFalse(original.known_roles)
        self.assertFalse(original.known_culprits)
        self.assertFalse(original.known_plots)

    def test_catalog_candidates_obey_public_reveals(self):
        game = Game(example_scenario("BTX"))
        view = game.view("a")
        sampler = CatalogBeliefSampler()
        evidence = PublicEvidence.from_view(view)
        candidates = sampler.candidates(evidence)
        self.assertTrue(candidates)
        self.assertIn(game.scenario["id"], {item.scenario_id for item in candidates})

        revealed = dict(view)
        revealed["known_roles"] = {"girl": {"role": "key", "loop": 1, "day": 1}}
        filtered = sampler.candidates(PublicEvidence.from_view(revealed))
        self.assertTrue(filtered)
        self.assertTrue(all(dict(item.roles)["girl"] == "key" for item in filtered))

    def test_sampling_is_seeded_and_empty_sets_do_not_fall_back_to_truth(self):
        view = Game(example_scenario("FS")).view("a")
        sampler = CatalogBeliefSampler()
        evidence = PublicEvidence.from_view(view)
        first = sampler.sample(evidence, 5, rng=random.Random(9))
        second = sampler.sample(evidence, 5, rng=random.Random(9))
        self.assertEqual(first, second)

        impossible = PublicEvidence(
            evidence.module, evidence.days, evidence.loops,
            evidence.characters, evidence.schedule,
            ((evidence.characters[0], "not-a-role"),), (), ())
        self.assertEqual(sampler.sample(impossible, 2, rng=random.Random(1)), ())

    def test_invalid_particle_count_is_rejected(self):
        evidence = PublicEvidence.from_view(Game(example_scenario("FS")).view("a"))
        with self.assertRaises(ValueError):
            CatalogBeliefSampler().sample(evidence, 0, rng=random.Random(1))


if __name__ == "__main__":
    unittest.main()
