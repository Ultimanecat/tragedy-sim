"""Public-boundary and cross-particle regression tests for FS/BTX."""

import unittest

from benchmarks.ai_self_play import _policy_offer
from tragedy_sim import Game
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.scenario import example_scenario
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.search import SearchBudget


def protagonist_position(scenario_id="official-fs-01-first-script"):
    game = Game(ScenarioLibrary().get(scenario_id))
    while game.state.phase != "protagonists":
        game = game.search_transition(game.search_actions(game.controller)[0])
    return game


class ParticleEnsembleTests(unittest.TestCase):
    def test_rollout_horizon_is_validated(self):
        with self.assertRaises(ValueError):
            ParticleEnsembleProtagonistAgent(rollout_horizon="match")
        with self.assertRaises(ValueError):
            ParticleEnsembleProtagonistAgent(mastermind_policy_samples=0)
        with self.assertRaises(ValueError):
            ParticleEnsembleProtagonistAgent(information_reward_weight=-0.1)

    def test_single_policy_sample_retains_seeded_baseline(self):
        game = protagonist_position()
        agent = ParticleEnsembleProtagonistAgent(mastermind_policy_samples=1)
        self.assertEqual(agent._mastermind_strategies(game), (None,))

    def test_multiple_policy_samples_cover_route_list_evenly(self):
        game = protagonist_position()
        agent = ParticleEnsembleProtagonistAgent(mastermind_policy_samples=2)
        options = agent.oracle._mastermind_strategy_options(game)
        selected = agent._mastermind_strategies(game)
        self.assertEqual(selected, (options[0], options[-1]))

    def test_information_shaping_cannot_override_survival(self):
        safe = (1.0, -1.0, 1.0, -1.0, -1.0, "safe")
        attractive_but_dead = (0.75, 1.0, 0.75, 1.0, 1.0, "info")
        best = max((safe, attractive_but_dead),
                   key=ParticleEnsembleProtagonistAgent._evaluation_key)
        self.assertEqual(best[5], "safe")

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
        self.assertEqual(trace.strategy, "public_fs_btx_particle_ensemble")
        self.assertGreaterEqual(trace.evaluated_pairs,
                                trace.iterations * trace.particles)
        self.assertEqual(trace.mastermind_policy_samples, 3)
        self.assertEqual(trace.mastermind_policy_aggregation,
                         "per_world_worst")
        self.assertEqual(trace.information_reward_weight, 0.01)
        self.assertTrue(all(row["policy_rollouts"] >= trace.particles
                            for row in trace.root_actions))
        self.assertTrue(all(0 <= row["information_bonus"] <= 0.012
                            for row in trace.root_actions))
        self.assertTrue(all({"information_future", "information_realized",
                             "information_refusal"} <= set(row)
                            for row in trace.root_actions))
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

    def test_btx_public_view_uses_joint_plan_and_not_fs_fallback(self):
        scenario = next(item["id"] for item in ScenarioLibrary().list("BTX")
                        if item["source"] == "library")
        game = protagonist_position(scenario)
        agent = ParticleEnsembleProtagonistAgent(
            SearchBudget(node_limit=6, rollout_depth=12, seed=11),
            particle_count=4, rng_seed=11)
        offers = [_policy_offer(game, action)
                  for action in game.action_offers(game.controller)]
        chosen = agent.choose_action(
            participant="team", view=game.protagonist_team_view(), offers=offers)
        self.assertIn(chosen, offers)
        self.assertEqual(agent.last_trace.module, "BTX")
        self.assertEqual(agent.last_trace.strategy,
                         "public_fs_btx_particle_ensemble")
        self.assertGreater(agent.last_trace.evaluated_pairs, 0)
        self.assertEqual(len(agent.last_trace.planned_commands), 2)

    def test_loop_horizon_uses_public_followup_policy(self):
        game = protagonist_position()
        agent = ParticleEnsembleProtagonistAgent(
            SearchBudget(node_limit=4, rollout_depth=8, seed=15),
            particle_count=4, rng_seed=15, rollout_horizon="loop")
        offers = [_policy_offer(game, action)
                  for action in game.action_offers(game.controller)]
        chosen = agent.choose_action(
            participant="team", view=game.protagonist_team_view(), offers=offers)
        self.assertIn(chosen, offers)
        self.assertEqual(agent.last_trace.rollout_horizon, "loop")
        self.assertFalse(agent.oracle.script_aware_rollout)
        self.assertTrue(all("horizon_survivals" in row
                            for row in agent.last_trace.root_actions))

    def test_btx_final_guess_uses_joint_role_posterior(self):
        game = Game(example_scenario("BTX"))
        game._start_final_guess()
        agent = ParticleEnsembleProtagonistAgent(
            SearchBudget(node_limit=4, seed=12), particle_count=4,
            rng_seed=12)
        offers = [_policy_offer(game, action)
                  for action in game.action_offers(game.controller)]
        chosen = agent.choose_action(
            participant="team", view=game.protagonist_team_view(), offers=offers)
        self.assertEqual(chosen["type"], "guess_all")
        self.assertEqual(set(chosen["arguments"]["guesses"]), set(game.roles))
        self.assertEqual(agent.last_trace.fallback, "simultaneous_map_guess")
        self.assertTrue(agent.last_trace.belief_setups)
        self.assertEqual(chosen["arguments"]["guesses"],
                         agent.last_trace.belief_setups[0]["roles"])

    def test_btx_irregular_script_does_not_fall_back_to_all_ordinary(self):
        scenario_id = "official-btx-08-mirror-passcode"
        game = protagonist_position(scenario_id)
        agent = ParticleEnsembleProtagonistAgent(
            SearchBudget(node_limit=4, rollout_depth=4, seed=13),
            particle_count=4, rng_seed=13)
        offers = [_policy_offer(game, action)
                  for action in game.action_offers(game.controller)]
        agent.choose_action(participant="team",
                            view=game.protagonist_team_view(), offers=offers)
        self.assertIsNone(agent.last_trace.fallback)
        self.assertGreater(agent.last_trace.evaluated_pairs, 0)

        final = Game(ScenarioLibrary().get(scenario_id))
        final._start_final_guess()
        offers = [_policy_offer(final, action)
                  for action in final.action_offers(final.controller)]
        chosen = agent.choose_action(
            participant="team", view=final.protagonist_team_view(), offers=offers)
        self.assertEqual(agent.last_trace.fallback, "simultaneous_map_guess")
        self.assertTrue(agent.last_trace.belief_roles)
        self.assertTrue(agent.last_trace.belief_setups)
        self.assertNotEqual(set(chosen["arguments"]["guesses"].values()),
                            {"ordinary"})


if __name__ == "__main__":
    unittest.main()
