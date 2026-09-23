"""Public deductions from BTX Delusion Expansion Virus role reveals."""

from __future__ import annotations

from typing import Any, Mapping

from ..witness_types import PublicWitness


def compile_virus_reveal_thresholds(
        view: Mapping[str, Any]) -> list[PublicWitness]:
    """Compare a current-role reveal with this loop's paranoia history.

    Virus converts an initial Ordinary at three paranoia. A simultaneous
    removal can leave the final counter below three; the event's intermediate
    steps still prove that the threshold was reached.
    """
    if view.get("module") != "BTX":
        return []
    result: list[PublicWitness] = []
    active_loop: int | None = None
    reached: set[str] = set()
    dead: set[str] = set()
    for event in view.get("events", ()):
        kind = event.get("kind")
        if kind == "loop_started":
            active_loop = int(event.get("loop", -1))
            reached.clear()
            dead.clear()
            continue
        if active_loop is None or event.get("loop") != active_loop:
            continue
        if kind == "character_died":
            target = event.get("target")
            if isinstance(target, str):
                dead.add(target)
            continue
        if kind == "counter_changed" and event.get("counter") == "paranoia":
            target = event.get("target")
            steps = event.get("steps")
            values = (steps if isinstance(steps, (tuple, list))
                      else (event.get("before"), event.get("after")))
            if (isinstance(target, str) and target not in dead
                    and any(isinstance(value, int) and value >= 3
                            for value in values)):
                reached.add(target)
            continue
        if kind != "role_revealed":
            continue
        target = event.get("character")
        if not isinstance(target, str):
            continue
        subject = ("part_timer" if target == "part_timer_question"
                   else target)
        role = event.get("role")
        if role == "serial" and target not in reached:
            result.append(PublicWitness(
                "role_not_in", subject, ("ordinary",), active_loop,
                int(event.get("round", view.get("round", 1))),
                str(event.get("timing", "unknown")),
                "public_virus_serial_without_threshold"))
        elif role == "ordinary" and target in reached:
            result.append(PublicWitness(
                "plot_not_present", "virus", True, active_loop,
                int(event.get("round", view.get("round", 1))),
                str(event.get("timing", "unknown")),
                "public_ordinary_after_virus_threshold"))
    return result
