"""FS/BTX main-plot clues visible at loop end."""

from __future__ import annotations

from typing import Any, Mapping

from ..witness_types import PublicWitness, WitnessStrength


def compile_loop_end_clues(view: Mapping[str, Any]) -> list[PublicWitness]:
    """A normal loss needs a plot explanation; ambiguous clues stay soft."""
    module = view.get("module")
    if module not in {"FS", "BTX"}:
        return []
    school = 0
    shrine = 0
    butterfly_happened = False
    characters = view.get("characters", {})
    character_intrigue = {str(cid): 0 for cid in characters}
    character_goodwill = {str(cid): 0 for cid in characters}
    alive = {str(cid): bool(item.get("present", True))
             for cid, item in characters.items()}
    initial_locations = {
        str(cid): str(item.get("initial_location", item.get("location", "")))
        for cid, item in characters.items()
    }
    location_intrigue = {location: 0 for location in
                         {"hospital", "shrine", "city", "school"}}
    events = view.get("events", ())
    result: list[PublicWitness] = []
    for index, event in enumerate(events):
        if event.get("kind") == "loop_started":
            school = 0
            shrine = 0
            butterfly_happened = False
            character_intrigue = {str(cid): 0 for cid in characters}
            character_goodwill = {str(cid): 0 for cid in characters}
            alive = {str(cid): bool(item.get("present", True))
                     for cid, item in characters.items()}
            location_intrigue = {location: 0 for location in
                                 location_intrigue}
        elif (event.get("kind") == "counter_changed"
              and isinstance(event.get("after"), int)):
            target = str(event.get("target", ""))
            counter = event.get("counter")
            if counter == "intrigue":
                if target in character_intrigue:
                    character_intrigue[target] = event["after"]
                elif target in location_intrigue:
                    location_intrigue[target] = event["after"]
                if target == "school":
                    school = event["after"]
                elif target == "shrine":
                    shrine = event["after"]
            elif counter == "goodwill" and target in character_goodwill:
                character_goodwill[target] = event["after"]
        elif event.get("kind") == "character_died":
            target = event.get("target")
            if isinstance(target, str):
                alive[target] = False
        elif (event.get("kind") == "incident_status"
              and event.get("incident") == "butterfly"
              and event.get("happened")):
            butterfly_happened = True
        elif (event.get("kind") == "loop_lost" and index > 0
              and ((events[index - 1].get("kind") == "day_ended"
                    and events[index - 1].get("loop") == event.get("loop"))
                   or any(
                       previous.get("kind") == "protagonists_lost"
                       and previous.get("loop") == event.get("loop")
                       and previous.get("round") == event.get("round")
                       and previous.get("timing") == "day_end"
                       for previous in events[:index]))):
            normal_loop_end = (
                events[index - 1].get("kind") == "day_ended"
                and events[index - 1].get("loop") == event.get("loop"))
            if normal_loop_end:
                # No role_revealed event sits between day_ended and this
                # loss, so a dead Friend did not cause this resolution.
                # At least one main-plot predicate must be true.
                result.append(PublicWitness(
                    "loop_end_plot_explanation", module, {
                        "location_intrigue": dict(location_intrigue),
                        "character_intrigue": dict(character_intrigue),
                        "initial_locations": dict(initial_locations),
                        "butterfly_happened": butterfly_happened,
                    }, int(event["loop"]), int(event["round"]),
                    "loop_end", "public_normal_loop_end_loss"))
            if module == "FS" and school >= 2:
                result.append(PublicWitness(
                    "plot_pressure", "protect", True,
                    int(event["loop"]), int(event["round"]), "loop_end",
                    "public_school_pressure_and_loss", WitnessStrength.SOFT))
            if module == "BTX" and shrine >= 2:
                result.append(PublicWitness(
                    "plot_pressure", "sealed", True,
                    int(event["loop"]), int(event["round"]), "loop_end",
                    "public_shrine_pressure_and_loss", WitnessStrength.SOFT))
            if module == "BTX" and butterfly_happened:
                result.append(PublicWitness(
                    "plot_pressure", "change", True,
                    int(event["loop"]), int(event["round"]), "loop_end",
                    "public_butterfly_and_loss", WitnessStrength.SOFT))
            if module == "BTX":
                sign_candidates = tuple(sorted(
                    cid for cid, value in character_intrigue.items()
                    if value >= 2))
                if sign_candidates:
                    result.append(PublicWitness(
                        "joint_plot_role_pressure", "sign",
                        {"role": "key", "candidates": sign_candidates},
                        int(event["loop"]), int(event["round"]), "loop_end",
                        "public_character_intrigue_and_loss",
                        WitnessStrength.SOFT))
                bomb_candidates = tuple(sorted(
                    cid for cid, location in initial_locations.items()
                    if location_intrigue.get(location, 0) >= 2))
                if bomb_candidates:
                    # Simultaneous routes are possible, so both remain soft.
                    result.append(PublicWitness(
                        "plot_pressure", "bomb", True,
                        int(event["loop"]), int(event["round"]), "loop_end",
                        "public_initial_board_pressure_and_loss",
                        WitnessStrength.SOFT))
                    result.append(PublicWitness(
                        "joint_plot_role_pressure", "bomb",
                        {"role": "witch", "candidates": bomb_candidates},
                        int(event["loop"]), int(event["round"]), "loop_end",
                        "public_initial_board_intrigue_and_loss",
                        WitnessStrength.SOFT))
                if int(event.get("round", 0)) == int(view.get("days", 0)):
                    declared_loss = any(
                        previous.get("kind") == "protagonists_lost"
                        and previous.get("loop") == event.get("loop")
                        and previous.get("round") == event.get("round")
                        and previous.get("timing") == "day_end"
                        for previous in events[:index])
                    traveler_candidates = tuple(sorted(
                        cid for cid, goodwill in character_goodwill.items()
                        if alive.get(cid, False) and goodwill < 3))
                    if traveler_candidates:
                        result.append(PublicWitness(
                            "role_pressure", "time_traveler",
                            {"candidates": traveler_candidates},
                            int(event["loop"]), int(event["round"]),
                            "loop_end", "public_final_day_low_goodwill_loss",
                            (WitnessStrength.HARD if declared_loss
                             else WitnessStrength.SOFT)))
    return result
