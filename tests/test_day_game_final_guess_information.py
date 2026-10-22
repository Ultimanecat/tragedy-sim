"""T1 final-guess information feature tests."""

import unittest

from tragedy_sim import Game
from tragedy_sim.day_game.final_guess_information import estimate_final_guess_information
from tragedy_sim.scenario_library import ScenarioLibrary


class FinalGuessInformationTests(unittest.TestCase):
    def test_btx_public_evidence_produces_a_bounded_estimate(self):
        game = Game(ScenarioLibrary().get("official-btx-01-machina-solar-cogwheel"))
        info = estimate_final_guess_information(game, node_limit=5000)
        self.assertIn(info.status, {"exact", "node_limit", "unsupported"})
        if info.exact:
            self.assertIsNotNone(info.probability)
            self.assertGreaterEqual(info.probability, 0.0)
            self.assertLessEqual(info.probability, 1.0)
            self.assertIsNotNone(info.best_guess)
        else:
            self.assertIsNone(info.probability)

    def test_fs_without_final_guess_is_rejected(self):
        game = Game(ScenarioLibrary().get("official-fs-01-first-script"))
        with self.assertRaises(ValueError):
            estimate_final_guess_information(game)

    def test_invalid_node_limit_is_rejected(self):
        game = Game(ScenarioLibrary().get("official-btx-01-machina-solar-cogwheel"))
        for limit in (0, -1, 1.5):
            with self.assertRaises(ValueError):
                estimate_final_guess_information(game, node_limit=limit)
