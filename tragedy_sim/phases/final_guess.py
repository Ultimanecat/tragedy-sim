"""Standard role-guessing endgame."""

from __future__ import annotations

from typing import Any

from ..catalog import ROLE_NAMES
from ..model import PhaseId
from .base import PhaseResolver


class FinalGuessResolver(PhaseResolver):
    phase = PhaseId.FINAL_GUESS

    def legal_actions(self, game, actor: str) -> list[dict[str, Any]]:
        if actor != self.controller(game):
            return []
        roles = game._script_roles() | {"ordinary"}
        if "hideous" in game.scenario["subplots"]:
            roles.add("curmudgeon")
        return [
            {"actor": actor, "action": "guess", "character": character, "role": role}
            for character in game._guess_remaining for role in ROLE_NAMES if role in roles
        ]

    def execute(self, game, actor: str, action: str,
                arguments: dict[str, Any]) -> None:
        game._guess(arguments["character"], arguments["role"])
