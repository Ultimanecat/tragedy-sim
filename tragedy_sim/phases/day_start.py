from typing import Any

from ..cards import ACTOR_NAMES
from ..model import PhaseId, TimingId
from .base import NextPhaseResolver


class DayStartResolver(NextPhaseResolver):
    phase = PhaseId.DAY_START

    def execute(self, game, actor: str, action: str,
                arguments: dict[str, Any]) -> None:
        state = game.state
        order = game._protagonists_from(state.leader)
        if game.module == "LL" and game._ll_restricted_day == state.round:
            game.configure_actions(mastermind=1, protagonists=order)
            game._event("mastermind_restricted", "秘钥已经公开：今日剧作家只能放置 1 张行动牌。")
        else:
            game.configure_actions(mastermind=3, protagonists=order)
        state.phase = "mastermind"
        game._event("day_started", f"第 {state.round} 天开始，领队为{ACTOR_NAMES[state.leader]}。",
                    timing=TimingId.DAY_START)
