"""Joint mastermind planning stays legal and leaves real state untouched."""

import unittest

from tragedy_sim import Game
from tragedy_sim.joint_mastermind import JointPlanMastermindAgent
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.search import SearchBudget


class JointMastermindTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
