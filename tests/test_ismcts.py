"""Public-information protagonist ISMCTS tests."""

import random
import unittest

from tragedy_sim import Game
from tragedy_sim.ismcts import IsmctsProtagonistAgent, PublicStateDeterminizer
from tragedy_sim.belief import ConstraintBeliefSampler, PublicEvidence
from tragedy_sim.scenario import example_scenario
from tragedy_sim.search import SearchBudget


def advance_to_protagonists(game: Game) -> Game:
    while game.state.phase != "protagonists":
        game = game.search_transition(game.search_actions(game.controller)[0])
    return game


class IsmctsTests(unittest.TestCase):
    def test_determinized_world_matches_public_board_and_not_scenario_identity(self):
        actual = advance_to_protagonists(Game(example_scenario("BTX")))
        view = actual.view("a")
        view["scenario_id"] = "forbidden-real-id"
        evidence = PublicEvidence.from_view(view)
        hypothesis = ConstraintBeliefSampler().sample(
            evidence, 1, rng=random.Random(8))[0]
        particle = PublicStateDeterminizer().determinize(
            hypothesis, evidence, view, rng=random.Random(9))
        self.assertIsNotNone(particle)
        self.assertNotEqual(particle.scenario["id"], "forbidden-real-id")
        self.assertEqual(particle.state.locations, actual.state.locations)
        self.assertEqual(particle.state.phase, "protagonists")
        self.assertEqual([(item.actor, item.target) for item in particle.state.pending],
                         [(item["actor"], item["target"]) for item in view["pending"]])

    def test_agent_returns_a_supplied_offer_and_records_information_set_stats(self):
        game = advance_to_protagonists(Game(example_scenario("FS")))
        view = game.view("a")
        offers = [offer.to_dict() for offer in game.action_offers("a")]
        agent = IsmctsProtagonistAgent(
            SearchBudget(node_limit=8, rollout_depth=4, seed=3),
            particle_count=4, rng_seed=7)
        chosen = agent.choose_action(participant="a", view=view, offers=offers)
        self.assertIn(chosen, offers)
        self.assertEqual(agent.last_trace.strategy, "public_fs_btx_so_ismcts")
        self.assertGreater(agent.last_trace.particles, 0)
        self.assertTrue(any(item["visits"] for item in agent.last_trace.root_actions))
        self.assertTrue(all("availability" in item
                            for item in agent.last_trace.root_actions))

    def test_unsupported_phase_falls_back_without_hidden_state(self):
        game = Game(example_scenario("MZ"))
        offer = {"id": "x", "actor": "a", "type": "next",
                 "parameters": {}, "label": "next"}
        agent = IsmctsProtagonistAgent(particle_count=2)
        self.assertEqual(agent.choose_action(
            participant="a", view=game.view("a"), offers=[offer]), offer)
        self.assertEqual(agent.last_trace.fallback, "unsupported_module")


if __name__ == "__main__":
    unittest.main()
