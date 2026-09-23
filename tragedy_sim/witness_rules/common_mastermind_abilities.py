"""Conservative, public source alternatives for mastermind-phase +1 effects."""

from __future__ import annotations

from typing import Any, Mapping

from ..cards import LOCATIONS
from ..catalog import CHARACTERS, REFUSAL
from ..witness_types import PublicWitness


def compile_mastermind_counter_sources(
        view: Mapping[str, Any]) -> list[PublicWitness]:
    """Keep all legal private ability sources, including Doctor and Factor.

    Sacred Tree's compulsory transfer has the same timing and counter event,
    but no public source marker.  Until a complete mandatory-window marker is
    available, a cast containing it is deliberately outside this component.
    """
    if view.get("module") not in {"FS", "BTX"}:
        return []
    characters = view.get("characters", {})
    if not isinstance(characters, Mapping) or "sacred_tree" in characters:
        return []
    positions = {str(cid): CHARACTERS[cid].start for cid in characters
                 if cid in CHARACTERS}
    # These cards can have a scenario-specific initial location.  Keeping
    # them as candidate sources at every board is conservative.
    flexible = {"servant", "henchman"} & positions.keys()
    current_loop: int | None = None
    result: list[PublicWitness] = []
    for event in view.get("events", ()):
        kind = event.get("kind")
        if kind == "loop_started":
            current_loop = event.get("loop")
            positions = {str(cid): CHARACTERS[cid].start for cid in characters
                         if cid in CHARACTERS}
            continue
        if current_loop is None or event.get("loop") != current_loop:
            continue
        if kind in {"character_moved", "character_replaced",
                    "character_arrived"}:
            cid = event.get("character", event.get("target"))
            location = event.get("location")
            if isinstance(cid, str) and location in LOCATIONS:
                positions[cid] = location
            continue
        if (kind != "counter_changed"
                or event.get("timing") != "mastermind_ability"
                or event.get("counter") not in {"intrigue", "paranoia"}
                or not isinstance(event.get("before"), int)
                or not isinstance(event.get("after"), int)
                or event["after"] - event["before"] != 1
                or not isinstance(event.get("round"), int)):
            continue
        target = event.get("target")
        if not isinstance(target, str):
            continue
        board = target if target in LOCATIONS else positions.get(target)
        if board not in LOCATIONS:
            continue
        near = tuple(sorted({"part_timer" if cid == "part_timer_question"
                             else cid for cid, location in positions.items()
                             if location == board or cid in flexible
                             or cid == "boss"}))
        routes: dict[str, tuple[str, ...]] = {}
        plots: tuple[str, ...] = ()
        if event["counter"] == "intrigue":
            routes["brain"] = near
            if target in LOCATIONS:
                plots = ("rumor",)
        elif target not in LOCATIONS:
            routes["conspiracy"] = near
            if view["module"] == "BTX":
                routes["factor"] = near
            if "doctor" in positions and target != "doctor" and (
                    positions["doctor"] == board or "doctor" in flexible):
                for role in REFUSAL:
                    routes[role] = tuple(sorted(set(routes.get(role, ()))
                                                | {"doctor"}))
        if not plots and not any(routes.values()):
            continue
        result.append(PublicWitness(
            "mastermind_ability_route", target,
            {"roles": routes, "plots": plots}, int(current_loop),
            event["round"], "mastermind_ability",
            ("public_mastermind_intrigue_source" if event["counter"] == "intrigue"
             else "public_mastermind_paranoia_source")))
    return result
