"""BTX immediate losses following character deaths."""

from __future__ import annotations

from typing import Any, Mapping

from ..witness_types import PublicWitness


def compile_immediate_death_losses(
        view: Mapping[str, Any]) -> list[PublicWitness]:
    """An immediate loss needs a dead Key, or Factor with city intrigue."""
    if view.get("module") != "BTX":
        return []
    events = view.get("events", ())
    city_intrigue = 0
    result: list[PublicWitness] = []
    for index, event in enumerate(events):
        if event.get("kind") == "loop_started":
            city_intrigue = 0
            continue
        if (event.get("kind") == "counter_changed"
                and event.get("target") == "city"
                and event.get("counter") == "intrigue"
                and isinstance(event.get("after"), int)):
            city_intrigue = event["after"]
            continue
        if event.get("kind") != "loop_lost":
            continue
        victims: list[str] = []
        cursor = index - 1
        while cursor >= 0:
            previous = events[cursor]
            if (previous.get("loop") != event.get("loop")
                    or previous.get("round") != event.get("round")):
                break
            kind = previous.get("kind")
            if kind == "character_died":
                target = previous.get("target")
                if isinstance(target, str):
                    victims.append(target)
            elif kind not in {"incident_ended", "role_revealed"}:
                break
            cursor -= 1
        if not victims:
            continue
        routes: dict[str, tuple[str, ...]] = {
            "key": tuple(sorted(set(victims))),
        }
        if city_intrigue >= 2:
            routes["factor"] = tuple(sorted(set(victims)))
        result.append(PublicWitness(
            "role_route_pressure", "immediate_death_loss", routes,
            int(event.get("loop", view.get("loop", 1))),
            int(event.get("round", view.get("round", 1))),
            str(event.get("timing", "loop_end")),
            "public_btx_immediate_death_loss"))
    return result
