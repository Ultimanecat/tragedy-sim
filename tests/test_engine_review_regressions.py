"""Regressions for the engine review findings (docs/review-engine.md)."""

import unittest

from tragedy_sim import Game
from tragedy_sim.engine import Placement
from tragedy_sim.scenario_library import ScenarioLibrary


class IllusionEchoTests(unittest.TestCase):
    @staticmethod
    def mz_game():
        return Game(ScenarioLibrary().get(
            "official-mz-06-singer-of-the-heretic-idol"))

    def test_single_forbid_card_is_not_doubled_by_board_echo(self):
        game = self.mz_game()
        game.state.pending = [Placement("m", "i1", "illusion"),
                              Placement("a", "fi", "school")]
        # One physical forbid card; the illusion echo repeats it on a board.
        game._board_echo_placements = [(
            1, Placement("a", "fi", "school"))]
        self.assertEqual(game._intrigue_forbid_count(), 1)

    def test_two_distinct_forbid_cards_still_cancel(self):
        game = self.mz_game()
        game.state.pending = [Placement("m", "i1", "illusion"),
                              Placement("a", "fi", "school"),
                              Placement("b", "fi", "city")]
        self.assertEqual(game._intrigue_forbid_count(), 2)

    def test_ignored_placement_is_not_counted(self):
        game = self.mz_game()
        game.state.pending = [Placement("a", "fi", "school"),
                              Placement("b", "fi", "city")]
        game._ignored_placement_indexes.add(1)
        self.assertEqual(game._intrigue_forbid_count(), 1)


class ScenarioInitialLocationTests(unittest.TestCase):
    def test_henchman_scenario_initial_location_reaches_public_view(self):
        game = Game(ScenarioLibrary().get(
            "official-mz-06-singer-of-the-heretic-idol"))
        view = game.protagonist_team_view()
        expected = game.scenario["character_options"]["henchman"][
            "initial_location"]
        self.assertEqual(view["characters"]["henchman"]["initial_location"],
                         expected)
        self.assertEqual(view["characters"]["henchman"]["location"], expected)
        self.assertEqual(game._loop_initial_locations["henchman"], expected)

    def test_servant_scenario_initial_location_reaches_map(self):
        library = ScenarioLibrary()
        candidates = [item["id"] for item in library.list()
                      if item["source"] == "library"]
        checked = 0
        for scenario_id in candidates:
            scenario = library.get(scenario_id)
            options = scenario.get("character_options", {})
            servant = options.get("servant", {}).get("initial_location")
            if not servant or "servant" not in scenario["cast"]:
                continue
            game = Game(scenario)
            self.assertEqual(
                game.protagonist_team_view()["characters"]["servant"][
                    "initial_location"], servant, scenario_id)
            checked += 1
        if not checked:
            self.skipTest("no library scenario overrides the servant board")


if __name__ == "__main__":
    unittest.main()
