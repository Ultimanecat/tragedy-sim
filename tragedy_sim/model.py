"""Stable state-transition vocabulary shared by rules, frontends and AI.

The current engine still stores historical string phase ids for save compatibility.
This module gives those ids a typed boundary without forcing every ruleset to be
migrated at once.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Hashable, Protocol


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


class Visibility(StrEnum):
    PUBLIC = "public"
    MASTERMIND = "mastermind"
    PROTAGONISTS = "protagonists"
    ACTOR = "actor"


@dataclass(frozen=True)
class PhaseCursor:
    """Serializable position in the explicit match state machine."""

    phase: PhaseId
    loop: int
    day: int
    step: int = 0

    @classmethod
    def from_state(cls, state: Any) -> "PhaseCursor":
        try:
            phase = PhaseId(state.phase)
        except (AttributeError, ValueError) as exc:
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

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["visibility"] = self.visibility.value
        return data


@dataclass(frozen=True)
class ResolutionStep:
    """One inspectable consequence produced while resolving a decision."""

    cursor: PhaseCursor
    kind: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    visibility: Visibility = Visibility.PUBLIC

    @classmethod
    def from_event(cls, event: dict[str, Any]) -> "ResolutionStep":
        known = {"loop", "round", "phase", "kind", "message"}
        return cls(
            cursor=PhaseCursor(
                phase=PhaseId(event["phase"]),
                loop=event["loop"],
                day=event["round"],
            ),
            kind=event["kind"],
            message=event["message"],
            data={key: value for key, value in event.items() if key not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cursor": self.cursor.to_dict(),
            "kind": self.kind,
            "message": self.message,
            "data": self.data,
            "visibility": self.visibility.value,
        }


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

    def dispatch(self, actor: str, action: str, **args: Any) -> None: ...

    def view(self, viewer: str = "spectator") -> dict[str, Any]: ...

    def state_key(self, viewer: str = "spectator") -> Hashable: ...

    def simulate(self, actor: str, action: str, **args: Any) -> SimulationResult: ...
