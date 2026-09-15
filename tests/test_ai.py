"""Baseline and fixed-playbook AI policy tests."""

import random
import unittest

from tragedy_sim.ai import FixedStrategyMastermindAgent, RandomAgent
from tragedy_sim import Game
from tragedy_sim.mcts import FullInformationMctsMastermindAgent
from tragedy_sim.effects.vocabulary import op, option
from tragedy_sim.scenario import example_scenario
from tragedy_sim.search import MastermindEvaluator, SearchBudget, SearchTrace
from tragedy_sim.service import GameService, ServiceError


def offer(action_type, **parameters):
    return {"id": repr((action_type, parameters)), "actor": "m", "type": action_type,
            "parameters": parameters, "label": "test"}


class AiPolicyTests(unittest.TestCase):
    def setUp(self):
        self.view = {
            "round": 1,
            "characters": {
                "girl": {"location": "school", "intrigue": 0, "paranoia": 0,
                         "paranoia_limit": 3},
                "worker": {"location": "city", "intrigue": 0, "paranoia": 0,
                           "paranoia_limit": 2},
                "doctor": {"location": "hospital", "intrigue": 0, "paranoia": 0,
                           "paranoia_limit": 2},
            },
            "secret": {
                "main_plot": "murder_plan",
                "roles": {"girl": "key", "worker": "killer", "doctor": "brain"},
                "incidents": [{"day": 2, "kind": "murder", "culprit": "doctor"}],
            },
        }

    def test_random_agent_always_returns_a_legal_offer(self):
        offers = [offer("next"), offer("play", card="i1", target="school")]
        chosen = RandomAgent(random.Random(3)).choose_action(
            participant="m", view=self.view, offers=offers)
        self.assertIn(chosen, offers)

    def test_assassination_playbook_builds_intrigue_then_moves_killer(self):
        agent = FixedStrategyMastermindAgent(random.Random(1), "key_assassination")
        offers = [offer("play", card="p1a", target="doctor"),
                  offer("play", card="i1", target="girl"),
                  offer("play", card="i2", target="girl")]
        chosen = agent.choose_action(participant="m", view=self.view, offers=offers)
        self.assertEqual(chosen["parameters"], {"card": "i2", "target": "girl"})
        self.assertEqual(agent.plan_name, "key_assassination")

        self.view["characters"]["girl"]["intrigue"] = 2
        self.view["characters"]["worker"]["forbidden"] = ["school"]
        movement = [offer("play", card="h", target="worker"),
                    offer("play", card="h", target="girl")]
        chosen = agent.choose_action(participant="m", view=self.view, offers=movement)
        self.assertEqual(chosen["parameters"], {"card": "h", "target": "girl"})
        self.assertEqual(agent.plan_name, "key_assassination")

    def test_incident_and_plot_paths_use_stable_parameters(self):
        incident = FixedStrategyMastermindAgent(random.Random(2), "incident_pressure")
        offers = [offer("play", card="i1", target="doctor"),
                  offer("play", card="p1a", target="doctor")]
        self.assertEqual(incident.choose_action(
            participant="m", view=self.view, offers=offers)["parameters"]["card"], "p1a")

        plot_view = {**self.view, "secret": {
            **self.view["secret"], "main_plot": "sealed",
        }}
        plot = FixedStrategyMastermindAgent(random.Random(4), "plot_intrigue")
        choices = [offer("play", card="i2", target="school"),
                   offer("play", card="i2", target="shrine")]
        self.assertEqual(plot.choose_action(
            participant="m", view=plot_view, offers=choices)["parameters"]["target"], "shrine")

    def test_playbook_prefers_a_winning_optional_effect(self):
        agent = FixedStrategyMastermindAgent(random.Random(1), "key_assassination")
        offers = [offer("next"), {
            **offer("choose"), "ui": {"choice_key": "killer:character:worker",
                                        "effect": "kill", "target": "girl"},
        }]
        self.assertEqual(agent.choose_action(
            participant="m", view=self.view, offers=offers)["type"], "choose")

    def test_btx_playbooks_reach_mastermind_win_without_counterplay(self):
        for path in ("key_assassination", "incident_pressure"):
            with self.subTest(path=path):
                service = GameService()
                created = service.create_game({"module": "BTX"})
                session = created["session_id"]
                tokens = created["credentials"]["seats"]
                agent = FixedStrategyMastermindAgent(random.Random(1), path)
                for _ in range(500):
                    public = service.get_view(session)["state"]
                    if public["winner"]:
                        break
                    actor = public["controller"]
                    actions = service.get_actions(session, actor, token=tokens[actor])
                    if actor == "m":
                        view = service.get_view(session, actor, token=tokens[actor])["state"]
                        selected = agent.choose_action(
                            participant=actor, view=view, offers=actions["actions"])
                    else:
                        harmless = [item for item in actions["actions"]
                                    if item["type"] == "play"
                                    and item["parameters"]["target"] in {
                                        "hospital", "shrine", "city", "school"}
                                    and item["parameters"]["card"] in {"p1", "g1", "h", "v"}]
                        skip = [item for item in actions["actions"] if item["type"] == "next"]
                        selected = (harmless or skip or actions["actions"])[0]
                    service.dispatch(session, {
                        "action_id": selected["id"], "expected_revision": actions["revision"],
                    }, token=tokens[actor])
                else:
                    self.fail(f"{path} did not finish")
                self.assertEqual(public["winner"], "mastermind")


class SearchInfrastructureTests(unittest.TestCase):
    def test_budget_validation_and_trace_are_json_safe(self):
        budget = SearchBudget(node_limit=20, rollout_depth=8, seed=17)
        self.assertEqual((budget.node_limit, budget.rollout_depth, budget.seed), (20, 8, 17))
        for invalid in (
                {"node_limit": 0}, {"rollout_depth": 0}, {"time_limit_ms": 0},
                {"exploration": -1}, {"seed": 1.5}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                SearchBudget(**invalid)
        trace = SearchTrace("test", 17, SearchTrace.hash_state_key("secret"),
                            20, 8, None, 3, 2, 1, 0.25, "node_limit", "abc")
        self.assertEqual(trace.to_dict()["root_key_hash"],
                         SearchTrace.hash_state_key("secret"))
        self.assertNotIn("secret", repr(trace.to_dict()))

    def test_evaluator_is_bounded_and_recognizes_terminal_winners(self):
        service = GameService()
        created = service.create_game({"module": "BTX"})
        game = service.unsafe_game(created["session_id"])
        evaluator = MastermindEvaluator()
        self.assertTrue(-0.85 <= evaluator(game) <= 0.85)
        game.winner = "mastermind"
        self.assertEqual(evaluator(game), 1.0)
        game.winner = "protagonists"
        self.assertEqual(evaluator(game), -1.0)

    def test_only_mastermind_or_admin_can_obtain_full_search_clone(self):
        service = GameService()
        created = service.create_game({"module": "BTX"})
        session = created["session_id"]
        clone = service.mastermind_search_clone(
            session, token=created["credentials"]["seats"]["m"])
        self.assertIsNot(clone, service.unsafe_game(session))
        clone.state.characters["student"].intrigue += 1
        self.assertEqual(service.unsafe_game(session).state.characters["student"].intrigue, 0)
        with self.assertRaises(ServiceError) as caught:
            service.mastermind_search_clone(
                session, token=created["credentials"]["seats"]["a"])
        self.assertEqual(caught.exception.code, "FORBIDDEN")


class FullInformationMctsTests(unittest.TestCase):
    @staticmethod
    def immediate_win_game():
        game = Game(example_scenario("FS"))
        game.state.loop = game.scenario["loops"]
        game.state.phase = "day_end"
        game._timing_window = None
        game.state.characters["worker"].intrigue = 4
        return game

    def test_search_is_reproducible_legal_and_does_not_mutate_root(self):
        game = Game(example_scenario("BTX"))
        before = game.state_key("m")
        budget = SearchBudget(node_limit=18, rollout_depth=7, seed=42)
        first = FullInformationMctsMastermindAgent(budget)
        second = FullInformationMctsMastermindAgent(budget)

        chosen_a = first.search(game)
        chosen_b = second.search(game)

        self.assertEqual(chosen_a.command, chosen_b.command)
        self.assertIn(chosen_a, game.action_offers("m"))
        self.assertEqual(game.state_key("m"), before)
        self.assertEqual(first.last_trace.nodes, budget.node_limit)
        self.assertEqual(
            [(item.action_id, item.visits, item.mean_value)
             for item in first.last_trace.root_actions],
            [(item.action_id, item.visits, item.mean_value)
             for item in second.last_trace.root_actions])

    def test_search_selects_an_immediate_mastermind_win(self):
        game = self.immediate_win_game()
        agent = FullInformationMctsMastermindAgent(
            SearchBudget(node_limit=12, rollout_depth=5, seed=3))
        chosen = agent.search(game)
        successor = game.transition(chosen).game
        self.assertEqual(chosen.command, {"actor": "m", "action": "choose", "index": 1})
        self.assertEqual(successor.winner, "mastermind")
        self.assertEqual(agent.last_trace.stop_reason, "node_limit")
        self.assertTrue(all(-1 <= item.mean_value <= 1
                            for item in agent.last_trace.root_actions))

    def test_wall_clock_limit_is_a_secondary_safety_stop(self):
        agent = FullInformationMctsMastermindAgent(SearchBudget(
            node_limit=10000, rollout_depth=4, time_limit_ms=1, seed=1))
        agent.search(Game(example_scenario("BTX")))
        self.assertEqual(agent.last_trace.stop_reason, "time_limit")
        self.assertLess(agent.last_trace.nodes, 10000)

    def test_fully_expanded_finite_tree_stops_before_node_budget(self):
        game = self.immediate_win_game()
        game._pending = op("choice", options=[
            option("立即结束", [op("heroes_die")])])
        game._return_phase = "day_end"
        game._decision_actor = "m"
        game._decision_public_phase = "day_end"
        game.state.phase = "decision"
        agent = FullInformationMctsMastermindAgent(
            SearchBudget(node_limit=100, rollout_depth=3, seed=9))
        agent.search(game)
        self.assertEqual(agent.last_trace.stop_reason, "tree_exhausted")
        self.assertEqual(agent.last_trace.nodes, 2)

    def test_every_ruleset_can_supply_mcts_root_actions(self):
        for module in ("FS", "BTX", "MZ", "MC", "HSA", "WM", "AHR", "LL"):
            with self.subTest(module=module):
                game = Game(example_scenario(module))
                agent = FullInformationMctsMastermindAgent(
                    SearchBudget(node_limit=2, rollout_depth=1, seed=5))
                chosen = agent.search(game)
                self.assertIn(chosen, game.action_offers("m"))


if __name__ == "__main__":
    unittest.main()
