"""Complete phase registry used by the Game facade."""

from __future__ import annotations

from ..model import PhaseId
from .action_cards import ActionCardResolver
from .action_resolution import ActionCounterResolver, RevealResolver
from .base import PhaseResolver
from .day_end import DayEndResolver
from .day_start import DayStartResolver
from .final_guess import FinalGuessResolver
from .incidents import IncidentResolver
from .internal import DecisionResolver, GameOverResolver
from .loop_end import LoopEndResolver
from .mastermind_abilities import MastermindAbilityResolver
from .protagonist_abilities import ProtagonistAbilityResolver, RefusalResolver


class PhaseRegistry:
    def __init__(self, resolvers: tuple[PhaseResolver, ...]) -> None:
        self._resolvers = {resolver.phase: resolver for resolver in resolvers}
        expected = set(PhaseId) - {PhaseId.RESOLVED}
        if set(self._resolvers) != expected or len(self._resolvers) != len(resolvers):
            raise ValueError("阶段解析器注册不完整或重复")

    def resolve(self, phase: str | PhaseId) -> PhaseResolver:
        try:
            return self._resolvers[PhaseId(phase)]
        except (KeyError, ValueError) as exc:
            raise ValueError(f"未知游戏阶段：{phase}") from exc


PHASE_RESOLVERS = PhaseRegistry((
    DayStartResolver(),
    ActionCardResolver(PhaseId.MASTERMIND),
    ActionCardResolver(PhaseId.PROTAGONISTS),
    RevealResolver(),
    ActionCounterResolver(),
    MastermindAbilityResolver(),
    ProtagonistAbilityResolver(),
    RefusalResolver(),
    IncidentResolver(),
    DecisionResolver(),
    DayEndResolver(),
    LoopEndResolver(),
    FinalGuessResolver(),
    GameOverResolver(),
))
