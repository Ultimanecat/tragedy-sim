"""Deterministic activation windows for mandatory-then-optional timing rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol, Sequence

from .effects import Effect
from .rules import Activation, ActivationMode, RuleContext


class ActivationRule(Protocol):
    """A rule queried at a particular state and timing."""

    def activations(self, context: RuleContext) -> Iterable[Activation]: ...


@dataclass(frozen=True)
class MandatoryWindow:
    """Mandatory activations frozen from one pre-resolution state snapshot."""

    context: RuleContext
    activations: tuple[Activation, ...]

    def ordered(self, indexes: Sequence[int] | None = None) -> tuple[Activation, ...]:
        """Choose resolution order without changing which abilities triggered."""

        if indexes is None:
            return self.activations
        indexes = tuple(indexes)
        if sorted(indexes) != list(range(len(self.activations))):
            raise ValueError("强制能力顺序必须且只能包含每个已触发能力一次")
        return tuple(self.activations[index] for index in indexes)

    def effects(self, indexes: Sequence[int] | None = None) -> tuple[Effect, ...]:
        return tuple(effect for activation in self.ordered(indexes)
                     for effect in activation.effects)


class TimingResolver:
    """Collects each activation class at the rules-prescribed moment.

    Mandatory abilities are captured first and remain fixed while their targets
    and order are resolved. Optional abilities are intentionally queried through
    a separate call with the resulting context, never cached from the old state.
    """

    @staticmethod
    def _collect(context: RuleContext, rules: Iterable[ActivationRule],
                 mode: ActivationMode) -> tuple[Activation, ...]:
        result = []
        for rule in rules:
            for activation in rule.activations(context):
                if activation.timing != context.timing:
                    raise ValueError("能力时间点与当前规则上下文不一致")
                if activation.mode == mode:
                    result.append(activation)
        return tuple(result)

    def begin(self, context: RuleContext,
              rules: Iterable[ActivationRule]) -> MandatoryWindow:
        return MandatoryWindow(
            context,
            self._collect(context, tuple(rules), ActivationMode.MANDATORY),
        )

    def optional(self, context: RuleContext,
                 rules: Iterable[ActivationRule]) -> tuple[Activation, ...]:
        return self._collect(context, tuple(rules), ActivationMode.OPTIONAL)
