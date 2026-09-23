"""BTX public observations that uniquely identify Time Traveler."""

from __future__ import annotations

from typing import Any, Mapping

from ..witness_types import PublicWitness


def compile_ignored_goodwill_forbids(
        view: Mapping[str, Any]) -> list[PublicWitness]:
    """A successful goodwill card through Forbidden Goodwill reveals the role."""
    if view.get("module") != "BTX":
        return []
    result: list[PublicWitness] = []
    ignored_targets: set[str] = set()
    for event in view.get("events", ()):
        kind = event.get("kind")
        if kind == "cards_revealed":
            cards = event.get("cards", ())
            forbidden = {str(item.get("target")) for item in cards
                         if item.get("actor") == "m"
                         and item.get("card") == "fg"}
            goodwill = {str(item.get("target")) for item in cards
                        if item.get("actor") != "m"
                        and item.get("card") in {"g1", "g2"}}
            ignored_targets = forbidden & goodwill
            continue
        if kind == "actions_resolved":
            ignored_targets = set()
            continue
        target = event.get("target")
        if (kind == "counter_changed" and target in ignored_targets
                and event.get("counter") == "goodwill"
                and isinstance(event.get("before"), int)
                and isinstance(event.get("after"), int)
                and event["after"] > event["before"]):
            result.append(PublicWitness(
                "role_is", str(target), "time_traveler",
                int(event.get("loop", view.get("loop", 1))),
                int(event.get("round", view.get("round", 1))),
                str(event.get("timing", "action_resolution")),
                "public_goodwill_forbid_ignored"))
    return result


def compile_death_prevention(view: Mapping[str, Any]) -> list[PublicWitness]:
    """BTX's explicit death-prevention event uniquely identifies the role."""
    if view.get("module") != "BTX":
        return []
    result: list[PublicWitness] = []
    for event in view.get("events", ()):
        if event.get("kind") != "death_prevented":
            continue
        target = event.get("target")
        if not isinstance(target, str):
            continue
        subject = ("part_timer" if target == "part_timer_question"
                   else target)
        result.append(PublicWitness(
            "role_is", subject, "time_traveler",
            int(event.get("loop", view.get("loop", 1))),
            int(event.get("round", view.get("round", 1))),
            str(event.get("timing", "unknown")),
            "public_time_traveler_death_prevention"))
    return result
