"""Private single-transition executor, with explicit OO card-math overrides.

The executor owns no new game fields and never escapes. It operates on an
already detached Game's attribute dictionary; the caller receives that plain
Game. No global ruleset registration, method patching or callback hooks.
"""

from dataclasses import dataclass

from ..game import Game
from .local_cards import resolve_counters, resolve_movements, target_programs


@dataclass
class ProgramStats:
    movements: int = 0
    counters: int = 0
    fallbacks: int = 0


class _CompiledFsExecutor(Game):
    __slots__ = ("_program_stats",)

    def _resolve_movements(self):
        programs = target_programs(self)
        if programs is None:
            self._program_stats.fallbacks += 1
            return super()._resolve_movements()
        self._program_stats.movements += 1
        resolve_movements(self, programs)

    def _resolve_counters(self):
        programs = target_programs(self)
        if programs is None:
            self._program_stats.fallbacks += 1
            return super()._resolve_counters()
        self._program_stats.counters += 1
        resolve_counters(self, programs)


def dispatch_compiled(detached_game, actor, action, arguments, stats):
    executor = object.__new__(_CompiledFsExecutor)
    executor.__dict__ = detached_game.__dict__
    executor._program_stats = stats
    executor._dispatch(actor, action, arguments, atomic=False, record_observation=False)
