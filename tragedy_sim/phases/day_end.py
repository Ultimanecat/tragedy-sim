from ..model import PhaseId
from .base import ChoicePhaseResolver


class DayEndResolver(ChoicePhaseResolver):
    phase = PhaseId.DAY_END

    def advance(self, game) -> None:
        if not game._night_forced_done:
            game._start_day_end_forced()
            if game.state.phase != "day_end" or game._pending:
                return
        state = game.state
        game._close_timing_window()
        game._event("day_ended", f"第 {state.round} 天结束。")
        if state.round >= game._current_loop_days():
            game._finish_loop()
            return
        state.round += 1
        game.day_used.clear()
        game.public_day_used.clear()
        game._prevented_incident_culprits.clear()
        game._ignore_intrigue.clear()
        game._night_forced_done = False
        state.phase = "day_start"
