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
    """Abilities that can lower ``counter``.

    Only ``transfer`` is turned into a concrete multi-day plan today; the other
    kinds are returned so callers can see them in diagnostics, and
    ``plan_counter_defense`` reports ``blocked_reason`` when only those exist.
    """
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
    others = {item.kind for item in capabilities}
    if others:
        return AbilityDefensePlan(
            target, counter, need, None, (),
            f"only transfer is planned; found {sorted(others)}")
    return AbilityDefensePlan(target, counter, need, None, (),
                              "no transfer capability in scenario")


@dataclass(frozen=True)
class DayAbilityPlan:
    card_plan: tuple[dict[str, Any], ...]
    effect: CapabilityStep | None
    blocked_reason: str | None = None


def build_day_ability_plan(world, plan: AbilityDefensePlan, *,
                           plan_length: int = 3) -> DayAbilityPlan:
    """Turn capability steps into legal current-day card placements.

    Only playwright-visible legality is checked here; ability effects are
    selected separately by ``find_ability_option`` during the goodwill phase.
    """
    if plan.blocked_reason or plan.capability is None:
        return DayAbilityPlan((), None, plan.blocked_reason or "no capability")
    actions = [item for item in world.legal_actions(world.controller)
               if item.get("action") == "play"]
    if not actions:
        return DayAbilityPlan((), None, "no legal card placement")

    def pick(card: str | None, target: str | None):
        for action in actions:
            if (card is not None and action.get("card") == card
                    and action.get("target") == target):
                return action
        return None

    chosen = []
    used_targets = set()
    for step in plan.steps:
        if step.kind == "setup_goodwill":
            action = pick(step.card, step.target)
            if action is None:
                return DayAbilityPlan(tuple(chosen), None,
                                      f"missing setup card {step.card} for {step.target}")
        elif step.kind == "move":
            action = next((item for item in actions
                           if item.get("card") in {"h", "v", "d"}
                           and item.get("target") == step.target), None)
            if action is None:
                return DayAbilityPlan(tuple(chosen), None,
                                      f"missing movement card for {step.target}")
        else:
            continue
        if action["target"] in used_targets:
            return DayAbilityPlan(tuple(chosen), None,
                                  f"two setup steps target {action['target']} on one day")
        chosen.append(dict(action))
        used_targets.add(action["target"])
    for action in actions:
        if len(chosen) >= plan_length:
            break
        if action.get("target") in used_targets:
            continue
        chosen.append(dict(action))
        used_targets.add(action["target"])
    if len(chosen) != plan_length:
        return DayAbilityPlan(tuple(chosen), None, "not enough distinct card targets")
    effect = next((step for step in plan.steps if step.kind == "use_transfer"), None)
    return DayAbilityPlan(tuple(chosen), effect)


def schedule_ability_steps(plan: AbilityDefensePlan, *, max_days: int = 4
                           ) -> "ScheduledAbilityPlan":
    """Split card setup steps across days; the effect lands on the last day."""
    if type(max_days) is not int or max_days < 1:
        raise ValueError("max_days must be a positive integer")
    if plan.blocked_reason or plan.capability is None:
        return ScheduledAbilityPlan((), plan.blocked_reason or "no capability")
    days: list[list[CapabilityStep]] = []
    effect = None
    for step in plan.steps:
        if step.kind == "use_transfer":
            effect = step
            continue
        for day in days:
            if step.target not in {item.target for item in day}:
                day.append(step)
                break
        else:
            if len(days) >= max_days:
                return ScheduledAbilityPlan((), "ability setup exceeds max_days")
            days.append([step])
    if effect is not None:
        if not days:
            days.append([])
        days[-1].append(effect)
    return ScheduledAbilityPlan(tuple(tuple(day) for day in days))


@dataclass(frozen=True)
class ScheduledAbilityPlan:
    days: tuple[tuple[CapabilityStep, ...], ...]
    blocked_reason: str | None = None


def build_real_day_plan(world, steps: Sequence[CapabilityStep], *,
                        plan_length: int = 3,
                        avoid_targets: Sequence[str] = ()) -> DayAbilityPlan:
    """Build a legal multi-seat plan on a concrete Game, one action at a time."""
    current = world
    chosen = []
    used_targets = set()
    avoided = set(avoid_targets)
    pending = [step for step in steps
               if step.kind in {"setup_goodwill", "move"}]
    for _ in range(plan_length):
        if current.state.phase != "protagonists":
            return DayAbilityPlan(tuple(chosen), None, "left protagonist phase")
        actions = [item for item in current.legal_actions(current.controller)
                   if item.get("action") == "play"]
        if not actions:
            return DayAbilityPlan(tuple(chosen), None, "no legal card placement")
        action = None
        for step in list(pending):
            if step.kind == "setup_goodwill":
                action = next((item for item in actions
                               if item.get("card") == step.card
                               and item.get("target") == step.target), None)
            elif step.kind == "move":
                action = next((item for item in actions
                               if item.get("card") in {"h", "v", "d"}
                               and item.get("target") == step.target), None)
            if action is not None and action["target"] not in used_targets:
                pending.remove(step)
                break
            action = None
        if action is None:
            safe = [item for item in actions
                    if item.get("target") not in used_targets
                    and item.get("target") not in avoided
                    and item.get("card") not in {"p1"}]
            action = (safe or [item for item in actions
                               if item.get("target") not in used_targets] or [None])[0]
        if action is None:
            return DayAbilityPlan(tuple(chosen), None, "no distinct filler target")
        chosen.append(dict(action))
        used_targets.add(action["target"])
        current = current.transition(action).game
    effect = next((step for step in steps if step.kind == "use_transfer"), None)
    return DayAbilityPlan(tuple(chosen), effect)


def find_ability_option(game, *, effect_kind: str, source: str | None = None,
                        sink: str | None = None):
    """Find the goodwill-phase ``choose`` action for a planned ability effect."""
    actor = game.controller
    options = game.options(actor)
    for index, choice in enumerate(options, 1):
        for effect in choice.get("effects", ()) or ():
            if effect.get("kind") != effect_kind:
                continue
            if source is not None and effect.get("source") != source:
                continue
            if sink is not None and effect.get("target") != sink:
                continue
            return {"actor": actor, "action": "choose", "index": index}
    return None
