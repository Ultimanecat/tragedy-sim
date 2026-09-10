"""Phase resolver contracts and small reusable resolver policies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

from ..cards import ACTOR_NAMES
from ..engine import RuleError
from ..flow import MATCH_FLOW
from ..model import PhaseId, TimingId, timing_for_phase
from ..domain.keys import PhaseKey

if TYPE_CHECKING:
    from ..game import Game


class PhaseResolver(ABC):
    """Owns input and advancement behavior for one public engine phase."""

    phase: PhaseId | PhaseKey

    def timing(self, game: "Game") -> TimingId:
        if isinstance(self.phase, PhaseKey):
            raise NotImplementedError("扩展阶段必须声明规则时间点")
        return timing_for_phase(self.phase)

    def validate_command(self, action: str, arguments: dict[str, Any]) -> None:
        if isinstance(self.phase, PhaseKey):
            raise NotImplementedError("扩展阶段必须声明命令结构")
        MATCH_FLOW.validate_command(self.phase, action, arguments)

    def controller(self, game: "Game") -> str | None:
        return MATCH_FLOW.controller(self.phase, leader=game.state.leader,
                                     next_actor=game.next_actor)

    def authorize(self, game: "Game", actor: str, action: str) -> None:
        if actor != self.controller(game):
            name = ACTOR_NAMES.get(self.controller(game), "无人")
            raise RuleError(f"当前需要 {name} 操作")

    @abstractmethod
    def legal_actions(self, game: "Game", actor: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    def execute(self, game: "Game", actor: str, action: str,
                arguments: dict[str, Any]) -> None: ...


class NextPhaseResolver(PhaseResolver):
    def legal_actions(self, game: "Game", actor: str) -> list[dict[str, Any]]:
        if actor != self.controller(game):
            return []
        return [{"actor": actor, "action": "next"}]

    def execute(self, game: "Game", actor: str, action: str,
                arguments: dict[str, Any]) -> None:
        raise NotImplementedError(f"{self.phase.value} 尚未实现阶段推进")


class ChoicePhaseResolver(PhaseResolver):
    may_finish = True

    def legal_actions(self, game: "Game", actor: str) -> list[dict[str, Any]]:
        if actor != self.controller(game):
            return []
        choices = [
            {"actor": actor, "action": "choose", "index": index}
            for index, choice in enumerate(game.options(actor), 1)
            if not choice.get("finish")
        ]
        if self.may_finish:
            choices.append({"actor": actor, "action": "next"})
        return choices

    def execute(self, game: "Game", actor: str, action: str,
                arguments: dict[str, Any]) -> None:
        if action == "choose":
            game._choose(actor, arguments["index"])
        else:
            self.advance(game)

    def advance(self, game: "Game") -> None:
        raise NotImplementedError(f"{self.phase.value} 尚未实现阶段推进")
