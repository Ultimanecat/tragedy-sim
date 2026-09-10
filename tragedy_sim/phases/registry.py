"""Complete phase registry used by the Game facade."""

from __future__ import annotations

from ..model import PhaseId
from ..domain.keys import PhaseKey
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
    def __init__(self, resolvers: tuple[PhaseResolver, ...], *, require_core=True) -> None:
        self._resolvers = {self._key(resolver.phase): resolver for resolver in resolvers}
        expected = set(PhaseId) - {PhaseId.RESOLVED}
        actual_core = {PhaseId(key) for key in self._resolvers if key in PhaseId._value2member_map_}
        if ((require_core and actual_core != expected) or len(self._resolvers) != len(resolvers)):
            raise ValueError("阶段解析器注册不完整或重复")

    @staticmethod
    def _key(phase: str | PhaseId | PhaseKey) -> str:
        return phase.value if isinstance(phase, (PhaseId, PhaseKey)) else str(phase)

    def resolve(self, phase: str | PhaseId | PhaseKey) -> PhaseResolver:
        try:
            return self._resolvers[self._key(phase)]
        except KeyError as exc:
            raise ValueError(f"未知游戏阶段：{phase}") from exc

    def extended(self, *resolvers: PhaseResolver) -> "PhaseRegistry":
        additions = {self._key(resolver.phase): resolver for resolver in resolvers}
        if len(additions) != len(resolvers) or set(additions) & set(self._resolvers):
            raise ValueError("扩展阶段标识重复")
        return PhaseRegistry(tuple(self._resolvers.values()) + tuple(resolvers))

    def replaced(self, resolver: PhaseResolver) -> "PhaseRegistry":
        key = self._key(resolver.phase)
        if key not in self._resolvers:
            raise KeyError(key)
        return PhaseRegistry(tuple(resolver if self._key(item.phase) == key else item
                                   for item in self._resolvers.values()))


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
