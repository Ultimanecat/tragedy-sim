"""Defense value primitives (P1/P2).

P1 filters actions that fail an active hard threat. P2 provides the satisficing
survival term and a weighted score. Both are pure functions so they can be
tested before wiring any policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Collection, Mapping, Sequence

from ..composition import BeliefSnapshot
from .threats import ThreatAssessment, role_distribution


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


def long_term_slots(*, hard_threat: bool, cards_per_day: int = 1) -> int:
    """Reserve card slots for long-term work when no hard threat is active."""
    if type(cards_per_day) is not int or cards_per_day < 0:
        raise ValueError("cards_per_day must be a non-negative integer")
    if hard_threat:
        return 0
    return cards_per_day


def deadline_urgency(deadline: int | None, current_day: int, *,
                     horizon: int = 3) -> float:
    """Urgency rises as a deadline approaches; past deadlines are 1.0."""
    if type(current_day) is not int or type(horizon) is not int or horizon < 1:
        raise ValueError("current_day and horizon must be valid integers")
    if deadline is None:
        return 0.0
    lead = int(deadline) - current_day
    if lead <= 0:
        return 1.0
    return max(0.0, 1.0 - lead / (horizon + 1))


def information_value(snapshot: BeliefSnapshot | None,
                      view: Mapping[str, Any]) -> float:
    """Known-role fraction plus posterior concentration, averaged over alive cast."""
    distribution = role_distribution(snapshot)
    if not distribution:
        return 0.0
    characters = view.get("characters", {})
    alive = [cid for cid, state in characters.items()
             if isinstance(state, Mapping) and state.get("alive", False)]
    if not alive:
        return 0.0
    known = getattr(snapshot, "known_roles", {}) if snapshot is not None else {}
    known_fraction = sum(cid in known for cid in alive) / len(alive)
    concentrations = []
    for cid in alive:
        probabilities = distribution.get(cid, {})
        concentrations.append(max(probabilities.values()) if probabilities else 0.0)
    return 0.5 * known_fraction + 0.5 * sum(concentrations) / len(concentrations)


def final_guess_value(snapshot: BeliefSnapshot | None,
                      view: Mapping[str, Any]) -> float:
    """Mean top-role probability over alive characters, a cheap guess proxy."""
    distribution = role_distribution(snapshot)
    if not distribution:
        return 0.0
    characters = view.get("characters", {})
    alive = [cid for cid, state in characters.items()
             if isinstance(state, Mapping) and state.get("alive", False)]
    if not alive:
        return 0.0
    probabilities = [max(distribution.get(cid, {"?": 0.0}).values())
                     for cid in alive]
    return sum(probabilities) / len(probabilities)


@dataclass(frozen=True)
class DefenseCandidate:
    action: Any
    survival: float
    long_term: float
    information: float
    final_guess: float
    expected_loss: float
    covered_targets: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DefenseSelection:
    chosen: DefenseCandidate | None
    hard_ok: bool
    filter: HardThreatFilterResult
    scores: tuple[tuple[Any, float], ...]
    reason: str


def select_defense_action(candidates: Sequence[DefenseCandidate],
                          threats: Sequence[ThreatAssessment], *,
                          weights: DefenseValueWeights = DefenseValueWeights(),
                          survival_target: float = 0.8) -> DefenseSelection:
    """Apply hard filtering, then rank candidates by the layered value."""
    if not candidates:
        return DefenseSelection(None, False, filter_hard_actions((), threats, {}),
                                (), "no_candidates")
    actions = [candidate.action for candidate in candidates]
    coverage = {candidate.action: candidate.covered_targets
                for candidate in candidates}
    hard_filter = filter_hard_actions(actions, threats, coverage)
    allowed = set(hard_filter.allowed)
    feasible_hard = hard_filter.feasible
    scored = []
    for candidate in candidates:
        hard_ok = (not hard_filter.filtered
                   or (feasible_hard and candidate.action in allowed))
        value = DefenseValue(
            hard_ok=hard_ok,
            survival=candidate.survival,
            long_term=candidate.long_term,
            information=candidate.information,
            final_guess=candidate.final_guess,
            expected_loss=candidate.expected_loss)
        scored.append((candidate, score_defense_value(
            value, weights, survival_target=survival_target)))
    chosen = max(scored, key=lambda item: (item[1], -len(str(item[0].action))))[0]
    chosen_hard_ok = (not hard_filter.filtered
                      or (feasible_hard and chosen.action in allowed))
    if hard_filter.filtered and not feasible_hard:
        reason = "hard_infeasible"
    elif hard_filter.filtered:
        reason = "hard_filtered"
    else:
        reason = "soft_rank"
    return DefenseSelection(
        chosen=chosen, hard_ok=chosen_hard_ok,
        filter=hard_filter,
        scores=tuple((candidate.action, score) for candidate, score in scored),
        reason=reason)
