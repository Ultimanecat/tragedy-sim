"""Public incident effects that constrain culprit identity or location."""

from __future__ import annotations

from typing import Any, Mapping

from ..witness_types import PublicWitness


def compile_suicide_victims(view: Mapping[str, Any]) -> list[PublicWitness]:
    """The victim of a successful Suicide is the incident's culprit."""
    events = tuple(view.get("events", ()))
    result: list[PublicWitness] = []
    for index, event in enumerate(events):
        if (event.get("kind") != "incident_status"
                or event.get("incident") != "suicide"
                or not bool(event.get("happened", False))):
            continue
        victim = None
        for follow in events[index + 1:]:
            kind = follow.get("kind")
            if kind in {"incident_status", "day_ended"}:
                break
            if kind == "character_died":
                target = follow.get("target")
                if isinstance(target, str):
                    victim = ("part_timer" if target == "part_timer_question"
                              else target)
                break
            if kind == "incident_ended":
                break
        if victim is None:
            continue
        result.append(PublicWitness(
            "culprit_is", str(int(event.get(
                "round", view.get("round", 1)))), victim,
            int(event.get("loop", view.get("loop", 1))),
            int(event.get("round", view.get("round", 1))),
            "incident", "public_suicide_victim"))
    return result


def compile_suicide_prevented_targets(
        view: Mapping[str, Any]) -> list[PublicWitness]:
    """A prevented Suicide still targets its culprit, not the substitute victim."""
    events = tuple(view.get("events", ()))
    result: list[PublicWitness] = []
    for index, event in enumerate(events):
        if (event.get("kind") != "incident_status"
                or event.get("incident") != "suicide"
                or not bool(event.get("happened", False))):
            continue
        target = None
        for follow in events[index + 1:]:
            if (follow.get("loop") != event.get("loop")
                    or follow.get("round") != event.get("round")):
                break
            kind = follow.get("kind")
            if kind in {"incident_status", "incident_ended", "day_ended"}:
                break
            if kind in {"death_prevented", "guard_spent"}:
                target = follow.get("target")
                break
            if kind == "death_replaced":
                protected = follow.get("protected", ())
                if isinstance(protected, (list, tuple)) and len(protected) == 1:
                    target = protected[0]
                break
            if kind == "character_died":
                break
        if not isinstance(target, str):
            continue
        subject = ("part_timer" if target == "part_timer_question"
                   else target)
        day = int(event.get("round", view.get("round", 1)))
        result.append(PublicWitness(
            "culprit_is", str(day), subject,
            int(event.get("loop", view.get("loop", 1))), day,
            "incident", "public_suicide_prevented_target"))
    return result


def compile_guru_incidents(view: Mapping[str, Any]) -> list[PublicWitness]:
    """A public doubled-effect announcement identifies the scheduled culprit."""
    events = tuple(view.get("events", ()))
    result: list[PublicWitness] = []
    for index, event in enumerate(events):
        if (event.get("kind") != "incident_status"
                or not bool(event.get("happened", False))):
            continue
        for follow in events[index + 1:]:
            if (follow.get("loop") != event.get("loop")
                    or follow.get("round") != event.get("round")):
                break
            kind = follow.get("kind")
            if kind in {"incident_status", "incident_ended", "day_ended"}:
                break
            if kind != "incident_effect_doubled":
                continue
            if follow.get("character") != "guru":
                break
            day = int(event.get("round", view.get("round", 1)))
            result.append(PublicWitness(
                "culprit_is", str(day), "guru",
                int(event.get("loop", view.get("loop", 1))), day,
                "incident", "public_guru_incident_doubled"))
            break
    return result


def compile_effective_incidents(view: Mapping[str, Any]) -> list[PublicWitness]:
    """Black Cat's incident never has an effect; a positive effect excludes it."""
    characters = view.get("characters", {})
    if "black_cat" not in characters:
        return []
    candidates = tuple(sorted(
        ("part_timer" if cid == "part_timer_question" else str(cid))
        for cid in characters if cid != "black_cat"))
    events = tuple(view.get("events", ()))
    result: list[PublicWitness] = []
    for index, event in enumerate(events):
        if (event.get("kind") != "incident_status"
                or not bool(event.get("happened", False))):
            continue
        for follow in events[index + 1:]:
            if (follow.get("loop") != event.get("loop")
                    or follow.get("round") != event.get("round")):
                break
            kind = follow.get("kind")
            if kind == "incident_status" or kind == "day_ended":
                break
            if kind != "incident_ended":
                continue
            if follow.get("effective") is True:
                day = int(event.get("round", view.get("round", 1)))
                result.append(PublicWitness(
                    "culprit_in", str(day), candidates,
                    int(event.get("loop", view.get("loop", 1))), day,
                    "incident", "public_effective_incident_excludes_black_cat"))
            break
    return result


def compile_direct_culprits(view: Mapping[str, Any]) -> list[PublicWitness]:
    """A positive Missing movement reveals the moving culprit."""
    rules = {
        "missing": ("character_moved", ("target", "character"),
                    "public_missing_moved_culprit"),
    }
    events = tuple(view.get("events", ()))
    result: list[PublicWitness] = []
    for index, event in enumerate(events):
        rule = rules.get(str(event.get("incident")))
        if (event.get("kind") != "incident_status"
                or not bool(event.get("happened", False))
                or rule is None):
            continue
        effect_kind, target_fields, source = rule
        culprit = None
        for follow in events[index + 1:]:
            kind = follow.get("kind")
            if kind in {"incident_status", "incident_ended", "day_ended"}:
                break
            if kind != effect_kind:
                continue
            target = next((follow.get(field) for field in target_fields
                           if isinstance(follow.get(field), str)), None)
            if isinstance(target, str):
                culprit = ("part_timer" if target == "part_timer_question"
                           else target)
            break
        if culprit is None:
            continue
        incident_day = int(event.get("round", view.get("round", 1)))
        result.append(PublicWitness(
            "culprit_is", str(incident_day), culprit,
            int(event.get("loop", view.get("loop", 1))), incident_day,
            "incident", source))
    return result


def compile_effect_locations(view: Mapping[str, Any]) -> list[PublicWitness]:
    """An effect at the culprit's location narrows the culprit candidates."""
    effect_kinds = {
        "murder": frozenset({"character_died", "death_prevented",
                              "guard_spent", "death_replaced"}),
        "butterfly": frozenset({"counter_changed"}),
    }
    events = tuple(view.get("events", ()))
    result: list[PublicWitness] = []
    for index, event in enumerate(events):
        incident = str(event.get("incident"))
        allowed_effects = effect_kinds.get(incident)
        characters = event.get("characters")
        if (event.get("kind") != "incident_status"
                or not bool(event.get("happened", False))
                or allowed_effects is None
                or not isinstance(characters, Mapping)):
            continue
        target = None
        for follow in events[index + 1:]:
            kind = follow.get("kind")
            if kind in {"incident_status", "incident_ended", "day_ended"}:
                break
            if kind not in allowed_effects:
                continue
            if kind == "death_replaced":
                protected = follow.get("protected", ())
                candidate = (protected[0] if isinstance(protected, list)
                             and protected else None)
            else:
                candidate = follow.get("target")
            if isinstance(candidate, str) and candidate in characters:
                target = candidate
            break
        target_state = characters.get(target) if target is not None else None
        target_location = (target_state.get("location")
                           if isinstance(target_state, Mapping) else None)
        if not isinstance(target_location, str):
            continue
        candidates = tuple(sorted(
            ("part_timer" if cid == "part_timer_question" else str(cid))
            for cid, state in characters.items()
            if isinstance(state, Mapping)
            and state.get("location") == target_location
            and bool(state.get("present", False))
            and bool(state.get("alive", False))
            and not (incident == "murder" and cid == target)))
        if not candidates:
            continue
        incident_day = int(event.get("round", view.get("round", 1)))
        result.append(PublicWitness(
            "culprit_in", str(incident_day), candidates,
            int(event.get("loop", view.get("loop", 1))), incident_day,
            "incident", "public_incident_effect_location"))
    return result
