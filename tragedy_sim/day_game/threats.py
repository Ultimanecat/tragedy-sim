"""Structured threat assessment for defense valuation (P0).

P0 only classifies threats. It does not choose actions and does not change the
default AI. Hard role knowledge and posterior guesses are kept separate so the
later value layer can treat known immediate losses as constraints.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..composition import BeliefSnapshot


@dataclass(frozen=True)
class ThreatAssessment:
    target: str
    failure_kind: str
    role: str | None
    confidence: float
    severity: float
    deadline: int | None
    active_now: bool
    source: str
    hard: bool

    def to_dict(self):
        return {
            "target": self.target,
            "failure_kind": self.failure_kind,
            "role": self.role,
            "confidence": self.confidence,
            "severity": self.severity,
            "deadline": self.deadline,
            "active_now": self.active_now,
            "source": self.source,
            "hard": self.hard,
        }


PROTECTED_ROLES = frozenset({"key", "friend", "time_traveler"})
THREAT_ROLES = frozenset({"killer", "serial"})
INCIDENT_SEVERITY = {
    "murder": 1.0,
    "serial_murder": 1.0,
    "suicide": 1.0,
    "hospital": 0.9,
    "missing": 0.9,
    "unease": 0.8,
    "butterfly": 0.8,
    "spreading": 0.8,
}


def _characters(view: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    value = view.get("characters", {})
    return value if isinstance(value, Mapping) else {}


def role_distribution(snapshot: BeliefSnapshot | None) -> dict[str, dict[str, float]]:
    """Role probabilities: hard known roles first, otherwise particle majority/frequency."""
    if snapshot is None:
        return {}
    if snapshot.known_roles:
        return {cid: {str(role): 1.0}
                for cid, role in snapshot.known_roles.items()}
    worlds = getattr(snapshot, "worlds", ())
    if not worlds:
        return {}
    counts: dict[str, Counter] = {}
    for world in worlds:
        for cid, role in getattr(world, "roles", {}).items():
            counts.setdefault(str(cid), Counter())[str(role)] += 1
    total = len(worlds)
    return {cid: {role: count / total for role, count in counter.items()}
            for cid, counter in counts.items()}


def _hard_roles(snapshot: BeliefSnapshot | None) -> dict[str, str]:
    if snapshot is None or not snapshot.known_roles:
        return {}
    return {str(cid): str(role) for cid, role in snapshot.known_roles.items()}


def classify_threats(*, view: Mapping[str, Any],
                     snapshot: BeliefSnapshot | None = None,
                     scenario: Mapping[str, Any] | None = None,
                     role_threshold: float = 0.6,
                     horizon_days: int = 3,
                     ) -> tuple[ThreatAssessment, ...]:
    """Classify near-term losses without deciding how to defend them.

    Hard known roles produce hard threats. Particle-only roles produce
    probability-weighted threats. Scheduled incidents use known culprits only;
    unknown culprits stay unknown rather than reading the scenario culprit.
    """
    if not 0 < role_threshold <= 1:
        raise ValueError("role_threshold must be in (0, 1]")
    if type(horizon_days) is not int or horizon_days < 1:
        raise ValueError("horizon_days must be a positive integer")
    characters = _characters(view)
    hard = _hard_roles(snapshot)
    distribution = role_distribution(snapshot)
    current_day = int(view.get("round", 1))
    threats: list[ThreatAssessment] = []

    def state(cid: str) -> Mapping[str, Any]:
        value = characters.get(cid, {})
        return value if isinstance(value, Mapping) else {}

    threat_locations = set()
    for cid, role_probs in distribution.items():
        character = state(cid)
        if not character.get("alive", False) or not character.get("present", False):
            continue
        if any(role in THREAT_ROLES and confidence >= role_threshold
               for role, confidence in role_probs.items()):
            threat_locations.add(character.get("location"))

    # Known or likely loss-critical characters.
    for cid, role_probs in distribution.items():
        if cid not in characters:
            continue
        character = state(cid)
        if not character.get("alive", False) or not character.get("present", False):
            continue
        for role, confidence in role_probs.items():
            if role not in PROTECTED_ROLES or confidence < role_threshold:
                continue
            active = character.get("location") in threat_locations
            deadline = None
            source = "hard_role" if cid in hard else "posterior_role"
            threats.append(ThreatAssessment(
                target=cid, failure_kind="character_loss", role=role,
                confidence=confidence, severity=1.0, deadline=deadline,
                active_now=active, source=source, hard=cid in hard))
            break

    # Known/posterior killers are threats, not protected targets.
    for cid, role_probs in distribution.items():
        if cid not in characters or not state(cid).get("alive", False):
            continue
        for role, confidence in role_probs.items():
            if role not in THREAT_ROLES or confidence < role_threshold:
                continue
            threats.append(ThreatAssessment(
                target=cid, failure_kind="role_threat", role=role,
                confidence=confidence, severity=0.9, deadline=None,
                active_now=True,
                source="hard_role" if cid in hard else "posterior_role",
                hard=cid in hard))
            break

    # Scheduled incidents: only classifier-known culprits are targeted.
    if scenario is not None:
        known_culprits = {}
        if snapshot is not None:
            known_culprits = {int(day): str(cid)
                              for day, cid in snapshot.known_culprits.items()}
        for incident in scenario.get("incidents", ()) or ():
            if not isinstance(incident, Mapping):
                continue
            day = int(incident.get("day", 0))
            lead = day - current_day
            if lead < 0 or lead > horizon_days:
                continue
            culprit = known_culprits.get(day)
            if culprit is None:
                continue
            kind = str(incident.get("kind"))
            threats.append(ThreatAssessment(
                target=culprit, failure_kind="incident", role=kind,
                confidence=1.0,
                severity=INCIDENT_SEVERITY.get(kind, 0.8),
                deadline=day, active_now=lead == 0,
                source="known_culprit", hard=True))

    order = {"character_loss": 0, "role_threat": 1, "incident": 2}
    return tuple(sorted(threats, key=lambda item: (
        order.get(item.failure_kind, 9), not item.hard,
        -(item.confidence * item.severity),
        item.deadline if item.deadline is not None else 999,
        item.target)))
