"""Mastermind and protagonist card-placement phases."""

from __future__ import annotations

from typing import Any

from ..cards import LOCATIONS
from ..model import PhaseId
from .base import PhaseResolver


class ActionCardResolver(PhaseResolver):
    def __init__(self, phase: PhaseId) -> None:
        if phase not in (PhaseId.MASTERMIND, PhaseId.PROTAGONISTS):
            raise ValueError("行动牌解析器只能注册行动牌阶段")
        self.phase = phase

    def legal_actions(self, game, actor: str) -> list[dict[str, Any]]:
        if actor != self.controller(game):
            return []
        view = game.view(actor)
        occupied = {
            placement["target"] for placement in view["pending"]
            if (placement["actor"] == "m") == (actor == "m")
        }
        targets = [
            target for target in (*view["characters"], *LOCATIONS)
            if target not in occupied
            and (target in LOCATIONS or view["characters"][target]["alive"])
            and game._can_target_action(actor, target)
        ]
        return [
            {"actor": actor, "action": "play", "card": card, "target": target}
            for card in view["hand"] for target in targets
        ]

    def execute(self, game, actor: str, action: str,
                arguments: dict[str, Any]) -> None:
        game.play(actor, arguments["card"], arguments["target"])
