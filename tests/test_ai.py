"""Baseline and fixed-playbook AI policy tests."""

import random
import unittest

from tragedy_sim.ai import FixedStrategyMastermindAgent, RandomAgent
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


if __name__ == "__main__":
    unittest.main()
