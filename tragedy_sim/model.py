"""Stable state-transition vocabulary shared by rules, frontends and AI.

The current engine still stores historical string phase ids for save compatibility.
This module gives those ids a typed boundary without forcing every ruleset to be
migrated at once.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Hashable, Protocol

from .i18n import format_timepoint


class PhaseId(StrEnum):
    DAY_START = "day_start"
    MASTERMIND = "mastermind"
    PROTAGONISTS = "protagonists"
    REVEAL = "reveal"
    ACTION_COUNTERS = "action_counters"
    RESOLVED = "resolved"
    MASTER_ABILITIES = "master_abilities"
    GOODWILL = "goodwill"
    REFUSAL = "refusal"
    INCIDENT = "incident"
    DECISION = "decision"
    DAY_END = "day_end"
    LOOP_END = "loop_end"
    FINAL_GUESS = "final_guess"
    GAME_OVER = "game_over"


class TimingId(StrEnum):
    """Rules timing, intentionally independent from the UI's current phase."""

    LOOP_START = "loop_start"
    DAY_START = "day_start"
    MASTERMIND_ACTION = "mastermind_action"
    PROTAGONIST_ACTION = "protagonist_action"
    ACTION_RESOLUTION = "action_resolution"
    MASTERMIND_ABILITY = "mastermind_ability"
    PROTAGONIST_ABILITY = "protagonist_ability"
    INCIDENT = "incident"
    LEADER_CHANGE = "leader_change"
    DAY_END = "day_end"
    LOOP_END = "loop_end"
    FINAL_GUESS = "final_guess"
    GAME_END = "game_end"


PHASE_TIMINGS = {
    PhaseId.DAY_START: TimingId.DAY_START,
    PhaseId.MASTERMIND: TimingId.MASTERMIND_ACTION,
    PhaseId.PROTAGONISTS: TimingId.PROTAGONIST_ACTION,
    PhaseId.REVEAL: TimingId.ACTION_RESOLUTION,
    PhaseId.ACTION_COUNTERS: TimingId.ACTION_RESOLUTION,
    PhaseId.RESOLVED: TimingId.ACTION_RESOLUTION,
    PhaseId.MASTER_ABILITIES: TimingId.MASTERMIND_ABILITY,
    PhaseId.GOODWILL: TimingId.PROTAGONIST_ABILITY,
    PhaseId.REFUSAL: TimingId.PROTAGONIST_ABILITY,
    PhaseId.INCIDENT: TimingId.INCIDENT,
    PhaseId.DAY_END: TimingId.DAY_END,
    PhaseId.LOOP_END: TimingId.LOOP_END,
    PhaseId.FINAL_GUESS: TimingId.FINAL_GUESS,
    PhaseId.GAME_OVER: TimingId.GAME_END,
}


def timing_for_phase(phase: str | PhaseId) -> TimingId:
    phase = PhaseId(phase)
    if phase == PhaseId.DECISION:
        raise ValueError("内部选择阶段必须提供其所属的公开规则阶段")
    return PHASE_TIMINGS[phase]


class Visibility(StrEnum):
    PUBLIC = "public"
    MASTERMIND = "mastermind"
    PROTAGONISTS = "protagonists"
    ACTOR = "actor"


@dataclass(frozen=True)
class PhaseCursor:
    """Serializable position in the explicit match state machine."""

    phase: Any
    loop: int
    day: int
    step: int = 0

    @classmethod
    def from_state(cls, state: Any) -> "PhaseCursor":
        try:
            if state.phase in PhaseId._value2member_map_:
                phase = PhaseId(state.phase)
            else:
                from .domain.keys import PhaseKey
                phase = PhaseKey(state.phase)
        except (AttributeError, ValueError, TypeError) as exc:
            raise ValueError(f"未知游戏阶段：{getattr(state, 'phase', None)}") from exc
        return cls(phase=phase, loop=state.loop, day=state.round)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["phase"] = self.phase.value
        return data


@dataclass(frozen=True)
class Observation:
    """A fact emitted by a transition, with an explicit information boundary."""

    kind: str
    message: str
    visibility: Visibility = Visibility.PUBLIC
    data: dict[str, Any] = field(default_factory=dict)
    timing: TimingId | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timing"] = self.timing.value if self.timing else None
        data["visibility"] = self.visibility.value
        return data


@dataclass(frozen=True)
class ResolutionStep:
    """One inspectable consequence produced while resolving a decision."""

    cursor: PhaseCursor
    kind: str
    message: str
    timing: TimingId
    data: dict[str, Any] = field(default_factory=dict)
    visibility: Visibility = Visibility.PUBLIC

    @classmethod
    def from_event(cls, event: dict[str, Any]) -> "ResolutionStep":
        known = {"loop", "round", "phase", "timing", "kind", "message"}
        return cls(
            cursor=PhaseCursor(
                phase=PhaseId(event["phase"]),
                loop=event["loop"],
                day=event["round"],
            ),
            kind=event["kind"],
            message=event["message"],
            timing=TimingId(event["timing"]),
            data={key: value for key, value in event.items() if key not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cursor": self.cursor.to_dict(),
            "kind": self.kind,
            "message": self.message,
            "timing": self.timing.value,
            "timepoint": self.timepoint,
            "data": self.data,
            "visibility": self.visibility.value,
        }

    @property
    def timepoint(self) -> str:
        return format_timepoint(self.timing.value, self.cursor.loop, self.cursor.day)


@dataclass(frozen=True)
class DecisionRecord:
    """A successful human decision and every public consequence it caused."""

    number: int
    actor: str
    action: str
    arguments: dict[str, Any]
    description: str
    before: PhaseCursor
    after: PhaseCursor
    timing: TimingId
    steps: tuple[ResolutionStep, ...] = ()

    @property
    def command(self) -> dict[str, Any]:
        return {"actor": self.actor, "action": self.action, **self.arguments}

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "command": self.command,
            "description": self.description,
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "timing": self.timing.value,
            "timepoint": format_timepoint(self.timing.value, self.before.loop, self.before.day),
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass(frozen=True)
class SimulationResult:
    """The detached successor produced by one candidate action."""

    game: "GameModel"
    decision: DecisionRecord


class GameModel(Protocol):
    """Small simulation surface intended for frontends and search algorithms."""

    @property
    def phase_cursor(self) -> PhaseCursor: ...

    def options(self, actor: str) -> list[dict[str, Any]]: ...

    def legal_actions(self, actor: str) -> list[dict[str, Any]]: ...

    def action_offers(self, actor: str) -> list[Any]: ...

    def dispatch(self, actor: str, action: str, **args: Any) -> None: ...

    def view(self, viewer: str = "spectator", language: str = "zh") -> dict[str, Any]: ...

    def state_key(self, viewer: str = "spectator") -> Hashable: ...

    def simulate(self, actor: str, action: str, **args: Any) -> SimulationResult: ...
