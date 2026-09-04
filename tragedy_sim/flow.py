"""Explicit, inspectable phase machine for a complete match."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .model import PhaseId


PHASE_LABELS = {
    PhaseId.DAY_START.value: "日初",
    PhaseId.MASTERMIND.value: "剧作家出牌",
    PhaseId.PROTAGONISTS.value: "主人公出牌",
    PhaseId.REVEAL.value: "统一揭示",
    PhaseId.ACTION_COUNTERS.value: "行动结算",
    PhaseId.RESOLVED.value: "行动结算完成",
    PhaseId.MASTER_ABILITIES.value: "剧作家能力",
    PhaseId.GOODWILL.value: "友好能力",
    PhaseId.REFUSAL.value: "确认友好能力",
    PhaseId.INCIDENT.value: "事件结算",
    PhaseId.DECISION.value: "必要结算选择",
    PhaseId.DAY_END.value: "日末结算",
    PhaseId.LOOP_END.value: "轮回之间",
    PhaseId.FINAL_GUESS.value: "最终猜测",
    PhaseId.GAME_OVER.value: "对局结束",
}


class ControllerPolicy(StrEnum):
    MASTERMIND = "mastermind"
    LEADER = "leader"
    NEXT_ACTOR = "next_actor"
    NONE = "none"


@dataclass(frozen=True)
class PhaseDefinition:
    id: PhaseId
    controller: ControllerPolicy
    actions: frozenset[str]


class MatchFlow:
    """Closed set of public phases and commands; rules resolve within a phase."""

    command_shapes = {
        "play": frozenset(("card", "target")),
        "resolve": frozenset(),
        "next": frozenset(),
        "choose": frozenset(("index",)),
        "guess": frozenset(("character", "role")),
        "final": frozenset(),
    }

    def __init__(self, definitions: tuple[PhaseDefinition, ...]):
        self.definitions = {definition.id: definition for definition in definitions}
        if set(self.definitions) != set(PhaseId) - {PhaseId.RESOLVED}:
            raise ValueError("完整对局阶段定义不完整")

    def definition(self, phase: str | PhaseId) -> PhaseDefinition:
        return self.definitions[PhaseId(phase)]

    def controller(self, phase: str | PhaseId, *, leader: str, next_actor: str | None) -> str | None:
        policy = self.definition(phase).controller
        if policy == ControllerPolicy.NEXT_ACTOR:
            return next_actor
        if policy == ControllerPolicy.LEADER:
            return leader
        if policy == ControllerPolicy.MASTERMIND:
            return "m"
        return None

    def validate_command(self, phase: str | PhaseId, action: str, arguments: dict[str, Any]) -> None:
        if action not in self.command_shapes or set(arguments) != self.command_shapes[action]:
            raise ValueError("未知命令或参数")
        if action not in self.definition(phase).actions:
            raise ValueError("当前阶段不能执行这项操作")


MATCH_FLOW = MatchFlow((
    PhaseDefinition(PhaseId.DAY_START, ControllerPolicy.MASTERMIND, frozenset(("next",))),
    PhaseDefinition(PhaseId.MASTERMIND, ControllerPolicy.NEXT_ACTOR, frozenset(("play",))),
    PhaseDefinition(PhaseId.PROTAGONISTS, ControllerPolicy.NEXT_ACTOR, frozenset(("play",))),
    PhaseDefinition(PhaseId.REVEAL, ControllerPolicy.MASTERMIND, frozenset(("resolve",))),
    PhaseDefinition(PhaseId.ACTION_COUNTERS, ControllerPolicy.MASTERMIND, frozenset(("choose", "next"))),
    PhaseDefinition(PhaseId.MASTER_ABILITIES, ControllerPolicy.MASTERMIND, frozenset(("choose", "next"))),
    PhaseDefinition(PhaseId.GOODWILL, ControllerPolicy.LEADER, frozenset(("choose", "next"))),
    PhaseDefinition(PhaseId.REFUSAL, ControllerPolicy.MASTERMIND, frozenset(("choose",))),
    PhaseDefinition(PhaseId.INCIDENT, ControllerPolicy.MASTERMIND, frozenset(("next",))),
    PhaseDefinition(PhaseId.DECISION, ControllerPolicy.MASTERMIND, frozenset(("choose",))),
    PhaseDefinition(PhaseId.DAY_END, ControllerPolicy.MASTERMIND, frozenset(("choose", "next"))),
    PhaseDefinition(PhaseId.LOOP_END, ControllerPolicy.MASTERMIND, frozenset(("next", "final"))),
    PhaseDefinition(PhaseId.FINAL_GUESS, ControllerPolicy.LEADER, frozenset(("guess",))),
    PhaseDefinition(PhaseId.GAME_OVER, ControllerPolicy.NONE, frozenset()),
))
