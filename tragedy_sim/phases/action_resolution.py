"""Card reveal and counter-choice phases."""

from __future__ import annotations

from typing import Any

from ..model import PhaseId
from .base import ChoicePhaseResolver, PhaseResolver


class RevealResolver(PhaseResolver):
    phase = PhaseId.REVEAL

    def legal_actions(self, game, actor: str) -> list[dict[str, Any]]:
        if actor != self.controller(game):
            return []
        return [{"actor": actor, "action": "resolve"}]

    def execute(self, game, actor: str, action: str,
                arguments: dict[str, Any]) -> None:
        game.resolve()


class ActionCounterResolver(ChoicePhaseResolver):
    phase = PhaseId.ACTION_COUNTERS

    def advance(self, game) -> None:
        game._resolve_counters()
        game.state.phase = "master_abilities"
        game.state.events[-1]["message"] = (
            "行动牌结算完毕，普通牌回手，限次牌公开留置。进入剧作家能力阶段。"
        )
        game._start_master_abilities_forced()
