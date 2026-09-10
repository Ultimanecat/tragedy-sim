from ..model import PhaseId
from .base import ChoicePhaseResolver


class MastermindAbilityResolver(ChoicePhaseResolver):
    phase = PhaseId.MASTER_ABILITIES

    def advance(self, game) -> None:
        game._close_timing_window()
        game.state.phase = "goodwill"
        game._event("phase_changed", "进入友好能力阶段，由当日领队选择；友好值不消耗。")
