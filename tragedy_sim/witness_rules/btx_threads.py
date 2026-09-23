"""Positive public evidence of BTX's Threads of Fate subplot."""

from __future__ import annotations

from typing import Any, Mapping

from ..witness_types import PublicWitness


def compile_threads_at_loop_start(
        view: Mapping[str, Any]) -> list[PublicWitness]:
    """A prior-goodwill character gaining two paranoia before setup proves Threads.

    The previous loop must be present from its start through its loss. We only
    inspect the first counter change after the next loop_started: Threads is
    resolved before the Friend bonus and character-specific loop placements.
    """
    if view.get("module") != "BTX":
        return []
    active_loop: int | None = None
    goodwill: dict[str, int] = {}
    completed = False
    expected: set[str] = set()
    result: list[PublicWitness] = []
    for event in view.get("events", ()):
        kind = event.get("kind")
        event_loop = event.get("loop")
        if kind == "loop_started":
            next_loop = int(event_loop)
            expected = ({cid for cid, amount in goodwill.items() if amount > 0}
                        if active_loop is not None and completed
                        and next_loop == active_loop + 1 else set())
            active_loop = next_loop
            goodwill = {}
            completed = False
            continue
        if active_loop is None or event_loop != active_loop:
            continue
        if expected:
            target = event.get("target")
            before = event.get("before")
            after = event.get("after")
            if (kind == "counter_changed" and target in expected
                    and event.get("counter") == "paranoia"
                    and isinstance(before, int) and isinstance(after, int)
                    and after - before == 2):
                result.append(PublicWitness(
                    "plot_present", "threads", True, active_loop,
                    int(event.get("round", view.get("round", 1))),
                    str(event.get("timing", "loop_start")),
                    "public_threads_loop_start_paranoia"))
                expected.remove(target)
            else:
                expected.clear()
        if kind == "counter_changed" and event.get("counter") == "goodwill":
            target = event.get("target")
            after = event.get("after")
            if isinstance(target, str) and isinstance(after, int):
                goodwill[target] = after
        elif kind == "loop_lost":
            completed = True
    return result
