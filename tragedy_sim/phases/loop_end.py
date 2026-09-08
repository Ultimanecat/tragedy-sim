"""Loop boundary, including rulesets which permit an early final guess."""

from __future__ import annotations

from typing import Any

from ..catalog import MODULES
from ..engine import RuleError
from ..model import PhaseId
from .base import NextPhaseResolver


class LoopEndResolver(NextPhaseResolver):
    phase = PhaseId.LOOP_END

    def legal_actions(self, game, actor: str) -> list[dict[str, Any]]:
        if actor == game.state.leader and MODULES[game.module].early_final_guess:
            return [{"actor": actor, "action": "final"}]
        return super().legal_actions(game, actor)

    def authorize(self, game, actor: str, action: str) -> None:
        if action == "final":
            if actor != game.state.leader or not MODULES[game.module].early_final_guess:
                raise RuleError("当前规则集或阶段不允许领队提前进入最终猜测")
            return
        super().authorize(game, actor, action)

    def execute(self, game, actor: str, action: str,
                arguments: dict[str, Any]) -> None:
        if action == "final":
            game._start_final_guess()
        else:
            game._new_loop()
