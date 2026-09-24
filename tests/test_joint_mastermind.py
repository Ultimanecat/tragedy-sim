"""Joint mastermind planning stays legal and leaves real state untouched."""

import random
import unittest
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

from tragedy_sim import Game
from tragedy_sim.ai import RiskAwareProtagonistAgent
from tragedy_sim.joint_mastermind import (JointPlanMastermindAgent,
                                         _PublicReplyEvaluator)
from tragedy_sim.oracle_protagonist import OracleProtagonistAgent
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.search import SearchBudget


class JointMastermindTests(unittest.TestCase):
    def test_fs01_routes_include_serial_isolation_before_intrigue(self):
        game = Game(ScenarioLibrary().get("official-fs-01-first-script"))
        game = game.search_transition(game.search_actions("m")[0])
        agent = JointPlanMastermindAgent(SearchBudget(node_limit=8))
        self.assertEqual(agent._routes(game)[0][0], ("v", "girl"))

    def test_fs02_routes_cover_plot_and_future_hospital_pressure(self):
        game = Game(ScenarioLibrary().get("official-fs-02-prevailing-secrecy"))
        game = game.search_transition(game.search_actions("m")[0])
        agent = JointPlanMastermindAgent(SearchBudget(node_limit=8))
        route = agent._routes(game)[0]
        self.assertEqual(route[:2], (("i2", "school"), ("i1", "hospital")))

    def test_three_card_plan_is_legal_reproducible_and_nonmutating(self):
        game = Game(ScenarioLibrary().get("silent-town-fs"))
        game = game.search_transition(game.search_actions("m")[0])
        before = game.state_key("m")
        budget = SearchBudget(node_limit=8, rollout_depth=8, seed=7)
        first = JointPlanMastermindAgent(budget, reply_nodes=6)
        second = JointPlanMastermindAgent(budget, reply_nodes=6)
        chosen_a = first.search(game)
        chosen_b = second.search(game)
        self.assertEqual(chosen_a.command, chosen_b.command)
        self.assertEqual(game.state_key("m"), before)
        self.assertEqual(first.last_trace.nodes, 8)
        self.assertEqual(first.last_trace.strategy, first.plan_name)
        self.assertIn(chosen_a, game.action_offers("m"))
        world = game.search_transition(chosen_a.command)
        for _ in range(2):
            choice = first.search(world)
            self.assertIn(choice, world.action_offers("m"))
            self.assertEqual(first.last_trace.stop_reason, "joint_plan_followup")
            world = world.search_transition(choice.command)
        self.assertEqual(world.state.phase, "protagonists")

    def test_btx_three_card_plan_stays_legal_and_nonmutating(self):
        game = Game(ScenarioLibrary().get(
            "official-btx-09-those-with-antibodies"))
        game = game.search_transition(game.search_actions("m")[0])
        before = game.state_key("m")
        agent = JointPlanMastermindAgent(
            SearchBudget(node_limit=4, rollout_depth=6, seed=3),
            reply_nodes=4)
        self.assertTrue(agent._placement_phase(game))
        world = game
        for index in range(3):
            choice = agent.search(world)
            self.assertIn(choice, world.action_offers("m"))
            if index:
                self.assertEqual(agent.last_trace.stop_reason,
                                 "joint_plan_followup")
            world = world.search_transition(choice.command)
        self.assertEqual(world.state.phase, "protagonists")
        self.assertEqual(game.state_key("m"), before)

    def test_reply_search_receives_remaining_joint_deadline(self):
        game = Game(ScenarioLibrary().get("silent-town-fs"))
        game = game.search_transition(game.search_actions("m")[0])
        agent = JointPlanMastermindAgent(SearchBudget(node_limit=4), reply_nodes=8,
                                        reply_model="hidden")
        bundle = agent._candidate(game, 0, random.Random(0))
        budgets = []

        class FakeOracle:
            last_trace = None

            def __init__(self, budget, **kwargs):
                budgets.append(budget)

            def choose_game_action(self, **kwargs):
                return None

            def _offer(self, action):
                return action

            def _day_score(self, *args):
                return 0.0, True

        with patch("tragedy_sim.joint_mastermind.HiddenCardOracleProtagonistAgent",
                   FakeOracle):
            agent._evaluate(game, bundle, 0, deadline=perf_counter() + 0.5)
        self.assertEqual(len(budgets), 1)
        self.assertIsNotNone(budgets[0].time_limit_ms)
        self.assertGreater(budgets[0].time_limit_ms, 0)
        self.assertLessEqual(budgets[0].time_limit_ms, 500)
        self.assertLessEqual(budgets[0].node_limit, 3)

    def test_public_reply_uses_only_team_view_and_keeps_oracle_as_ablation(self):
        game = Game(ScenarioLibrary().get("official-fs-01-first-script"))
        game = game.search_transition(game.search_actions("m")[0])
        agent = JointPlanMastermindAgent(SearchBudget(node_limit=4, seed=0))
        self.assertEqual(agent.reply_model, "public")
        bundle = agent._candidate(game, 0, random.Random(0))
        seen_views = []
        original_choose = RiskAwareProtagonistAgent.choose_action

        def checked_choose(policy, *, participant, view, offers):
            self.assertEqual(participant, "team")
            self.assertNotIn("secret", view)
            self.assertNotIn("cast", view)
            seen_views.append(view)
            return original_choose(policy, participant=participant,
                                   view=view, offers=offers)

        with (patch("tragedy_sim.joint_mastermind.HiddenCardOracleProtagonistAgent",
                    side_effect=AssertionError("script-aware oracle used")),
              patch("tragedy_sim.joint_mastermind.RiskAwareProtagonistAgent.choose_action",
                    new=checked_choose)):
            score = agent._evaluate(game, bundle, 0)
        self.assertIsInstance(score, float)
        self.assertEqual(len(seen_views), 3)

    def test_public_reply_stops_before_final_guess_without_script_peek(self):
        evaluator = _PublicReplyEvaluator(SearchBudget(), 0)
        self.assertFalse(evaluator.script_aware_rollout)
        world = SimpleNamespace(state=SimpleNamespace(phase="final_guess"))
        self.assertTrue(evaluator._horizon_reached(world, 0, 1, 1))

    def test_final_guess_cutoff_scores_entire_actual_guess_from_public_view(self):
        root = {"events": [{"kind": "public_prior"}]}
        evaluator = _PublicReplyEvaluator(
            SearchBudget(node_limit=1), 0, root_view=root,
            information_weight=0.02)

        class FinalWorld:
            state = SimpleNamespace(phase="final_guess")
            controller = "p1"
            roles = {"girl": "key", "boy": "ordinary"}

            def protagonist_team_view(self):
                return {"phase": "final_guess", "events": [],
                        "protagonist_knowledge": {"roles": {"girl": "key"}}}

            def search_actions(self, actor):
                return [{"actor": actor, "action": "guess_all", "guesses": {}}]

        seen = []

        def guess(policy, *, participant, view, offers):
            self.assertEqual(participant, "team")
            self.assertEqual(view["protagonist_knowledge"], {})
            self.assertEqual([event["kind"] for event in view["events"]],
                             ["public_prior", "public_new"])
            seen.append(view)
            return {"arguments": {"guesses": {
                "girl": "key", "boy": "ordinary"}}}

        with patch.object(ParticleEnsembleProtagonistAgent, "choose_action",
                          new=guess):
            self.assertEqual(evaluator._cutoff_value_with_events(
                FinalWorld(), 1, [{"kind": "public_new"}]), 1.0)
        self.assertEqual(len(seen), 1)

        with patch.object(ParticleEnsembleProtagonistAgent, "choose_action",
                          return_value={"arguments": {"guesses": {
                              "girl": "key", "boy": "killer"}}}):
            self.assertEqual(evaluator._cutoff_value_with_events(
                FinalWorld(), 1, []), -1.0)

    def test_entropy_tiebreak_favors_keeping_red_uncertain(self):
        world = SimpleNamespace(state=SimpleNamespace(phase="day_end"),
                                winner=None)
        evaluator = _PublicReplyEvaluator(
            SearchBudget(), 0, root_view={"events": []},
            information_weight=0.02)
        with (patch.object(evaluator, "_role_entropy", side_effect=[0.2, 0.8]),
              patch.object(OracleProtagonistAgent, "_cutoff_value",
                           return_value=0.4),
              patch.object(evaluator, "_public_cutoff_view", return_value={})):
            self.assertAlmostEqual(
                evaluator._cutoff_value_with_events(world, 1, []), 0.388)

    def test_role_entropy_falls_after_public_identity_is_fixed(self):
        game = Game(ScenarioLibrary().get(
            "official-btx-09-those-with-antibodies"))
        view = game.protagonist_team_view()
        evaluator = _PublicReplyEvaluator(SearchBudget(), 0)
        before = evaluator._role_entropy(view)
        view["known_roles"]["journalist"] = {"role": "ordinary"}
        self.assertLess(evaluator._role_entropy(view), before)

    def test_belief_reply_samples_public_worlds_without_private_result(self):
        game = Game(ScenarioLibrary().get(
            "official-btx-09-those-with-antibodies"))
        game = game.search_transition(game.search_actions("m")[0])
        game.protagonist_knowledge["roles"] = {"journalist": "time_traveler"}
        agent = JointPlanMastermindAgent(
            SearchBudget(node_limit=4, rollout_depth=6, seed=0),
            reply_model="belief")
        bundle = agent._candidate(game, 0, random.Random(0))
        seen = []
        original_choose = ParticleEnsembleProtagonistAgent.choose_action

        def checked_choose(policy, *, participant, view, offers):
            self.assertEqual(participant, "team")
            self.assertNotIn("secret", view)
            self.assertEqual(view["protagonist_knowledge"], {})
            seen.append(view)
            return original_choose(policy, participant=participant,
                                   view=view, offers=offers)

        with patch.object(ParticleEnsembleProtagonistAgent, "choose_action",
                          new=checked_choose):
            score = agent._evaluate(game, bundle, 1)
        self.assertIsInstance(score, float)
        self.assertEqual(len(seen), 3)
        self.assertEqual(sum(event.get("kind") == "card_placed"
                             and event.get("actor") == "m"
                             for event in seen[0]["events"]), 3)

    def test_belief_root_search_resamples_replies_and_returns_legal_plan(self):
        game = Game(ScenarioLibrary().get(
            "official-btx-09-those-with-antibodies"))
        game = game.search_transition(game.search_actions("m")[0])
        before = game.state_key("m")
        agent = JointPlanMastermindAgent(
            SearchBudget(node_limit=4, rollout_depth=6, seed=5),
            reply_model="belief")
        choice = agent.search(game)
        self.assertIn(choice, game.action_offers("m"))
        self.assertEqual(agent.last_trace.strategy, "joint_belief_root_mcts")
        self.assertEqual(agent.last_trace.nodes, 4)
        self.assertLessEqual(agent.last_trace.expanded_actions, 2)
        self.assertEqual(game.state_key("m"), before)


if __name__ == "__main__":
    unittest.main()
