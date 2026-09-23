"""First Steps' immediate Key Person death observation."""

from __future__ import annotations

from typing import Any, Mapping

from ..witness_types import PublicWitness


def compile_key_deaths(view: Mapping[str, Any]) -> list[PublicWitness]:
    """A sole death immediately before an FS loss identifies the Key Person."""
    if view.get("module") != "FS":
        return []
    events = view.get("events", ())
    result: list[PublicWitness] = []
    for index in range(1, len(events)):
        loss = events[index]
        if loss.get("kind") != "loop_lost":
            continue
        cursor = index - 1
        while (cursor >= 0
               and events[cursor].get("kind") in {"incident_ended", "role_revealed"}
               and events[cursor].get("loop") == loss.get("loop")
               and events[cursor].get("round") == loss.get("round")):
            cursor -= 1
        if cursor < 0:
            continue
        death = events[cursor]
        if death.get("kind") != "character_died":
            continue
        if cursor >= 1 and events[cursor - 1].get("kind") == "character_died":
            continue
        if (loss.get("loop") != death.get("loop")
                or loss.get("round") != death.get("round")):
            continue
        victim = death.get("target")
        if not isinstance(victim, str):
            continue
        result.append(PublicWitness(
            "role_is", victim, "key", int(death["loop"]),
            int(death["round"]), str(death.get("timing", "unknown")),
            "immediate_fs_death_loss"))
    return result
