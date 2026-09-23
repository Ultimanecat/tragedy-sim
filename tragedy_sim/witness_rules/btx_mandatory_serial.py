"""BTX serial-killer routes from a completed public mandatory window."""

from __future__ import annotations

from typing import Any, Mapping

from ..catalog import CHARACTERS
from ..witness_types import PublicWitness


def compile_mandatory_serial_routes(
        view: Mapping[str, Any]) -> list[PublicWitness]:
    """Attribute protected or actual victims before optional day-end choices.

    The marker is required: historical replays without it cannot distinguish
    the mandatory batch from a Killer's later optional death.  Part-timer can
    die from its own compulsory ability, so its outcome is not attributed.
    """
    if view.get("module") != "BTX":
        return []
    characters = view.get("characters", {})
    if not isinstance(characters, Mapping):
        return []
    positions: dict[str, str | None] = {
        str(cid): (None if cid in {"servant", "henchman"}
                   else CHARACTERS[cid].start)
        for cid in characters if cid in CHARACTERS}
    alive = set(positions)
    reached: set[str] = set()
    active_loop: int | None = None
    window: tuple[int, int, dict[str, str | None], set[str], set[str]] | None = None
    outcomes: list[str] = []
    replacement = False
    result: list[PublicWitness] = []
    for event in view.get("events", ()):
        kind = event.get("kind")
        if kind == "loop_started":
            active_loop = event.get("loop")
            positions = {
                str(cid): (None if cid in {"servant", "henchman"}
                           else CHARACTERS[cid].start)
                for cid in characters if cid in CHARACTERS}
            alive = set(positions)
            reached.clear()
            window = None
            continue
        if active_loop is None or event.get("loop") != active_loop:
            continue
        if kind == "phase_changed" and event.get("timing") == "day_end":
            day = event.get("round")
            window = ((active_loop, day, dict(positions), set(alive),
                       set(reached)) if isinstance(day, int) else None)
            outcomes = []
            replacement = False
            continue
        if kind in {"character_moved", "character_replaced",
                    "character_arrived"}:
            cid = event.get("character", event.get("target"))
            location = event.get("location")
            if isinstance(cid, str) and isinstance(location, str):
                positions[cid] = location
                if kind != "character_moved":
                    alive.add(cid)
        elif kind == "character_died":
            target = event.get("target")
            if isinstance(target, str):
                alive.discard(target)
                if window is not None:
                    outcomes.append(target)
        elif kind in {"guard_spent", "death_prevented"}:
            target = event.get("target")
            if window is not None and isinstance(target, str):
                outcomes.append(target)
        elif kind == "death_replaced" and window is not None:
            replacement = True
        elif kind == "revived":
            target = event.get("target")
            if isinstance(target, str):
                alive.add(target)
        elif kind == "character_left":
            target = event.get("character")
            if isinstance(target, str):
                alive.discard(target)
        elif kind == "counter_changed" and event.get("counter") == "paranoia":
            target = event.get("target")
            steps = event.get("steps")
            values = (steps if isinstance(steps, (list, tuple))
                      else (event.get("before"), event.get("after")))
            if (isinstance(target, str) and target in alive
                    and any(isinstance(value, int) and value >= 3
                            for value in values)):
                reached.add(target)
        if kind != "mandatory_window_resolved" or window is None:
            continue
        loop, day, snapshot, living, virus_reached = window
        window = None
        if replacement or event.get("round") != day:
            continue
        # Subsequent batches can see characters killed (or converted by a
        # death reaction) in the first batch.  Only the first attempted death
        # is guaranteed to use the frozen opening snapshot.
        for target in outcomes[:1]:
            if target == "part_timer" or target not in living:
                continue
            board = snapshot.get(target)
            if board is None:
                continue
            occupants = {cid for cid in living if snapshot.get(cid) == board}
            candidates = tuple(sorted({
                "part_timer" if cid == "part_timer_question" else cid
                for cid in living if cid != target and (
                    cid == "boss" or cid in {"servant", "henchman"}
                    or cid in occupants and len(occupants) == 2)}))
            if not candidates:
                continue
            result.append(PublicWitness(
                "mandatory_serial_route", target, {
                    "serial": candidates,
                    "virus_ordinary": tuple(cid for cid in candidates
                                            if cid in virus_reached
                                            or (cid == "part_timer" and
                                                "part_timer_question" in virus_reached)),
                }, loop, day, "day_end", "public_btx_mandatory_serial_route"))
    return result
