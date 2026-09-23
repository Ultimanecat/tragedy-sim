"""Public consequences of an ignored Forbidden Intrigue card."""

from __future__ import annotations

from typing import Any, Mapping

from ..witness_types import PublicWitness


def compile_ignored_intrigue_forbids(
        view: Mapping[str, Any]) -> list[PublicWitness]:
    """One uncancelled forbid that lets intrigue through implies a Cultist.

    The Cultist chooses a location after movement. Boss remains a conservative
    candidate because its territory may extend its ability location.
    """
    characters = view.get("characters", {})
    initial = {
        str(cid): str(item.get("initial_location", item.get("location", "")))
        for cid, item in characters.items()
    }
    locations = dict(initial)
    alive = {str(cid): bool(item.get("present", True))
             for cid, item in characters.items()}
    ignored_targets: set[str] = set()
    result: list[PublicWitness] = []
    for event in view.get("events", ()):
        kind = event.get("kind")
        if kind == "loop_started":
            locations = dict(initial)
            alive = {str(cid): bool(item.get("present", True))
                     for cid, item in characters.items()}
            ignored_targets = set()
            continue
        if kind in {"character_moved", "character_replaced"}:
            target = event.get("character", event.get("target"))
            location = event.get("location")
            if isinstance(target, str) and isinstance(location, str):
                locations[target] = location
                alive[target] = True
            continue
        if kind == "character_died":
            target = event.get("target")
            if isinstance(target, str):
                alive[target] = False
            continue
        if kind == "revived":
            target = event.get("target")
            if isinstance(target, str):
                alive[target] = True
            continue
        if kind == "character_left":
            target = event.get("character")
            if isinstance(target, str):
                alive[target] = False
            continue
        if kind == "cards_revealed":
            cards = event.get("cards", ())
            forbids = [item for item in cards
                       if item.get("card") == "fi"]
            intrigue_targets = {
                str(item.get("target")) for item in cards
                if item.get("card") in {"i1", "i2"}}
            ignored_targets = ({str(forbids[0].get("target"))}
                               & intrigue_targets
                               if len(forbids) == 1 else set())
            continue
        if kind == "actions_resolved":
            ignored_targets = set()
            continue
        target = event.get("target")
        if (kind != "counter_changed" or target not in ignored_targets
                or event.get("counter") != "intrigue"
                or not isinstance(event.get("before"), int)
                or not isinstance(event.get("after"), int)
                or event["after"] <= event["before"]):
            continue
        protected_location = (locations.get(str(target))
                              if target in characters else str(target))
        candidates = tuple(sorted(
            cid for cid in characters if alive.get(str(cid), False)
            and (locations.get(str(cid)) == protected_location
                 or cid == "boss")))
        if candidates:
            result.append(PublicWitness(
                "role_pressure", "cultist", {"candidates": candidates},
                int(event.get("loop", view.get("loop", 1))),
                int(event.get("round", view.get("round", 1))),
                str(event.get("timing", "action_resolution")),
                "public_intrigue_forbid_ignored"))
    return result
