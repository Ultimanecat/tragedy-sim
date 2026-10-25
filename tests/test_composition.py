"""Composition layer tests."""

import unittest

from tragedy_sim.composition import (BeliefSnapshot, ComposedProtagonistAgent,
                                     ParticleInformationPolicy)


class FakeInformation:
    def __init__(self):
        self.calls = 0

    def build(self, *, game, view, offers):
        self.calls += 1
        return BeliefSnapshot((), None, source="fake")  # type: ignore[arg-type]


class FakeAction:
    def __init__(self):
        self.snapshot = None

    def choose(self, *, snapshot, view, offers, participant):
        self.snapshot = snapshot
        return {"action": "next", "actor": participant}


class CompositionTests(unittest.TestCase):
    def test_composed_agent_delegates_information_then_action(self):
        information, action = FakeInformation(), FakeAction()
        agent = ComposedProtagonistAgent(information, action)
        chosen = agent.choose_action(participant="team", view={"phase": "goodwill"},
                                     offers=[{"type": "next", "actor": "team"}])
        self.assertEqual(information.calls, 1)
        self.assertEqual(action.snapshot.source, "fake")
        self.assertEqual(chosen["action"], "next")

    def test_particle_information_policy_validates_source(self):
        with self.assertRaises(ValueError):
            ParticleInformationPolicy(information_policy="unknown")

    def test_particle_information_policy_exposes_components(self):
        policy = ParticleInformationPolicy(particle_count=4, rng_seed=7)
        self.assertIsNotNone(policy.factorized_belief)
        self.assertIsNotNone(policy.compiler)
        self.assertEqual(policy.information_policy, "public")


if __name__ == "__main__":
    unittest.main()
