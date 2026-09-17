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
    def test_agent_reuses_particles_advanced_from_public_observations(self):
        game = Game(example_scenario("BTX"))
        while game.controller == "m":
            command = game.search_actions("m")[0]
            game.dispatch(command["actor"], command["action"],
                          **{key: value for key, value in command.items()
                             if key not in {"actor", "action"}})
        actor = game.controller
        offers = [offer.to_dict() for offer in game.action_offers(actor)]
        agent = IsmctsProtagonistAgent(
            SearchBudget(node_limit=1, rollout_depth=1, seed=23),
            particle_count=4, rng_seed=23)
        records = game.observation_records("team")
        agent.observe(viewer="team", records=records)
        chosen = agent.choose_action(
            participant="team", view=game.protagonist_team_view(), offers=offers)
        self.assertIn(chosen, offers)
        self.assertTrue(agent.controls_protagonist_team)
        self.assertEqual(agent.last_trace.belief_source, "persistent")
        self.assertEqual(agent.last_trace.observation_updates, len(records) - 1)

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
        self.assertEqual(particle._queue, [])
        self.assertIsNone(particle._pending)
        self.assertIsNone(particle._return_phase)

    def test_agent_returns_a_supplied_offer_and_records_information_set_stats(self):
        game = advance_to_protagonists(Game(example_scenario("FS")))
        view = game.view("a")
        offers = [offer.to_dict() for offer in game.action_offers("a")]
        agent = IsmctsProtagonistAgent(
            SearchBudget(node_limit=8, rollout_depth=4, seed=3),
            particle_count=4, rng_seed=7)
        chosen = agent.choose_action(participant="a", view=view, offers=offers)
        self.assertIn(chosen, offers)
        self.assertEqual(agent.last_trace.strategy,
                         "public_fs_btx_team_so_ismcts")
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

    def test_team_search_caches_the_remaining_cards_of_one_joint_node(self):
        game = advance_to_protagonists(Game(example_scenario("BTX")))
        agent = IsmctsProtagonistAgent(
            SearchBudget(node_limit=6, rollout_depth=3, seed=41),
            particle_count=4, rng_seed=41)
        offers = [offer.to_dict() for offer in game.action_offers(game.controller)]
        first = agent.choose_action(
            participant="team", view=game.protagonist_team_view(), offers=offers)
        self.assertEqual(agent.last_trace.iterations, 6)
        self.assertTrue(agent.last_trace.planned_commands)

        game = game.search_transition({
            "actor": first["actor"],
            "action": first["kind"].removeprefix("core."),
            **first["parameters"],
        })
        followup_offers = [offer.to_dict()
                           for offer in game.action_offers(game.controller)]
        second = agent.choose_action(
            participant="team", view=game.protagonist_team_view(),
            offers=followup_offers)
        self.assertIn(second, followup_offers)
        self.assertEqual(agent.last_trace.fallback, "joint_plan_followup")
        self.assertEqual(agent.last_trace.iterations, 0)

    def test_rollout_does_not_evaluate_before_current_day_end(self):
        game = Game(example_scenario("FS"))
        # Isolate the horizon invariant from immediate role-loss conditions.
        game.roles = dict.fromkeys(game.roles, "ordinary")
        game.scenario["cast"] = dict(game.roles)
        game = advance_to_protagonists(game)
        successor = game.search_transition(game.search_actions(game.controller)[0])
        observed = []
        agent = IsmctsProtagonistAgent(
            SearchBudget(node_limit=1, rollout_depth=1, seed=4), particle_count=1)

        def capture(world, evaluator):
            observed.append(world)
            return 0.0

        agent._reward = capture
        agent._rollout(successor, random.Random(5))
        self.assertTrue(observed)
        reached_boundary = any(event.get("kind") == "day_ended"
                               and event.get("loop") == successor.state.loop
                               and event.get("round") == successor.state.round
                               for event in observed[0].state.events)
        self.assertTrue(reached_boundary or observed[0].winner is not None)

    def test_final_guess_returns_one_joint_assignment(self):
        game = Game(example_scenario("BTX"))
        game._start_final_guess()
        offers = [offer.to_dict() for offer in game.action_offers(game.controller)]
        agent = IsmctsProtagonistAgent(
            SearchBudget(node_limit=1, rollout_depth=1, seed=6),
            particle_count=4, rng_seed=6)
        chosen = agent.choose_action(
            participant=game.controller, view=game.view(game.controller), offers=offers)
        self.assertEqual(chosen["kind"], "core.guess_all")
        self.assertEqual(set(chosen["arguments"]["guesses"]), set(game.roles))
        self.assertEqual(agent.last_trace.fallback, "simultaneous_map_guess")

    def test_joint_guess_uses_repeated_public_death_evidence(self):
        game = Game(example_scenario("BTX"))
        game._start_final_guess()
        game.state.events = []
        for loop in range(1, 5):
            game.state.events.extend([
                {"kind": "loop_started", "loop": loop, "round": 1,
                 "timing": "loop_start", "message": ""},
                {"kind": "character_died", "loop": loop, "round": 1,
                 "timing": "day_end", "target": "girl", "message": ""},
                {"kind": "loop_lost", "loop": loop, "round": 1,
                 "timing": "loop_end", "message": ""},
            ])
        offers = [offer.to_dict() for offer in game.action_offers(game.controller)]
        agent = IsmctsProtagonistAgent(
            SearchBudget(node_limit=1, rollout_depth=1, seed=12),
            particle_count=8, rng_seed=12)
        chosen = agent.choose_action(
            participant=game.controller, view=game.view(game.controller), offers=offers)
        self.assertEqual(chosen["arguments"]["guesses"]["student"], "serial")
        self.assertIn(chosen["arguments"]["guesses"]["girl"], {"key", "friend"})
        self.assertTrue(agent.last_trace.belief_roles)

    def test_evidence_filters_worlds_without_consuming_action_budget(self):
        game = advance_to_protagonists(Game(example_scenario("BTX")))
        view = game.view("a")
        for loop in (1, 2):
            view["events"].extend([
                {"kind": "loop_started", "loop": loop, "round": 1,
                 "timing": "loop_start", "message": ""},
                {"kind": "character_died", "loop": loop, "round": 1,
                 "timing": "day_end", "target": "girl", "message": ""},
                {"kind": "loop_lost", "loop": loop, "round": 1,
                 "timing": "loop_end", "message": ""},
            ])
        offers = [offer.to_dict() for offer in game.action_offers("a")]
        agent = IsmctsProtagonistAgent(
            SearchBudget(node_limit=1, rollout_depth=1, seed=15),
            particle_count=2, rng_seed=15)
        chosen = agent.choose_action(participant="a", view=view, offers=offers)
        self.assertIn(chosen, offers)
        self.assertIsNone(agent.last_trace.fallback)
        self.assertGreater(agent.last_trace.evidence_soft, 0)
        # Evidence count does not change the configured joint-node budget.
        self.assertEqual(agent.last_trace.iterations, 1)


if __name__ == "__main__":
    unittest.main()
