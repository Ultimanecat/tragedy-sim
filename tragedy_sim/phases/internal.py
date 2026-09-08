"""Explicit user decisions nested inside a public rules timing."""

from __future__ import annotations

from typing import Any

from ..model import PhaseId
from .base import ChoicePhaseResolver, PhaseResolver


class DecisionResolver(ChoicePhaseResolver):
    phase = PhaseId.DECISION
    may_finish = False

    def controller(self, game) -> str | None:
        return game._decision_actor


class GameOverResolver(PhaseResolver):
    phase = PhaseId.GAME_OVER

    def legal_actions(self, game, actor: str) -> list[dict[str, Any]]:
        return []

    def execute(self, game, actor: str, action: str,
                arguments: dict[str, Any]) -> None:
        raise AssertionError("结束后的对局不能执行行动")
