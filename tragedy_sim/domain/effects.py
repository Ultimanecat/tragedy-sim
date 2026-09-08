"""Typed effects and the compatibility boundary for the legacy resolver."""

from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..model import Observation
from .actions import ActionOffer


class Effect(ABC):
    """A state change understood by an effect resolver."""

    @property
    @abstractmethod
    def kind(self) -> str: ...

    @abstractmethod
    def to_legacy(self) -> dict[str, Any]:
        """Temporary adapter used until the old resolver has been migrated."""


@dataclass(frozen=True)
class LegacyEffect(Effect):
    effect_kind: str
    parameters: Mapping[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return self.effect_kind

    def to_legacy(self) -> dict[str, Any]:
        return {"kind": self.effect_kind, **deepcopy(dict(self.parameters))}


@dataclass(frozen=True)
class CounterChange(Effect):
    target: str
    counter: str
    amount: int
    silent_noop: bool = False

    @property
    def kind(self) -> str:
        return "counter"

    def to_legacy(self) -> dict[str, Any]:
        result = {"kind": self.kind, "target": self.target,
                  "counter": self.counter, "amount": self.amount}
        if self.silent_noop:
            result["silent_noop"] = True
        return result


@dataclass(frozen=True)
class KillCharacter(Effect):
    target: str

    @property
    def kind(self) -> str:
        return "kill"

    def to_legacy(self) -> dict[str, Any]:
        return {"kind": self.kind, "target": self.target}


@dataclass(frozen=True)
class CustomEffect(Effect):
    """Namespaced effect for a ruleset-specific resolver."""

    effect_kind: str
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if "." not in self.effect_kind:
            raise ValueError("自定义效果必须使用规则集命名空间")

    @property
    def kind(self) -> str:
        return self.effect_kind

    def to_legacy(self) -> dict[str, Any]:
        return {"kind": self.effect_kind, **deepcopy(dict(self.parameters))}


def normalize_effect(effect: Effect | Mapping[str, Any]) -> dict[str, Any]:
    """Return an isolated legacy representation, rejecting malformed effects."""

    if isinstance(effect, Effect):
        result = effect.to_legacy()
    elif isinstance(effect, Mapping):
        result = deepcopy(dict(effect))
    else:
        raise TypeError("内部效果必须是 Effect 或映射")
    if not isinstance(result.get("kind"), str) or not result["kind"]:
        raise ValueError("内部效果缺少 kind")
    return result


@dataclass(frozen=True)
class EffectResult:
    """Effects may produce observations, follow-ups, or an explicit interruption."""

    observations: tuple[Observation, ...] = ()
    follow_ups: tuple[Effect, ...] = ()
    offers: tuple[ActionOffer, ...] = ()
    interrupted: bool = False
    reason: str | None = None
