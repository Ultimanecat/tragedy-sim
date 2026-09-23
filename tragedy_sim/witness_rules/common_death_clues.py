"""Death and loop-loss clues reconstructed from the public journal."""

from __future__ import annotations

from typing import Any, Mapping

from ..witness_types import PublicWitness, WitnessStrength


def compile_death_clues(view: Mapping[str, Any]) -> list[PublicWitness]:
    """Keep ambiguous causes soft; FS's unique lone companion can be hard."""
    characters = view.get("characters", {})
    initial = {
        str(cid): str(character.get("initial_location", character.get("location", "")))
        for cid, character in characters.items()
    }
    locations = dict(initial)
    intrigue = {str(cid): 0 for cid in characters}
    paranoia = {str(cid): 0 for cid in characters}
    virus_eligible: set[str] = set()
    city_intrigue = 0
    alive = {str(cid) for cid, character in characters.items()
             if bool(character.get("present", True))}
    deaths_by_loop: dict[int, list[
        tuple[str, tuple[str, ...], int, bool]]] = {}
    result: list[PublicWitness] = []
    for event in view.get("events", ()):
        kind = event.get("kind")
        event_loop = int(event.get("loop", view.get("loop", 1)))
        event_day = int(event.get("round", view.get("round", 1)))
        if kind == "loop_started":
            locations = dict(initial)
            intrigue = {str(cid): 0 for cid in characters}
            paranoia = {str(cid): 0 for cid in characters}
            virus_eligible = set()
            city_intrigue = 0
            alive = {str(cid) for cid, character in characters.items()
                     if bool(character.get("present", True))}
            continue
        if kind == "counter_changed":
            target = event.get("target")
            counter = event.get("counter")
            after = event.get("after")
            if isinstance(target, str) and isinstance(after, int):
                if counter == "intrigue" and target in intrigue:
                    intrigue[target] = after
                elif counter == "intrigue" and target == "city":
                    city_intrigue = after
                elif counter == "paranoia" and target in paranoia:
                    paranoia[target] = after
                    if after >= 3:
                        virus_eligible.add(target)
            continue
        if kind == "character_moved":
            target = event.get("character", event.get("target"))
            destination = event.get("location")
            if isinstance(target, str) and isinstance(destination, str):
                locations[target] = destination
            continue
        if kind == "character_died":
            victim = event.get("target")
            if not isinstance(victim, str):
                continue
            companions = tuple(sorted(
                cid for cid in alive if cid != victim
                and locations.get(cid) == locations.get(victim)))
            deaths_by_loop.setdefault(event_loop, []).append(
                (victim, companions, event_day, city_intrigue >= 2))
            if event.get("timing") == "day_end":
                if len(companions) == 1:
                    if (view.get("module") == "FS"
                            and victim != "part_timer"
                            and intrigue.get(victim, 0) < 2):
                        result.append(PublicWitness(
                            "role_is", companions[0], "serial",
                            event_loop, event_day, "day_end",
                            "fs_lone_companion_death"))
                    else:
                        result.append(PublicWitness(
                            "day_end_death_companion", victim, {
                                "character": companions[0],
                                "virus_eligible": companions[0] in virus_eligible,
                            },
                            event_loop, event_day, "day_end",
                            "public_death_and_location", WitnessStrength.SOFT))
                if intrigue.get(victim, 0) >= 2:
                    for companion in companions:
                        result.append(PublicWitness(
                            "day_end_killer_candidate", victim, companion,
                            event_loop, event_day, "day_end",
                            "public_death_and_intrigue", WitnessStrength.SOFT))
            alive.discard(victim)
            continue
        if kind == "loop_lost":
            same_day = [(victim, companions, factor_key_possible)
                        for victim, companions, death_day, factor_key_possible
                        in deaths_by_loop.get(event_loop, ())
                        if death_day == event_day]
            for victim, companions, factor_key_possible in same_day:
                result.append(PublicWitness(
                    "loss_after_death", victim,
                    {"companions": companions,
                     "factor_key_possible": factor_key_possible},
                    event_loop, event_day,
                    str(event.get("timing", "loop_end")),
                    "public_death_before_loop_loss", WitnessStrength.SOFT))
    return result
