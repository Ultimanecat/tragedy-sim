"""Joint mastermind planning stays legal and leaves real state untouched."""

import random
import unittest
from time import perf_counter
from unittest.mock import patch

from tragedy_sim import Game
from tragedy_sim.joint_mastermind import JointPlanMastermindAgent
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
        agent = JointPlanMastermindAgent(SearchBudget(node_limit=4), reply_nodes=8)
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


if __name__ == "__main__":
    unittest.main()
