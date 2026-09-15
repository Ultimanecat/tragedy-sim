"""Shared, deterministic search infrastructure for game-playing agents.

The objects in this module deliberately depend only on the engine's typed
``action_offers``/``transition`` surface.  They contain no room, HTTP, or UI
logic, and search traces are private diagnostics rather than observations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from typing import Any, Callable, Protocol

from .catalog import CHARACTERS


class SearchGame(Protocol):
    controller: str
    winner: str | None
    roles: dict[str, str]
    state: Any
    scenario: dict[str, Any]

    def action_offers(self, actor: str) -> list[Any]: ...
    def transition(self, action: Any) -> Any: ...
    def state_key(self, viewer: str = "spectator") -> str: ...
    def clone(self) -> "SearchGame": ...


@dataclass(frozen=True)
class SearchBudget:
    """Reproducible node budget with an optional wall-clock safety limit."""

    node_limit: int = 64
    rollout_depth: int = 24
    time_limit_ms: int | None = None
    exploration: float = math.sqrt(2.0)
    seed: int = 0

    def __post_init__(self) -> None:
        if type(self.node_limit) is not int or self.node_limit < 1:
            raise ValueError("node_limit must be a positive integer")
        if type(self.rollout_depth) is not int or self.rollout_depth < 1:
            raise ValueError("rollout_depth must be a positive integer")
        if (self.time_limit_ms is not None
                and (type(self.time_limit_ms) is not int or self.time_limit_ms < 1)):
            raise ValueError("time_limit_ms must be a positive integer or None")
        if not isinstance(self.exploration, (int, float)) or self.exploration < 0:
            raise ValueError("exploration must be a non-negative number")
        if type(self.seed) is not int:
            raise ValueError("seed must be an integer")


@dataclass(frozen=True)
class RootActionStats:
    action_id: str
    actor: str
    kind: str
    parameters: dict[str, Any]
    visits: int
    mean_value: float


@dataclass(frozen=True)
class SearchTrace:
    """One auditable decision trace; never included in a player view."""

    strategy: str
    seed: int
    root_key_hash: str
    node_limit: int
    rollout_depth: int
    time_limit_ms: int | None
    nodes: int
    iterations: int
    max_depth: int
    elapsed_ms: float
    stop_reason: str
    selected_action_id: str
    root_actions: tuple[RootActionStats, ...] = field(default_factory=tuple)

    @staticmethod
    def hash_state_key(state_key: str) -> str:
        return hashlib.sha256(state_key.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self), ensure_ascii=False, allow_nan=False))


class MastermindEvaluator:
    """Bounded full-information heuristic from the mastermind perspective."""

    def __call__(self, game: SearchGame) -> float:
        if game.winner == "mastermind":
            return 1.0
        if game.winner is not None:
            return -1.0

        characters = game.state.characters
        roles = game.roles
        score = 0.0

        # Immediate role routes: intrigue on the Key Person and Killer.
        for cid, role in roles.items():
            character = characters.get(cid)
            if character is None or not character.present:
                continue
            if role == "key":
                score += 0.18 * min(character.intrigue, 2) / 2
                if not character.alive:
                    score += 0.30
            elif role == "killer":
                score += 0.16 * min(character.intrigue, 4) / 4
            elif role == "friend" and not character.alive:
                score += 0.24

        # Events that are still relevant reward progress toward their threshold.
        current_day = game.state.round
        for incident in game.scenario.get("incidents", ()):
            if incident.get("day", 0) < current_day:
                continue
            culprit = characters.get(incident.get("culprit"))
            if culprit is None or not culprit.present or not culprit.alive:
                continue
            limit = max(1, CHARACTERS.get(culprit.id).limit
                        if culprit.id in CHARACTERS else 4)
            score += 0.10 * min(culprit.paranoia, limit) / limit

        board_pressure = sum(game.state.locations.values())
        character_pressure = sum(c.intrigue for c in characters.values()
                                 if c.present and c.alive)
        protagonist_resources = sum(c.goodwill + c.hope for c in characters.values()
                                    if c.present and c.alive)
        score += min(board_pressure, 8) * 0.012
        score += min(character_pressure, 16) * 0.006
        score -= min(protagonist_resources, 24) * 0.004
        return max(-0.85, min(0.85, score))


Evaluator = Callable[[SearchGame], float]
