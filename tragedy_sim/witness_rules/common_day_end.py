"""Day-end hero death constraints shared by FS and BTX."""

from __future__ import annotations

from typing import Any, Mapping

from ..witness_types import PublicWitness


def compile_hero_deaths(view: Mapping[str, Any]) -> list[PublicWitness]:
    """A day-end hero death needs a Killer or Lover with public gates."""
    characters = view.get("characters", {})
    intrigue = {str(cid): 0 for cid in characters}
    paranoia = {str(cid): 0 for cid in characters}
    alive = {str(cid): bool(item.get("present", True))
             for cid, item in characters.items()}
    result: list[PublicWitness] = []
    for event in view.get("events", ()):
        kind = event.get("kind")
        if kind == "loop_started":
            intrigue = {str(cid): 0 for cid in characters}
            paranoia = {str(cid): 0 for cid in characters}
            alive = {str(cid): bool(item.get("present", True))
                     for cid, item in characters.items()}
            continue
        if kind == "counter_changed":
            target = event.get("target")
            after = event.get("after")
            if isinstance(target, str) and isinstance(after, int):
                if event.get("counter") == "intrigue" and target in intrigue:
                    intrigue[target] = after
                elif event.get("counter") == "paranoia" and target in paranoia:
                    paranoia[target] = after
            continue
        if kind == "character_died":
            target = event.get("target")
            if isinstance(target, str):
                alive[target] = False
            continue
        if kind in {"revived", "character_replaced"}:
            target = event.get("target", event.get("character"))
            if isinstance(target, str):
                alive[target] = True
            continue
        if kind == "character_left":
            target = event.get("character")
            if isinstance(target, str):
                alive[target] = False
            continue
        if kind != "heroes_died" or event.get("timing") != "day_end":
            continue
        routes = {
            "killer": tuple(sorted(
                cid for cid in characters
                if alive.get(str(cid), False) and intrigue[str(cid)] >= 4)),
            "lover": tuple(sorted(
                cid for cid in characters if alive.get(str(cid), False)
                and paranoia[str(cid)] >= 3 and intrigue[str(cid)] >= 1)),
        }
        routes = {role: candidates for role, candidates in routes.items()
                  if candidates}
        if routes:
            result.append(PublicWitness(
                "role_route_pressure", "day_end_hero_death", routes,
                int(event.get("loop", view.get("loop", 1))),
                int(event.get("round", view.get("round", 1))),
                "day_end", "public_day_end_hero_death"))
    return result
