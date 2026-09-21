"""The two script-aware baselines have an explicit dark-card boundary."""

import random
import unittest
from copy import deepcopy
from functools import reduce

from tragedy_sim import Game
from tragedy_sim.belief import PublicEvidence
from tragedy_sim.engine import Placement
from tragedy_sim.oracle_protagonist import (
    FullCardOracleProtagonistAgent, HiddenCardOracleProtagonistAgent)
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.search import SearchBudget


def protagonist_position(scenario_id="official-fs-01-first-script"):
    game = Game(ScenarioLibrary().get(scenario_id))
    while game.state.phase != "protagonists":
        game = game.search_transition(game.search_actions(game.controller)[0])
    return game


class OracleProtagonistTests(unittest.TestCase):
    def test_visible_pressure_on_known_killer_enters_defense_candidates(self):
        game = Game(ScenarioLibrary().get("silent-town-fs"))
        game = game.search_transition(game.search_actions("m")[0])
        killer = next(cid for cid, role in game.roles.items() if role == "killer")
        for card, target in (("i1", killer), ("p1a", "doctor"),
                             ("v", "girl")):
            action = next(action for action in game.search_actions("m")
                          if action.get("card") == card and action.get("target") == target)
            game = game.search_transition(action)
        oracle = FullCardOracleProtagonistAgent(SearchBudget(node_limit=24))
        candidates = [oracle._bundle(game, game.protagonist_team_view(), index)
                      for index in range(24)]
        self.assertTrue(any(
            action["card"] == "fi" and action["target"] == killer
            for bundle in candidates for action in bundle))
        self.assertTrue(all(sum(action["card"] == "fi" for action in bundle) <= 1
                            for bundle in candidates))
        self.assertTrue(all(action["card"] == "fi"
                            for bundle in candidates for action in bundle
                            if action["target"] in game.state.locations))

    def test_full_card_oracle_recovers_previously_lost_tutorial_seed(self):
        from benchmarks.ai_self_play import play

        result = play("silent-town-fs", 4, 24, 12, "strategic",
                      "oracle_cards", protagonist_nodes=24)
        self.assertEqual(result.winner, "protagonists")

    def test_day_value_penalizes_isolated_known_key(self):
        game = Game(ScenarioLibrary().get("official-fs-01-first-script"))
        game.state.round = 2
        isolated = deepcopy(game)
        isolated.state.characters["girl"].location = "shrine"
        grouped = deepcopy(game)
        grouped.state.characters["girl"].location = "school"
        oracle = FullCardOracleProtagonistAgent(SearchBudget(node_limit=4))
        alone_score, _ = oracle._day_score(isolated, 1, 1)
        grouped_score, _ = oracle._day_score(grouped, 1, 1)
        self.assertGreater(grouped_score, alone_score)

    def test_both_modes_choose_legal_full_team_plan(self):
        game = protagonist_position()
        offers = [{**item.to_dict(), "type": item.kind.removeprefix("core.")}
                  for item in game.action_offers(game.controller)]
        for agent in (
            FullCardOracleProtagonistAgent(SearchBudget(node_limit=12)),
            HiddenCardOracleProtagonistAgent(
                SearchBudget(node_limit=12), scenario_count=3),
        ):
            with self.subTest(agent=agent.plan_name):
                chosen = agent.choose_game_action(
                    participant="team", game=game, offers=offers)
                self.assertIn(chosen, offers)
                self.assertEqual(len(agent.last_trace.selected_bundle), 3)
                self.assertGreater(agent.last_trace.candidates, 0)
                self.assertEqual(agent.last_trace.to_dict()["strategy"],
                                 agent.plan_name)

    def test_hidden_card_mode_is_invariant_to_actual_pending_faces(self):
        game = protagonist_position()
        other = deepcopy(game)
        original = other.state.pending[0]
        replacement = next(card for card in other.state.hands["m"]
                           if card != original.card)
        other.state.hands["m"].remove(replacement)
        other.state.hands["m"].append(original.card)
        other.state.pending[0] = Placement("m", replacement, original.target)
        self.assertEqual(game.protagonist_team_view(),
                         other.protagonist_team_view())
        offers = [{**item.to_dict(), "type": item.kind.removeprefix("core.")}
                  for item in game.action_offers(game.controller)]
        budget = SearchBudget(node_limit=18, seed=9)
        first = HiddenCardOracleProtagonistAgent(
            budget, scenario_count=4, rng_seed=9)
        second = HiddenCardOracleProtagonistAgent(
            budget, scenario_count=4, rng_seed=9)
        chosen_a = first.choose_game_action(participant="team", game=game,
                                            offers=offers)
        chosen_b = second.choose_game_action(participant="team", game=other,
                                             offers=offers)
        self.assertEqual(chosen_a, chosen_b)
        self.assertEqual(first.last_trace.selected_bundle,
                         second.last_trace.selected_bundle)
        evidence = PublicEvidence.from_view(game.protagonist_team_view())
        worlds_a = first._worlds(game, game.protagonist_team_view(), random.Random(4))
        worlds_b = first._worlds(other, other.protagonist_team_view(), random.Random(4))
        self.assertEqual(evidence.module, "FS")
        self.assertEqual(
            [[item.card for item in world.state.pending] for world in worlds_a],
            [[item.card for item in world.state.pending] for world in worlds_b])

    def test_btx_both_oracles_search_and_hidden_mode_ignores_actual_faces(self):
        game = protagonist_position("official-btx-09-those-with-antibodies")
        other = deepcopy(game)
        original = other.state.pending[0]
        replacement = next(card for card in other.state.hands["m"]
                           if card != original.card)
        other.state.hands["m"].remove(replacement)
        other.state.hands["m"].append(original.card)
        other.state.pending[0] = Placement("m", replacement, original.target)
        self.assertEqual(game.protagonist_team_view(),
                         other.protagonist_team_view())
        offers = [{**item.to_dict(), "type": item.kind.removeprefix("core.")}
                  for item in game.action_offers(game.controller)]
        budget = SearchBudget(node_limit=8, seed=17)
        full = FullCardOracleProtagonistAgent(budget, rng_seed=17)
        hidden_a = HiddenCardOracleProtagonistAgent(
            budget, scenario_count=2, rng_seed=17)
        hidden_b = HiddenCardOracleProtagonistAgent(
            budget, scenario_count=2, rng_seed=17)
        full_choice = full.choose_game_action(
            participant="team", game=game, offers=offers)
        blind_a = hidden_a.choose_game_action(
            participant="team", game=game, offers=offers)
        blind_b = hidden_b.choose_game_action(
            participant="team", game=other, offers=offers)
        self.assertIn(full_choice, offers)
        self.assertIn(blind_a, offers)
        self.assertEqual(blind_a, blind_b)
        self.assertEqual(hidden_a.last_trace.selected_bundle,
                         hidden_b.last_trace.selected_bundle)
        self.assertEqual(len(full.last_trace.selected_bundle), 3)
        self.assertEqual(len(hidden_a.last_trace.selected_bundle), 3)

    def test_btx_oracles_guess_known_script_exactly(self):
        game = Game(ScenarioLibrary().get("official-btx-09-those-with-antibodies"))
        game._start_final_guess()
        offers = [{**item.to_dict(), "type": item.kind.removeprefix("core.")}
                  for item in game.action_offers(game.controller)]
        for agent in (FullCardOracleProtagonistAgent(),
                      HiddenCardOracleProtagonistAgent()):
            with self.subTest(agent=agent.plan_name):
                chosen = agent.choose_game_action(
                    participant="team", game=game, offers=offers)
                self.assertEqual(chosen["arguments"]["guesses"],
                                 game.scenario["cast"])

    def test_btx_time_traveler_candidate_makes_legal_cross_day_progress(self):
        game = protagonist_position("official-btx-09-those-with-antibodies")
        oracle = FullCardOracleProtagonistAgent(SearchBudget(node_limit=8))
        bundle = oracle._bundle(game, game.protagonist_team_view(), 0)
        self.assertEqual((bundle[0]["card"], bundle[0]["target"]),
                         ("g2", "journalist"))
        self.assertEqual(len({item["target"] for item in bundle}), 3)
        world = reduce(lambda state, action: state.search_transition(action),
                       bundle, game)
        self.assertEqual(len(world.state.pending), 6)
        for index in range(12):
            candidate = oracle._bundle(game, game.protagonist_team_view(), index)
            self.assertEqual(len({item["target"] for item in candidate}),
                             len(candidate), candidate)

    def test_hidden_mode_forces_intrigue_faces_on_publicly_targeted_key(self):
        game = Game(ScenarioLibrary().get("official-fs-01-first-script"))
        game = game.search_transition(game.search_actions("m")[0])
        for card, target in (("v", "girl"), ("p1a", "worker"),
                             ("fp", "doctor")):
            command = next(action for action in game.search_actions("m")
                           if action.get("card") == card and action.get("target") == target)
            game = game.search_transition(command)
        oracle = HiddenCardOracleProtagonistAgent(
            SearchBudget(node_limit=12), scenario_count=1)
        worlds = oracle._worlds(game, game.protagonist_team_view(), random.Random(2))
        faces = {item.card for world in worlds for item in world.state.pending
                 if item.actor == "m" and item.target == "girl"}
        self.assertIn("i2", faces)
        self.assertIn("i1", faces)

    def test_known_fs_school_intrigue_can_be_blocked(self):
        game = Game(ScenarioLibrary().get("official-fs-02-prevailing-secrecy"))
        game = game.search_transition(game.search_actions(game.controller)[0])
        for card, target in (("i2", "school"), ("fg", "doctor"),
                             ("fp", "shrine")):
            action = next(item for item in game.search_actions(game.controller)
                          if item.get("card") == card and item.get("target") == target)
            game = game.search_transition(action)
        oracle = FullCardOracleProtagonistAgent(SearchBudget(node_limit=12))
        offers = [{**item.to_dict(), "type": item.kind.removeprefix("core.")}
                  for item in game.action_offers(game.controller)]
        oracle.choose_game_action(participant="team", game=game, offers=offers)
        self.assertIn(("fi", "school"),
                      [(action["card"], action["target"])
                       for action in oracle.last_trace.selected_bundle])
        self.assertIn(("h", "student"),
                      [(action["card"], action["target"])
                       for action in oracle.last_trace.selected_bundle])
        bundle = oracle._bundle(game, game.protagonist_team_view(), 1)
        self.assertEqual((bundle[0]["card"], bundle[0]["target"]),
                         ("fi", "school"))
        self.assertEqual((bundle[1]["card"], bundle[1]["target"]),
                         ("h", "student"))
        world = reduce(lambda state, action: state.search_transition(action),
                       bundle, game)
        self.assertIn(Placement("a", "fi", "school"), world.state.pending)
        self.assertEqual(world._ignored_placement_indexes, set())
        for _ in range(30):
            if world.state.round != 1 or world.winner is not None:
                break
            action = world.search_actions(world.controller)[0]
            world.dispatch(action["actor"], action["action"],
                           **{key: value for key, value in action.items()
                              if key not in {"actor", "action"}})
        self.assertEqual(world.state.locations["school"], 0,
                         [(event["kind"], event.get("message"))
                          for event in world.state.events])


if __name__ == "__main__":
    unittest.main()
