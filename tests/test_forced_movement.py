"""Forced movement (servant follow) regressions from the wiki FAQ.

Wiki: FAQ/キャラクター（https://w.atwiki.jp/rooper/pages/15.html）
- 同一区域的大小姐/大人物以行动卡以外的方式移动时，侍从也同行。
- 立てこもり（barricade）让全体移动时，侍从无视自身的移动限制跟随。
- “从版图移除”不是移动，侍从不跟随。
"""

import unittest
from types import SimpleNamespace

from tragedy_sim.engine import Character
from tragedy_sim.effects.movement import move


class FakeGame:
    """Minimal surface used by ``effects.movement.move``."""

    def __init__(self):
        self.state = SimpleNamespace(
            round=2,
            characters={"servant": Character("servant", "侍从", "city")},
        )
        self._movement_locks = {}
        self.events = []

    def _movement_destination_allowed(self, target, destination):
        return True

    def _event(self, kind, message, **fields):
        self.events.append({"kind": kind, "message": message, **fields})


class ForcedServantMoveTests(unittest.TestCase):
    def setUp(self):
        self.game = FakeGame()
        self.servant = self.game.state.characters["servant"]

    def test_forced_follow_ignores_movement_lock(self):
        self.game._movement_locks["servant"] = self.game.state.round
        move(self.game, {"target": "servant", "location": "school", "forced": True})
        self.assertEqual(self.servant.location, "school")
        self.assertIn("character_moved", [e["kind"] for e in self.game.events])

    def test_forced_follow_ignores_forbidden_board(self):
        self.servant.forbidden = ("school",)
        move(self.game, {"target": "servant", "location": "school", "forced": True})
        self.assertEqual(self.servant.location, "school")

    def test_non_forced_move_still_honours_restrictions(self):
        self.servant.forbidden = ("school",)
        move(self.game, {"target": "servant", "location": "school"})
        self.assertEqual(self.servant.location, "city")
        self.assertIn("movement_blocked", [e["kind"] for e in self.game.events])
        move(self.game, {"target": "servant", "location": "shrine"})
        self.assertEqual(self.servant.location, "shrine")

    def test_forced_move_rejects_unknown_destination(self):
        move(self.game, {"target": "servant", "location": "moon", "forced": True})
        self.assertEqual(self.servant.location, "city")
        self.assertIn("movement_blocked", [e["kind"] for e in self.game.events])


if __name__ == "__main__":
    unittest.main()
