"""Defense value primitives (P1/P2).

P1 filters actions that fail an active hard threat. P2 provides the satisficing
survival term and a weighted score. Both are pure functions so they can be
tested before wiring any policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Collection, Mapping, Sequence

from .threats import ThreatAssessment


@dataclass(frozen=True)
class HardThreatFilterResult:
    allowed: tuple[Any, ...]
    required_targets: frozenset[str]
    filtered: bool
    feasible: bool
    threats: tuple[ThreatAssessment, ...]


def filter_hard_actions(actions: Sequence[Any],
                        threats: Sequence[ThreatAssessment],
                        coverage: Mapping[Any, Collection[str]],
                        ) -> HardThreatFilterResult:
    """Keep actions covering at least one active hard threat.

    Callers provide ``coverage[action]`` = targets defended by that action.
    If no action covers a hard threat, the filter is infeasible and returns all
    actions so the caller can fall back to expected-risk scoring.
    """
    hard = tuple(threat for threat in threats if threat.hard and threat.active_now)
    required = frozenset(threat.target for threat in hard)
    if not hard:
        return HardThreatFilterResult(tuple(actions), required, False, True, hard)
    allowed = tuple(action for action in actions
                    if required.intersection(coverage.get(action, ())))
    if allowed:
        return HardThreatFilterResult(allowed, required, True, True, hard)
    return HardThreatFilterResult(tuple(actions), required, True, False, hard)


def satisficed_survival(probability: float, target: float = 0.8) -> float:
    """Survival credit saturates at the target; extra survival gets no credit."""
    if not 0 <= probability <= 1:
        raise ValueError("probability must be in [0, 1]")
    if not 0 < target <= 1:
        raise ValueError("target must be in (0, 1]")
    return min(1.0, probability / target)


@dataclass(frozen=True)
class DefenseValue:
    hard_ok: bool
    survival: float
    long_term: float
    information: float
    final_guess: float
    expected_loss: float


@dataclass(frozen=True)
class DefenseValueWeights:
    survival: float = 1.0
    long_term: float = 1.0
    information: float = 1.0
    final_guess: float = 1.0
    expected_loss: float = 1.0
    hard_bonus: float = 1000.0


def score_defense_value(value: DefenseValue,
                        weights: DefenseValueWeights = DefenseValueWeights(),
                        *, survival_target: float = 0.8) -> float:
    """Weighted score with hard constraint as a dominant bonus."""
    if not value.hard_ok:
        hard_term = 0.0
    else:
        hard_term = weights.hard_bonus
    return (hard_term
            + weights.survival * satisficed_survival(value.survival, survival_target)
            + weights.long_term * value.long_term
            + weights.information * value.information
            + weights.final_guess * value.final_guess
            - weights.expected_loss * value.expected_loss)
