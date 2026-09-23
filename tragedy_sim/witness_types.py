"""Rule independent witness values shared by compilers and matchers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class WitnessStrength(StrEnum):
    HARD = "hard"
    SOFT = "soft"


class WitnessVerdict(StrEnum):
    SATISFIED = "satisfied"
    CONTRADICTED = "contradicted"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PublicWitness:
    kind: str
    subject: str
    value: Any
    loop: int
    day: int
    timing: str
    source: str
    strength: WitnessStrength = WitnessStrength.HARD


@dataclass(frozen=True)
class WitnessEvaluation:
    compatible: bool
    verdicts: tuple[tuple[PublicWitness, WitnessVerdict], ...]

    @property
    def contradicted(self) -> tuple[PublicWitness, ...]:
        return tuple(witness for witness, verdict in self.verdicts
                     if verdict == WitnessVerdict.CONTRADICTED)
