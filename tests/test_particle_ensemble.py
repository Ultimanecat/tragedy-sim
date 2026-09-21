"""Public-boundary and cross-particle regression tests for the FS planner."""

import unittest

from benchmarks.ai_self_play import _policy_offer
from tragedy_sim import Game
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.search import SearchBudget


def protagonist_position():
    game = Game(ScenarioLibrary().get("official-fs-01-first-script"))
    while game.state.phase != "protagonists":
        game = game.search_transition(game.search_actions(game.controller)[0])
    return game


class ParticleEnsembleTests(unittest.TestCase):
    def test_public_view_yields_legal_three_card_plan_and_posteriors(self):
        game = protagonist_position()
        agent = ParticleEnsembleProtagonistAgent(
            SearchBudget(node_limit=8, rollout_depth=12, seed=3),
            particle_count=4, rng_seed=3)
        view = game.protagonist_team_view()
        offers = [_policy_offer(game, action)
                  for action in game.action_offers(game.controller)]
        chosen = agent.choose_action(participant="team", view=view, offers=offers)
        self.assertIn(chosen, offers)
        trace = agent.last_trace
        self.assertEqual(trace.strategy, "public_fs_particle_ensemble")
        self.assertEqual(trace.evaluated_pairs,
                         trace.iterations * trace.particles)
        self.assertGreater(trace.particles, 0)
        self.assertTrue(trace.belief_roles)
        self.assertTrue(trace.belief_culprits)
        self.assertTrue(trace.belief_dark_cards)
        self.assertTrue(trace.placement_tendencies)
        self.assertAlmostEqual(sum(
            trace.placement_tendencies[0]["card_probabilities"].values()), 1.0)
        self.assertEqual(len(trace.planned_commands), 2)
        self.assertEqual(trace.to_dict()["evaluated_pairs"],
                         trace.evaluated_pairs)

    def test_no_real_script_or_dark_card_argument_is_accepted(self):
        game = protagonist_position()
        agent = ParticleEnsembleProtagonistAgent(
            SearchBudget(node_limit=4, seed=7), particle_count=4, rng_seed=7)
        view = game.protagonist_team_view()
        offers = [_policy_offer(game, action)
                  for action in game.action_offers(game.controller)]
        first = agent.choose_action(participant="team", view=view, offers=offers)
        other = ParticleEnsembleProtagonistAgent(
            SearchBudget(node_limit=4, seed=7), particle_count=4, rng_seed=7)
        second = other.choose_action(participant="team", view=view, offers=offers)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(agent.last_trace.belief_roles,
                         other.last_trace.belief_roles)


if __name__ == "__main__":
    unittest.main()
