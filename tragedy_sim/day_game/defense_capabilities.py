"""Ability-based defense chains (first concrete slice).

Cards are not the only way to move counters: character goodwill abilities can
adjust or transfer counters, but they need setup (goodwill threshold, position,
a second target). This module extracts those capabilities and builds a small
diagnostic plan. It is not wired into the default AI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..catalog import CHARACTERS


@dataclass(frozen=True)
class AbilityCapability:
    actor: str
    ability: str
    kind: str
    counter: str | None
    amount: int | None
    threshold: int | None
    scope: str
    text: str


@dataclass(frozen=True)
class CapabilityStep:
    kind: str
    actor: str | None = None
    card: str | None = None
    target: str | None = None
    ability: str | None = None
    source: str | None = None
    sink: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class AbilityDefensePlan:
    target: str
    counter: str
    need: int
    capability: AbilityCapability | None
    steps: tuple[CapabilityStep, ...]
    blocked_reason: str | None = None


def scenario_capabilities(scenario: Mapping[str, Any]) -> tuple[AbilityCapability, ...]:
    cast = scenario.get("cast", {}) if isinstance(scenario, Mapping) else {}
    capabilities = []
    for cid in cast:
        definition = CHARACTERS.get(cid)
        if definition is None:
            continue
        for ability in definition.abilities:
            capabilities.append(AbilityCapability(
                actor=cid,
                ability=ability.id,
                kind=ability.kind,
                counter=getattr(ability, "counter", None),
                amount=getattr(ability, "amount", None),
                threshold=ability.threshold,
                scope=ability.scope,
                text=ability.text,
            ))
    return tuple(capabilities)


def counter_reduction_capabilities(
        scenario: Mapping[str, Any], counter: str = "paranoia"
        ) -> tuple[AbilityCapability, ...]:
    return tuple(
        item for item in scenario_capabilities(scenario)
        if item.counter == counter and item.kind in {"counter", "adjust", "transfer", "reset_all"}
        and (item.kind == "transfer" or item.amount is None or item.amount < 0)
    )


def _character(view: Mapping[str, Any], cid: str) -> Mapping[str, Any]:
    characters = view.get("characters", {})
    if not isinstance(characters, Mapping):
        return {}
    value = characters.get(cid, {})
    return value if isinstance(value, Mapping) else {}


def _sink_candidates(view: Mapping[str, Any], location: str,
                     exclude: Sequence[str]) -> list[str]:
    characters = view.get("characters", {})
    if not isinstance(characters, Mapping):
        return []
    excluded = set(exclude)
    result = []
    for cid, state in characters.items():
        if cid in excluded or not isinstance(state, Mapping):
            continue
        if not state.get("alive", False) or not state.get("present", False):
            continue
        if state.get("location") != location:
            continue
        limit = state.get("paranoia_limit")
        paranoia = state.get("paranoia")
        margin = (limit - paranoia) if type(limit) is int and type(paranoia) is int else 99
        result.append((margin, str(cid)))
    return [cid for _, cid in sorted(result, reverse=True)]


def plan_counter_defense(scenario: Mapping[str, Any], view: Mapping[str, Any], *,
                         target: str, need: int, counter: str = "paranoia"
                         ) -> AbilityDefensePlan:
    if type(need) is not int or need < 0:
        raise ValueError("need must be a nonnegative integer")
    if need == 0:
        return AbilityDefensePlan(target, counter, need, None, ())
    capabilities = counter_reduction_capabilities(scenario, counter)
    target_state = _character(view, target)
    if not target_state.get("alive", False) or not target_state.get("present", False):
        return AbilityDefensePlan(target, counter, need, None, (),
                                  "target not alive and present")
    transfers = [item for item in capabilities if item.kind == "transfer"]
    for capability in transfers:
        actor_state = _character(view, capability.actor)
        if not actor_state.get("alive", False) or not actor_state.get("present", False):
            continue
        location = target_state.get("location")
        steps = []
        goodwill = actor_state.get("goodwill", 0)
        threshold = capability.threshold or 0
        if type(goodwill) is not int:
            goodwill = 0
        gap = max(0, threshold - goodwill)
        if gap >= 2:
            steps.append(CapabilityStep("setup_goodwill", actor=capability.actor,
                                        card="g2", target=capability.actor,
                                        reason=f"goodwill gap {gap}"))
        elif gap == 1:
            steps.append(CapabilityStep("setup_goodwill", actor=capability.actor,
                                        card="g1", target=capability.actor,
                                        reason="goodwill gap 1"))
        if actor_state.get("location") != location:
            steps.append(CapabilityStep("move", actor=capability.actor, card="move",
                                        target=capability.actor,
                                        reason=f"move to {location}"))
        others = [cid for cid, state in view.get("characters", {}).items()
                  if isinstance(state, Mapping) and cid != capability.actor
                  and state.get("alive", False) and state.get("present", False)
                  and state.get("location") == location]
        if len(others) < 2:
            return AbilityDefensePlan(target, counter, need, capability, tuple(steps),
                                      "transfer needs two other characters in area")
        sinks = _sink_candidates(view, location, (target, capability.actor))
        if not sinks:
            return AbilityDefensePlan(target, counter, need, capability, tuple(steps),
                                      "no safe transfer sink")
        steps.append(CapabilityStep("use_transfer", actor=capability.actor,
                                    ability=capability.ability, source=target,
                                    sink=sinks[0],
                                    reason=f"move {counter} off target"))
        return AbilityDefensePlan(target, counter, need, capability, tuple(steps))
    return AbilityDefensePlan(target, counter, need, None, (),
                              "no transfer capability in scenario")
