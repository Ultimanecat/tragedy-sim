"""Stable, namespaced identifiers used by extensible rules."""

from __future__ import annotations

from dataclasses import dataclass
import re


_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


def _validate_key(value: str, description: str) -> str:
    if not isinstance(value, str) or not _KEY_PATTERN.fullmatch(value):
        raise ValueError(f"{description}必须是带命名空间的小写标识，例如 core.day_start")
    return value


@dataclass(frozen=True, order=True)
class PhaseKey:
    """Open phase identifier; rulesets may add their own namespace."""

    value: str

    def __post_init__(self) -> None:
        _validate_key(self.value, "阶段标识")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, order=True)
class RuleSource:
    """Machine-readable source of an offer, activation, or trace entry."""

    value: str

    def __post_init__(self) -> None:
        _validate_key(self.value, "规则来源")

    def __str__(self) -> str:
        return self.value


CORE_PHASES = {
    name: PhaseKey(f"core.{name}")
    for name in (
        "day_start", "mastermind_actions", "protagonist_actions", "action_resolution",
        "mastermind_abilities", "protagonist_abilities", "incident", "day_end",
        "loop_end", "final_guess", "game_over",
    )
}
