"""Standard role-guessing endgame."""

from __future__ import annotations

from typing import Any

from ..model import PhaseId
from .base import PhaseResolver


class FinalGuessResolver(PhaseResolver):
    phase = PhaseId.FINAL_GUESS

    def legal_actions(self, game, actor: str) -> list[dict[str, Any]]:
        if actor != self.controller(game):
            return []
        # Keep engine-level search actions executable without asking a UI for
        # parameters.  The service replaces this public-information baseline
        # with the complete assignment submitted by the player.
        guesses = {
            character: game.known_roles.get(character, {}).get("role", "ordinary")
            for character in game._guess_remaining
        }
        return [{"actor": actor, "action": "guess_all", "guesses": guesses}]

    def execute(self, game, actor: str, action: str,
                arguments: dict[str, Any]) -> None:
        game._guess_all(arguments["guesses"])
