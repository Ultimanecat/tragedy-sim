import unittest

from tragedy_sim.ai import RandomAgent
from tragedy_sim.ai_registry import ROOM_AI, RETIRED_ROOM_AI, build_room_ai


class RoomAiRegistryTests(unittest.TestCase):
    def test_retired_ids_have_no_room_factory(self):
        self.assertEqual(len(ROOM_AI), 12)
        self.assertFalse(RETIRED_ROOM_AI.intersection(ROOM_AI))
        for strategy in RETIRED_ROOM_AI:
            with self.subTest(strategy=strategy), self.assertRaises(KeyError):
                build_room_ai(strategy)

    def test_factories_are_independent_and_preserve_information_modes(self):
        for strategy, spec in ROOM_AI.items():
            with self.subTest(strategy=strategy):
                first, second = build_room_ai(strategy), build_room_ai(strategy)
                self.assertIsNot(first, second)
                self.assertTrue(callable(getattr(first, "choose_action", None))
                                or callable(getattr(first, "choose_game_action", None)))
                self.assertIn(spec.role, {"both", "mastermind", "protagonist"})
        self.assertEqual(build_room_ai("belief_joint_mastermind").reply_model, "belief")
        self.assertEqual(build_room_ai("joint_mastermind").reply_model, "public")
        self.assertTrue(build_room_ai("oracle_cards_protagonist").reveal_cards)
        self.assertFalse(build_room_ai("oracle_script_protagonist").reveal_cards)

    def test_random_injection_and_budgets_are_unchanged(self):
        random = RandomAgent()
        self.assertIs(build_room_ai("random", random_agent=random), random)
        self.assertEqual(build_room_ai("particle_ensemble_protagonist").budget.time_limit_ms, 3000)
        self.assertEqual(build_room_ai("belief_joint_mastermind").budget.time_limit_ms, 10000)


if __name__ == "__main__":
    unittest.main()
