"""Explicit composition of effect handlers used by the runtime resolver."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping, TYPE_CHECKING

from .effects import ahr, board, flow, hsa, knowledge, ll, mc, movement, mz, outcomes, wm

if TYPE_CHECKING:
    from .game import Game


EffectHandler = Callable[["Game", Mapping[str, Any]], None]


@dataclass(frozen=True)
class EffectHandlerRegistry:
    """Immutable dispatch table, explicitly supplied to an effect resolver.

    Extending returns a new registry and rejects collisions. This makes ruleset
    composition inspectable and avoids process-wide hooks or import-order effects.
    """

    handlers: Mapping[str, EffectHandler]

    def __init__(self, handlers: Mapping[str, EffectHandler]) -> None:
        if any(not isinstance(kind, str) or not kind for kind in handlers):
            raise ValueError("效果处理器必须使用非空 kind")
        object.__setattr__(self, "handlers", MappingProxyType(dict(handlers)))

    def handles(self, kind: str) -> bool:
        return kind in self.handlers

    def resolve(self, game: "Game", effect: Mapping[str, Any]) -> None:
        try:
            handler = self.handlers[effect["kind"]]
        except KeyError as exc:
            raise KeyError(f"未注册效果处理器：{effect.get('kind')}") from exc
        handler(game, effect)

    def extended(self, handlers: Mapping[str, EffectHandler]) -> "EffectHandlerRegistry":
        collisions = set(self.handlers) & set(handlers)
        if collisions:
            raise ValueError("效果处理器重复注册：" + "、".join(sorted(collisions)))
        return EffectHandlerRegistry({**self.handlers, **handlers})


def _change_counter(game: "Game", effect: Mapping[str, Any]) -> None:
    game._change(effect["target"], effect["counter"], effect["amount"],
                 silent_noop=effect.get("silent_noop", False))


def _kill_character(game: "Game", effect: Mapping[str, Any]) -> None:
    game._kill([effect["target"]])


def _kill_many(game: "Game", effect: Mapping[str, Any]) -> None:
    game._kill(effect["targets"])


CORE_EFFECT_HANDLERS = EffectHandlerRegistry({
    "counter": _change_counter,
    "kill": _kill_character,
    "kill_many": _kill_many,
})

# Explicit compatibility composition. Individual ruleset definitions will select
# their own handler sets when they migrate; no registration happens by callback.
MATCH_EFFECT_HANDLERS = (CORE_EFFECT_HANDLERS
    .extended(board.HANDLERS)
    .extended(movement.HANDLERS)
    .extended(knowledge.HANDLERS)
    .extended(outcomes.HANDLERS)
    .extended(flow.HANDLERS)
    .extended(mz.HANDLERS)
    .extended(mc.HANDLERS)
    .extended(hsa.HANDLERS)
    .extended(wm.HANDLERS)
    .extended(ahr.HANDLERS)
    .extended(ll.HANDLERS))
