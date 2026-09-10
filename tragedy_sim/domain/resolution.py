"""Deterministic activation windows for mandatory-then-optional timing rules."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, Protocol, Sequence

from .effects import Effect
from .rules import Activation, ActivationMode, RuleContext


class ActivationRule(Protocol):
    """A rule queried at a particular state and timing."""

    def activations(self, context: RuleContext) -> Iterable[Activation]: ...


class WindowStage(StrEnum):
    COLLECTED = "collected"
    RESOLVING_MANDATORY = "resolving_mandatory"
    OPTIONAL = "optional"
    CLOSED = "closed"


@dataclass
class MandatoryWindow:
    """Mandatory activations frozen from one pre-resolution state snapshot."""

    context: RuleContext
    activations: tuple[Activation, ...]
    stage: WindowStage = WindowStage.COLLECTED

    def start(self) -> None:
        if self.stage != WindowStage.COLLECTED:
            raise RuntimeError("强制能力时间窗已经开始结算")
        self.stage = WindowStage.RESOLVING_MANDATORY

    def finish_mandatory(self) -> None:
        if self.stage not in (WindowStage.COLLECTED, WindowStage.RESOLVING_MANDATORY):
            raise RuntimeError("强制能力时间窗不能重复完成")
        self.stage = WindowStage.OPTIONAL

    def close(self) -> None:
        if self.stage != WindowStage.OPTIONAL:
            raise RuntimeError("尚未完成强制能力，不能离开时间点")
        self.stage = WindowStage.CLOSED

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
        # Rules must all observe the same detached pre-resolution snapshot.
        snapshot = RuleContext(deepcopy(context.state), deepcopy(dict(context.script)),
                               context.ruleset_id, context.phase, context.timing,
                               context.components.clone())
        return MandatoryWindow(
            snapshot,
            self._collect(snapshot, tuple(rules), ActivationMode.MANDATORY),
        )

    def optional(self, window: MandatoryWindow, context: RuleContext,
                 rules: Iterable[ActivationRule]) -> tuple[Activation, ...]:
        if window.stage != WindowStage.OPTIONAL:
            raise RuntimeError("必须先结算全部强制能力，才能查询可选能力")
        return self._collect(context, tuple(rules), ActivationMode.OPTIONAL)
