"""Information-boundary tests for C3 hidden-world sampling."""

from copy import deepcopy
import random
import unittest

from tragedy_sim import Game
from tragedy_sim.belief import (BeliefParticleFilter, CatalogBeliefSampler,
                                ConstraintBeliefSampler,
                                HiddenWorldHypothesis, ParticleReplayer,
                                ObservationParticleAdvancer, PublicEvidence,
                                PublicSnapshot)
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
            evidence.module, evidence.days, evidence.loops, evidence.table_talk,
            evidence.characters, evidence.schedule,
            ((evidence.characters[0], "not-a-role"),), (), ())
        self.assertEqual(sampler.sample(impossible, 2, rng=random.Random(1)), ())

    def test_invalid_particle_count_is_rejected(self):
        evidence = PublicEvidence.from_view(Game(example_scenario("FS")).view("a"))
        with self.assertRaises(ValueError):
            CatalogBeliefSampler().sample(evidence, 0, rng=random.Random(1))


class ConstraintBeliefSamplerTests(unittest.TestCase):
    def test_generates_multiple_valid_worlds_without_catalog_identity(self):
        game = Game(example_scenario("BTX"))
        evidence = PublicEvidence.from_view(game.view("a"))
        worlds = ConstraintBeliefSampler().sample(
            evidence, 12, rng=random.Random(21))
        self.assertEqual(len(worlds), 12)
        self.assertGreater(len({world.main_plot for world in worlds}), 1)
        self.assertTrue(all(set(dict(world.roles)) == set(evidence.characters)
                            for world in worlds))
        self.assertTrue(all(tuple((day, public) for day, _, public, _ in world.incidents)
                            == evidence.schedule for world in worlds))
        self.assertTrue(all(world.scenario_id.startswith("belief-") for world in worlds))

    def test_public_reveals_are_hard_constraints(self):
        view = Game(example_scenario("BTX")).view("a")
        view["known_roles"] = {"girl": {"role": "key", "loop": 1, "day": 1}}
        view["known_culprits"] = {"2": "doctor"}
        view["known_plots"] = ["rumor"]
        evidence = PublicEvidence.from_view(view)
        worlds = ConstraintBeliefSampler().sample(
            evidence, 8, rng=random.Random(4))
        self.assertEqual(len(worlds), 8)
        for world in worlds:
            self.assertEqual(dict(world.roles)["girl"], "key")
            self.assertIn("rumor", world.subplots)
            self.assertEqual(next(culprit for day, _, _, culprit in world.incidents
                                  if day == 2), "doctor")

    def test_generation_is_seeded_across_all_rulesets(self):
        for module in ("FS", "BTX", "MZ", "MC", "HSA", "WM", "AHR", "LL"):
            with self.subTest(module=module):
                evidence = PublicEvidence.from_view(
                    Game(example_scenario(module)).view("a"))
                first = ConstraintBeliefSampler().sample(
                    evidence, 3, rng=random.Random(7))
                second = ConstraintBeliefSampler().sample(
                    evidence, 3, rng=random.Random(7))
                self.assertEqual(first, second)
                self.assertEqual(len(first), 3)


class ParticleReplayTests(unittest.TestCase):
    def test_public_snapshot_ignores_identity_labels_and_localized_messages(self):
        view = Game(example_scenario("BTX")).view("a")
        original = PublicSnapshot.from_view(view)
        changed = dict(view)
        changed["scenario_id"] = "not-evidence"
        changed["title"] = "not-evidence"
        changed["language"] = "en"
        changed["labels"] = {"not": "evidence"}
        changed["events"] = [dict(event, message="translated", timepoint="translated")
                             for event in view["events"]]
        self.assertEqual(PublicSnapshot.from_view(changed), original)
        self.assertEqual(PublicSnapshot.from_view(
            Game(example_scenario("BTX")).view("a", language="en")), original)
        self.assertEqual(len(original.digest), 16)

        changed_counter = deepcopy(view)
        changed_counter["characters"]["girl"]["intrigue"] += 1
        self.assertNotEqual(PublicSnapshot.from_view(changed_counter), original)

    def test_actual_particle_replays_to_the_same_public_snapshot(self):
        initial = Game(example_scenario("FS"))
        game = initial
        for _ in range(8):
            action = game.search_actions(game.controller)[0]
            game = game.transition(action).game
        evidence = PublicEvidence.from_view(initial.view("a"))
        hypothesis = HiddenWorldHypothesis.from_scenario(initial.scenario)
        result = ParticleReplayer().replay(
            hypothesis, evidence, game.history, viewer="a",
            expected=PublicSnapshot.from_view(game.view("a")))
        self.assertTrue(result.accepted, result.reason)
        self.assertEqual(result.decisions, len(game.history))
        self.assertEqual(PublicSnapshot.from_view(result.game.view("a")),
                         PublicSnapshot.from_view(game.view("a")))

    def test_illegal_public_command_and_mismatched_phenomenon_reject_particle(self):
        initial = Game(example_scenario("BTX"))
        evidence = PublicEvidence.from_view(initial.view("a"))
        hypothesis = HiddenWorldHypothesis.from_scenario(initial.scenario)
        illegal = ParticleReplayer().replay(
            hypothesis, evidence,
            [{"actor": "a", "action": "next"}], viewer="a")
        self.assertFalse(illegal.accepted)
        self.assertEqual(illegal.reason, "public_command_illegal")

        impossible_view = deepcopy(initial.view("a"))
        impossible_view["locations"]["school"] = 9
        mismatch = ParticleReplayer().replay(
            hypothesis, evidence, (), viewer="a",
            expected=PublicSnapshot.from_view(impossible_view))
        self.assertFalse(mismatch.accepted)
        self.assertEqual(mismatch.reason, "public_snapshot_mismatch")


class ObservationParticleAdvancerTests(unittest.TestCase):
    def test_hidden_action_is_inferred_from_public_consequence(self):
        game = Game(example_scenario("BTX"))
        command = game.search_actions("m")[0]
        actual = game.transition(command).game
        result = ObservationParticleAdvancer().advance(
            game, viewer="a", observed=PublicSnapshot.from_view(actual.view("a")))
        self.assertEqual(result.tested_actions, 1)
        self.assertEqual(len(result.successors), 1)
        self.assertEqual(PublicSnapshot.from_view(result.successors[0].view("a")),
                         PublicSnapshot.from_view(actual.view("a")))

    def test_unrevealed_card_keeps_all_observationally_equivalent_actions(self):
        game = Game(example_scenario("BTX"))
        game = game.transition(game.search_actions("m")[0]).game
        actual_command = game.search_actions("m")[17]
        actual = game.transition(actual_command).game
        result = ObservationParticleAdvancer().advance(
            game, viewer="a", observed=PublicSnapshot.from_view(actual.view("a")))
        self.assertGreater(result.tested_actions, 20)
        self.assertGreater(len(result.successors), 1)
        self.assertTrue(all(PublicSnapshot.from_view(item.view("a")) ==
                            PublicSnapshot.from_view(actual.view("a"))
                            for item in result.successors))

    def test_public_command_restricts_branch_and_limits_are_validated(self):
        game = Game(example_scenario("FS"))
        command = game.search_actions("m")[0]
        actual = game.transition(command).game
        advancer = ObservationParticleAdvancer()
        result = advancer.advance(
            game, viewer="a", observed=PublicSnapshot.from_view(actual.view("a")),
            public_command=command)
        self.assertEqual((result.tested_actions, len(result.successors)), (1, 1))
        rejected = advancer.advance(
            game, viewer="a", observed=PublicSnapshot.from_view(actual.view("a")),
            public_command={"actor": "a", "action": "next"})
        self.assertEqual((rejected.tested_actions, rejected.successors), (0, ()))
        with self.assertRaises(ValueError):
            advancer.advance(game, viewer="a",
                             observed=PublicSnapshot.from_view(game.view("a")),
                             max_successors=0)


class ObservationCheckpointTests(unittest.TestCase):
    def test_real_dispatch_records_only_public_snapshot_digests(self):
        game = Game(example_scenario("BTX"))
        initial = game.observation_checkpoints("a")
        self.assertEqual(len(initial), 1)
        self.assertEqual(initial[0],
                         (0, PublicSnapshot.from_view(game.view("a")).digest))
        action = game.search_actions("m")[0]
        game.dispatch("m", action["action"])
        checkpoints = game.observation_checkpoints("a")
        self.assertEqual(len(checkpoints), 2)
        self.assertEqual(checkpoints[-1],
                         (1, PublicSnapshot.from_view(game.view("a")).digest))
        self.assertNotIn("next", repr(checkpoints))

    def test_simulation_does_not_append_real_observation_history(self):
        game = Game(example_scenario("FS"))
        action = game.action_offers("m")[0]
        successor = game.transition(action).game
        self.assertEqual(len(game.observation_checkpoints("a")), 1)
        self.assertEqual(len(successor.observation_checkpoints("a")), 1)

    def test_checkpoint_digest_can_drive_hidden_particle_advance(self):
        game = Game(example_scenario("BTX"))
        action = game.search_actions("m")[0]
        game.dispatch("m", action["action"])
        observed_digest = game.observation_checkpoints("a")[-1][1]
        initial = Game(example_scenario("BTX"))
        result = ObservationParticleAdvancer().advance(
            initial, viewer="a", observed=observed_digest)
        self.assertEqual(len(result.successors), 1)


class BeliefParticleFilterTests(unittest.TestCase):
    @staticmethod
    def initial_particles():
        source = Game(example_scenario("BTX"))
        evidence = PublicEvidence.from_view(source.view("a"))
        hypotheses = ConstraintBeliefSampler().sample(
            evidence, 4, rng=random.Random(31))
        particles = BeliefParticleFilter.materialize(hypotheses, evidence)
        return source, particles

    def test_hidden_wide_branch_is_bounded_without_collapsing_to_one_answer(self):
        source, particles = self.initial_particles()
        first = source.search_actions("m")[0]
        source = source.transition(first).game
        filterer = BeliefParticleFilter(max_particles=12, rng=random.Random(5))
        setup = filterer.advance(
            particles, viewer="a",
            observed=PublicSnapshot.from_view(source.view("a")))
        self.assertEqual(len(setup.particles), len(particles))

        hidden = source.search_actions("m")[23]
        observed_game = source.transition(hidden).game
        result = filterer.advance(
            setup.particles, viewer="a",
            observed=PublicSnapshot.from_view(observed_game.view("a")))
        self.assertEqual(result.input_particles, len(particles))
        self.assertGreater(result.matching_successors, 20)
        self.assertGreater(result.unique_successors, 12)
        self.assertEqual(len(result.particles), 12)
        self.assertGreater(len({item.state_key("m") for item in result.particles}), 1)
        expected = PublicSnapshot.from_view(observed_game.view("a"))
        self.assertTrue(all(PublicSnapshot.from_view(item.view("a")) == expected
                            for item in result.particles))

    def test_resampling_is_seeded_and_contradictions_eliminate_all_particles(self):
        source, particles = self.initial_particles()
        source = source.transition(source.search_actions("m")[0]).game
        particles = BeliefParticleFilter(max_particles=16).advance(
            particles, viewer="a",
            observed=PublicSnapshot.from_view(source.view("a"))).particles
        observed = PublicSnapshot.from_view(
            source.transition(source.search_actions("m")[7]).game.view("a"))

        def keys():
            result = BeliefParticleFilter(
                max_particles=7, rng=random.Random(18)).advance(
                    particles, viewer="a", observed=observed)
            return tuple(item.state_key("m") for item in result.particles)

        sampled = keys()
        self.assertEqual(sampled, keys())
        self.assertEqual(len(sampled), 7)
        impossible = "0" * 16
        rejected = BeliefParticleFilter(max_particles=7).advance(
            particles, viewer="a", observed=impossible)
        self.assertFalse(rejected.particles)
        self.assertEqual(rejected.matching_successors, 0)

    def test_particle_limit_is_validated(self):
        with self.assertRaises(ValueError):
            BeliefParticleFilter(max_particles=0)


if __name__ == "__main__":
    unittest.main()
