"""Pluggable cross-day defense obligations.

An obligation is a *structured* future requirement, not a hard-coded action.
Incident models decide how a scenario incident becomes an obligation, and a
scheduler scores candidate card bundles against the current obligations.

The first built-in model covers counter-threshold incidents such as BTX
suicide. Other incident kinds can be registered without editing the module.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from .composition import BeliefSnapshot
from .catalog import CHARACTERS


@dataclass(frozen=True)
class DefenseObligation:
    key: str
    day: int
    kind: str
    target: str
    counter: str
    current: int
    threshold: int
    required_max: int
    lead_days: int
    expected_pressure: int = 0
    action: str = "counter"
    threat: str | None = None
    priority: int = 0
    source: str = "scheduled_incident"
    confidence: float = 1.0

    @property
    def need(self) -> int:
        return max(0, self.current + self.expected_pressure - self.required_max)


@dataclass(frozen=True)
class DefenseContext:
    view: Mapping[str, Any]
    snapshot: BeliefSnapshot | None = None
    scenario: Mapping[str, Any] | None = None
    horizon_days: int = 3


@dataclass(frozen=True)
class DefenseAssessment:
    score: float
    covered: tuple[str, ...] = ()
    unmet: tuple[str, ...] = ()
    urgent: tuple[str, ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)


class IncidentModel(Protocol):
    """Turn one scheduled incident into zero or more obligations."""

    def extract(self, context: DefenseContext,
                incident: Mapping[str, Any]) -> tuple[DefenseObligation, ...]:
        ...


class CounterThresholdModel:
    """An incident that fires when a counter reaches the character limit."""

    def __init__(self, counter: str = "paranoia", *, safety_margin: int = 1,
                 expected_pressure: int = 0):
        if type(safety_margin) is not int or safety_margin < 1:
            raise ValueError("safety_margin must be a positive integer")
        if type(expected_pressure) is not int or expected_pressure < 0:
            raise ValueError("expected_pressure must be nonnegative")
        self.counter = counter
        self.safety_margin = safety_margin
        self.expected_pressure = expected_pressure

    def extract(self, context: DefenseContext,
                incident: Mapping[str, Any]) -> tuple[DefenseObligation, ...]:
        target = str(incident.get("culprit"))
        day = int(incident.get("day", 0))
        current_day = int(context.view.get("round", 1))
        lead = day - current_day
        if lead < 0 or lead > context.horizon_days:
            return ()
        characters = context.view.get("characters", {})
        character = characters.get(target) if isinstance(characters, Mapping) else None
        if not isinstance(character, Mapping):
            return ()
        current = character.get(self.counter)
        # The incident resolver uses the catalog character limit, not the
        # role-specific public limit shown in the board view.
        catalog = CHARACTERS.get(target)
        limit = catalog.limit if catalog is not None else character.get(
            f"{self.counter}_limit")
        if type(current) is not int or type(limit) is not int:
            return ()
        return (DefenseObligation(
            key=f"{day}:{incident.get('kind')}:{target}",
            day=day,
            kind=str(incident.get("kind")),
            target=target,
            counter=self.counter,
            current=current,
            threshold=limit,
            required_max=limit - self.safety_margin,
            lead_days=lead,
            expected_pressure=self.expected_pressure,
        ),)


class IncidentModelRegistry:
    """Kind -> model mapping; callers may add their own incident kinds."""

    def __init__(self, models: Mapping[str, IncidentModel] | None = None):
        if models is None:
            models = {"suicide": CounterThresholdModel("paranoia", expected_pressure=1)}
        self._models = dict(models)

    def register(self, kind: str, model: IncidentModel) -> None:
        if type(kind) is not str or not kind:
            raise ValueError("kind must be a non-empty string")
        self._models[kind] = model

    def model_for(self, kind: str) -> IncidentModel | None:
        return self._models.get(kind)


class ScheduledIncidentProvider:
    """Extract obligations from upcoming scenario incidents."""

    def __init__(self, registry: IncidentModelRegistry | None = None):
        self.registry = registry or IncidentModelRegistry()

    def extract(self, context: DefenseContext) -> tuple[DefenseObligation, ...]:
        scenario = context.scenario or {}
        incidents = scenario.get("incidents", ()) if isinstance(scenario, Mapping) else ()
        obligations = []
        for incident in incidents:
            if not isinstance(incident, Mapping):
                continue
            model = self.registry.model_for(str(incident.get("kind")))
            if model is None:
                continue
            obligations.extend(model.extract(context, incident))
        return tuple(obligations)


class ProtectTargetProvider:
    """Obligations to move loss-critical characters away from killers."""

    PROTECTED_ROLES = frozenset({"key", "friend", "time_traveler"})
    THREAT_ROLES = frozenset({"killer", "serial"})

    def extract(self, context: DefenseContext) -> tuple[DefenseObligation, ...]:
        scenario = context.scenario or {}
        cast = scenario.get("cast", {}) if isinstance(scenario, Mapping) else {}
        characters = context.view.get("characters", {})
        if not isinstance(cast, Mapping) or not isinstance(characters, Mapping):
            return ()
        protected = [cid for cid, role in cast.items()
                     if role in self.PROTECTED_ROLES]
        threats = [cid for cid, role in cast.items()
                   if role in self.THREAT_ROLES]
        pending_targets = {
            str(item.get("target")) for item in context.view.get("pending", ())
            if item.get("actor") == "m"}
        obligations = []
        for target in protected:
            target_state = characters.get(target, {})
            if not target_state.get("alive", False) or not target_state.get("present", False):
                continue
            # A killer needs the key at >= 2 intrigue. Blocking intrigue on
            # the incoming black target is stronger than relocating after the
            # face is revealed.
            if (target in pending_targets
                    or int(target_state.get("intrigue", 0)) >= 1):
                obligations.append(DefenseObligation(
                    key=f"protect_intrigue:{target}",
                    day=int(context.view.get("round", 1)),
                    kind="protect_target",
                    target=target,
                    counter="intrigue",
                    current=2,
                    threshold=2,
                    required_max=1,
                    lead_days=0,
                    action="block_intrigue",
                    priority=1,
                    source="protect_target",
                ))
            target_location = target_state.get("location")
            for threat in threats:
                threat_state = characters.get(threat, {})
                if not (threat_state.get("alive", False)
                        and threat_state.get("present", False)):
                    continue
                threat_location = threat_state.get("location")
                if threat_location != target_location:
                    continue
                role = cast.get(threat)
                others = [
                    cid for cid, state in characters.items()
                    if cid != threat and state.get("alive", False)
                    and state.get("present", False)
                    and state.get("location") == threat_location
                ]
                # Serial killers kill a lone character at day end. Moving the
                # protected target is the direct defense even when the same
                # location also carries a killer-intrigue threat.
                lone = role == "serial" and others == [target]
                if role == "killer" or lone:
                    obligations.append(DefenseObligation(
                        key=f"protect:{target}:{threat}",
                        day=int(context.view.get("round", 1)),
                        kind="protect_target",
                        target=target,
                        counter="location",
                        current=1,
                        threshold=0,
                        required_max=0,
                        lead_days=0,
                        action="move",
                        threat=threat,
                        priority=2,
                        source="protect_target",
                    ))
        return tuple(obligations)


class CounterThresholdScheduler:
    """Score a bundle by whether it closes scheduled counter obligations."""

    def __init__(self, *, reduction_card: str = "p-1", urgent_days: int = 1):
        if type(urgent_days) is not int or urgent_days < 0:
            raise ValueError("urgent_days must be nonnegative")
        self.reduction_card = reduction_card
        self.urgent_days = urgent_days

    def assess(self, obligations: Sequence[DefenseObligation],
               bundle: Sequence[Mapping[str, Any]],
               context: DefenseContext) -> DefenseAssessment:
        reductions = Counter()
        for command in bundle:
            if command.get("card") == self.reduction_card:
                reductions[str(command.get("target"))] += 1
        covered, unmet, urgent = [], [], []
        score = 0.0
        details = {}
        for obligation in obligations:
            if obligation.action == "move":
                moved = any(command.get("card") in {"h", "v", "d"}
                            and str(command.get("target")) == obligation.target
                            for command in bundle)
                reduction = 1 if moved else 0
                remaining = 0 if moved else 1
            elif obligation.action == "block_intrigue":
                blocked = any(command.get("card") == "fi"
                              and str(command.get("target")) == obligation.target
                              for command in bundle)
                reduction = 1 if blocked else 0
                remaining = 0 if blocked else 1
            else:
                reduction = reductions.get(obligation.target, 0)
                remaining = obligation.need - reduction
            met = remaining <= 0
            is_urgent = obligation.lead_days <= self.urgent_days
            if is_urgent:
                urgent.append(obligation.key)
            if met:
                covered.append(obligation.key)
                score += 2.0 if is_urgent else 1.0
            else:
                unmet.append(obligation.key)
                # Partial progress still counts, so an earlier-day -1 is not
                # scored the same as doing nothing just because one card is
                # insufficient for the whole deficit.
                score += 0.5 * min(reduction, obligation.need)
                score -= 2.0 if is_urgent else 1.0
            details[obligation.key] = {
                "target": obligation.target,
                "current": obligation.current,
                "expected_pressure": obligation.expected_pressure,
                "required_max": obligation.required_max,
                "need": obligation.need,
                "reduction": reduction,
                "met": met,
                "lead_days": obligation.lead_days,
            }
        return DefenseAssessment(score, tuple(covered), tuple(unmet),
                                 tuple(urgent), details)


class DefenseModule:
    """Pluggable provider + scheduler used by an action policy."""

    def __init__(self, provider, scheduler: CounterThresholdScheduler | None = None):
        if isinstance(provider, (tuple, list)):
            self.providers = tuple(provider)
        else:
            self.providers = (provider,)
        self.provider = self.providers[0] if len(self.providers) == 1 else None
        self.scheduler = scheduler or CounterThresholdScheduler()

    def obligations(self, context: DefenseContext) -> tuple[DefenseObligation, ...]:
        result = []
        for provider in self.providers:
            result.extend(provider.extract(context))
        return tuple(result)

    def ordered(self, context: DefenseContext) -> tuple[DefenseObligation, ...]:
        """Urgent first; moves beat same-day block/counter reactions."""
        return tuple(sorted(
            self.obligations(context),
            key=lambda item: (item.lead_days, -item.priority, item.key)))

    def assess(self, context: DefenseContext,
               bundle: Sequence[Mapping[str, Any]]) -> DefenseAssessment:
        return self.scheduler.assess(self.obligations(context), bundle, context)
