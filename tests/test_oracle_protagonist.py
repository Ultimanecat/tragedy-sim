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


def protagonist_position():
    game = Game(ScenarioLibrary().get("official-fs-01-first-script"))
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

    def test_full_card_oracle_recovers_previously_lost_tutorial_seed(self):
        from benchmarks.ai_self_play import play

        result = play("silent-town-fs", 4, 24, 12, "strategic",
                      "oracle_cards", protagonist_nodes=24)
        self.assertEqual(result.winner, "protagonists")

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
