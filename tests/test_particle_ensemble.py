"""Public-boundary and cross-particle regression tests for FS/BTX."""

import unittest

from benchmarks.ai_self_play import _policy_offer
from tragedy_sim import Game
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.scenario import example_scenario
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.search import SearchBudget
from tragedy_sim.witness import PublicWitness, WitnessStrength


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
        day_safe = (1.0, -1.0, 1.0, -1.0, -1.0, "day_safe")
        attractive_but_day_risky = (1.0, 1.0, 0.75, 1.0, 1.0,
                                   "day_risky")
        best = max((day_safe, attractive_but_day_risky),
                   key=ParticleEnsembleProtagonistAgent._evaluation_key)
        self.assertEqual(best[5], "day_safe")

    def test_public_board_target_guard_bonus_reads_no_card_face(self):
        agent = ParticleEnsembleProtagonistAgent()
        view = {"locations": {"school": 0, "shrine": 0},
                "pending": [{"actor": "m", "target": "school"}]}
        guarded = ({"card": "fi", "target": "school"},)
        wrong_board = ({"card": "fi", "target": "shrine"},)
        unguarded = ({"card": "g1", "target": "student"},)
        self.assertEqual(agent._location_guard_bonus(guarded, view), 0.08)
        self.assertEqual(agent._location_guard_bonus(wrong_board, view), 0.0)
        self.assertEqual(agent._location_guard_bonus(unguarded, view), 0.0)

    def test_time_traveler_screening_uses_witness_intersection(self):
        witnesses = (
            PublicWitness("role_pressure", "time_traveler",
                          {"candidates": ("girl", "doctor", "patient")},
                          1, 5, "loop_end", "one", WitnessStrength.HARD),
            PublicWitness("role_pressure", "time_traveler",
                          {"candidates": ("doctor", "patient")},
                          2, 5, "loop_end", "two", WitnessStrength.HARD),
        )
        candidates = ParticleEnsembleProtagonistAgent._time_traveler_candidates(
            witnesses)
        self.assertEqual(candidates, ("doctor", "patient"))
        view = {
            "characters": {
                "doctor": {"goodwill": 2, "alive": True},
                "patient": {"goodwill": 1, "alive": True},
            },
            "team_hands": {"a": ["g1"], "b": ["g2"], "c": ["h"]},
        }
        base = ({"actor": "a", "card": "h", "target": "doctor"},
                {"actor": "b", "card": "h", "target": "patient"},
                {"actor": "c", "card": "h", "target": "doctor"})
        bundle = ParticleEnsembleProtagonistAgent._time_traveler_screening_bundle(
            base, view, candidates)
        self.assertIsNotNone(bundle)
        self.assertEqual(bundle[0]["card"], "g1")
        self.assertEqual(bundle[1]["card"], "g2")
        later = ParticleEnsembleProtagonistAgent._time_traveler_screening_bundle(
            base, view, candidates, offset=3)
        self.assertIsNone(later)
        view["characters"]["rich"] = {"goodwill": 0, "alive": True}
        view["characters"]["girl"] = {"goodwill": 0, "alive": True}
        later = ParticleEnsembleProtagonistAgent._time_traveler_screening_bundle(
            base, view, (*candidates, "girl", "rich"), offset=3)
        self.assertIsNotNone(later)
        self.assertEqual(later[0]["target"], "rich")
        offsets = ParticleEnsembleProtagonistAgent._time_traveler_screening_offsets
        self.assertEqual(offsets(tuple("abcde")), (0,))
        self.assertEqual(offsets(tuple("abcdefgh")), (0, 3))
        self.assertEqual(
            ParticleEnsembleProtagonistAgent._time_traveler_screening_bonus(
                bundle, view, candidates), 0.07)
        final_day = {**view, "days": 4, "round": 4}
        partial = ({"card": "g2", "target": "doctor"},)
        final_day["characters"]["doctor"]["goodwill"] = 0
        self.assertEqual(
            ParticleEnsembleProtagonistAgent._time_traveler_screening_bonus(
                partial, final_day, candidates), 0.0)

    def test_threads_risk_requires_public_confirmation(self):
        confirmed = ParticleEnsembleProtagonistAgent._threads_confirmed
        witness = PublicWitness("plot_present", "threads", True,
                                2, 1, "loop_start", "test",
                                WitnessStrength.HARD)
        self.assertFalse(confirmed({"known_plots": []}, ()))
        self.assertTrue(confirmed({"known_plots": ["threads"]}, ()))
        self.assertTrue(confirmed({"known_plots": []}, (witness,)))

    def test_sampling_seed_is_coupled_across_loop_difficulties(self):
        library = ScenarioLibrary()
        standard = Game(library.get(
            "official-btx-02-traditional-ensemble-murder"
        )).protagonist_team_view()
        easy = Game(library.get(
            "official-btx-02-traditional-ensemble-murder-easy"
        )).protagonist_team_view()
        self.assertNotEqual(standard["loops"], easy["loops"])
        self.assertEqual(
            ParticleEnsembleProtagonistAgent._sampling_hash(standard),
            ParticleEnsembleProtagonistAgent._sampling_hash(easy))
        easy["language"] = "ja"
        easy["labels"] = {"student": "学生"}
        easy["events"][0]["message"] = "表示専用"
        self.assertEqual(
            ParticleEnsembleProtagonistAgent._sampling_hash(standard),
            ParticleEnsembleProtagonistAgent._sampling_hash(easy))
        standard["events"].append({
            "kind": "loop_lost", "loop": 1, "round": 7,
            "timing": "loop_end", "remaining": 2,
        })
        easy["events"].append({
            "kind": "loop_lost", "loop": 1, "round": 7,
            "timing": "loop_end", "remaining": 3,
        })
        self.assertEqual(
            ParticleEnsembleProtagonistAgent._sampling_hash(standard),
            ParticleEnsembleProtagonistAgent._sampling_hash(easy))
        easy["round"] += 1
        self.assertNotEqual(
            ParticleEnsembleProtagonistAgent._sampling_hash(standard),
            ParticleEnsembleProtagonistAgent._sampling_hash(easy))

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
                             "information_refusal", "location_guard_bonus",
                             "threads_carryover_risk"}
                            <= set(row)
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

    def test_large_final_guess_uses_exact_space_not_action_particles(self):
        game = Game(ScenarioLibrary().get(
            "official-btx-06-secret-that-was-kept"))
        game._start_final_guess()
        agent = ParticleEnsembleProtagonistAgent(
            SearchBudget(node_limit=1, seed=2), particle_count=4, rng_seed=2)
        offers = [_policy_offer(game, action)
                  for action in game.action_offers(game.controller)]
        chosen = agent.choose_action(
            participant="team", view=game.protagonist_team_view(), offers=offers)
        self.assertEqual(chosen["type"], "guess_all")
        self.assertEqual(agent.last_trace.belief_source, "exact_joint_map")
        self.assertEqual(agent.last_trace.particles, 0)
        self.assertGreater(agent.last_trace.role_candidates, 192)

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
