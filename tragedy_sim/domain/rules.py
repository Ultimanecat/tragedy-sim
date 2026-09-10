"""Composable contracts for rules, state extensions, flow, and endgames."""

from __future__ import annotations

from abc import ABC
from copy import deepcopy
from dataclasses import asdict, dataclass, is_dataclass
from enum import StrEnum
from typing import Any, ClassVar, Mapping, Protocol, TypeVar

from ..model import Observation, TimingId
from .actions import ActionOffer
from .effects import Effect, EffectResult
from .keys import PhaseKey, RuleSource


ComponentT = TypeVar("ComponentT", bound="StateComponent")


class ActivationMode(StrEnum):
    MANDATORY = "mandatory"
    OPTIONAL = "optional"


class StateComponent(ABC):
    """Base class for cloneable ruleset-owned state outside core state."""

    component_key: ClassVar[str]

    def to_dict(self) -> dict[str, Any]:
        if not is_dataclass(self):
            raise TypeError("状态组件必须是 dataclass 或重写 to_dict()")
        return asdict(self)


class ComponentStore:
    """Type-safe registry copied with a simulated game state."""

    def __init__(self, components: tuple[StateComponent, ...] = ()) -> None:
        self._items: dict[type[StateComponent], StateComponent] = {}
        self._keys: set[str] = set()
        for component in components:
            self.register(component)

    def register(self, component: StateComponent) -> None:
        component_type = type(component)
        key = getattr(component, "component_key", "")
        RuleSource(key)
        if component_type in self._items or key in self._keys:
            raise ValueError(f"状态组件重复注册：{key}")
        self._items[component_type] = component
        self._keys.add(key)

    def get(self, component_type: type[ComponentT]) -> ComponentT:
        try:
            return self._items[component_type]
        except KeyError as exc:
            raise KeyError(f"状态组件未注册：{component_type.__name__}") from exc

    def clone(self) -> "ComponentStore":
        return ComponentStore(tuple(deepcopy(component) for component in self._items.values()))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ComponentStore) and self.to_dict() == other.to_dict()

    def to_dict(self) -> dict[str, dict[str, Any]]:
        return {component.component_key: component.to_dict()
                for component in self._items.values()}


@dataclass(frozen=True)
class RuleContext:
    """Explicit inputs supplied when asking a rule for behavior."""

    state: Any
    script: Mapping[str, Any]
    ruleset_id: str
    phase: PhaseKey
    timing: TimingId
    components: ComponentStore


@dataclass(frozen=True)
class Activation:
    source: RuleSource
    timing: TimingId
    mode: ActivationMode
    controller: str | None
    effects: tuple[Effect, ...] = ()
    offers: tuple[ActionOffer, ...] = ()


@dataclass(frozen=True)
class ResolutionTrace:
    """Private causal record. It must never be copied into a player view."""

    source: RuleSource
    timing: TimingId
    effect: Effect
    observations: tuple[Observation, ...] = ()
    details: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.value,
            "timing": self.timing.value,
            "effect": self.effect.to_legacy(),
            "observations": [observation.to_dict() for observation in self.observations],
            "details": deepcopy(dict(self.details or {})),
        }


@dataclass(frozen=True)
class FlowPlan:
    phases: tuple[PhaseKey, ...]

    def __post_init__(self) -> None:
        if not self.phases or len(set(self.phases)) != len(self.phases):
            raise ValueError("流程必须包含互不重复的阶段")

    def replace(self, old: PhaseKey, *replacement: PhaseKey) -> "FlowPlan":
        if old not in self.phases:
            raise KeyError(str(old))
        phases = list(self.phases)
        index = phases.index(old)
        phases[index:index + 1] = replacement
        return FlowPlan(tuple(phases))

    def insert_after(self, existing: PhaseKey, *added: PhaseKey) -> "FlowPlan":
        if existing not in self.phases:
            raise KeyError(str(existing))
        phases = list(self.phases)
        index = phases.index(existing) + 1
        phases[index:index] = added
        return FlowPlan(tuple(phases))

    def insert_before(self, existing: PhaseKey, *added: PhaseKey) -> "FlowPlan":
        if existing not in self.phases:
            raise KeyError(str(existing))
        phases = list(self.phases)
        phases[phases.index(existing):phases.index(existing)] = added
        return FlowPlan(tuple(phases))


@dataclass(frozen=True)
class EndgamePlan:
    entry_phase: PhaseKey
    controller: str | None
    offered_actions: tuple[ActionOffer, ...] = ()


class VictoryPolicy(Protocol):
    def check(self, context: RuleContext) -> EffectResult | None: ...

    def endgame(self, context: RuleContext) -> EndgamePlan: ...
