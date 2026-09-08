"""Goodwill ability selection and mastermind refusal."""

from ..model import PhaseId
from .base import ChoicePhaseResolver


class ProtagonistAbilityResolver(ChoicePhaseResolver):
    phase = PhaseId.GOODWILL

    def advance(self, game) -> None:
        game.state.phase = "incident"
        game._event("phase_changed", "友好能力阶段结束，进入事件阶段。")


class RefusalResolver(ChoicePhaseResolver):
    phase = PhaseId.REFUSAL
    may_finish = False
