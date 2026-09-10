from typing import Any

from ..cards import ACTOR_NAMES
from ..model import PhaseId, TimingId
from .base import NextPhaseResolver


class DayStartResolver(NextPhaseResolver):
    phase = PhaseId.DAY_START

    def execute(self, game, actor: str, action: str,
                arguments: dict[str, Any]) -> None:
        state = game.state
        game._configure_day_actions()
        state.phase = "mastermind"
        game._event("day_started", f"第 {state.round} 天开始，领队为{ACTOR_NAMES[state.leader]}。",
                    timing=TimingId.DAY_START)
