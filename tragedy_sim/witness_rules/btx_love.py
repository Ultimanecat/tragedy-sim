"""Public BTX Romance evidence from the mandatory death reaction."""

from __future__ import annotations

from typing import Any, Mapping

from ..witness_types import PublicWitness


def compile_love_death_reactions(
        view: Mapping[str, Any]) -> list[PublicWitness]:
    """A +6 paranoia directly following death identifies the Romance pair.

    Several simultaneous deaths can share one reaction window.  In that case
    the recipient is known to be one partner, but the exact dead partner is
    not; only a single-death batch supports both role constraints.
    """
    if view.get("module") != "BTX":
        return []
    events = tuple(view.get("events", ()))
    result: list[PublicWitness] = []
    index = 0
    while index < len(events):
        first = events[index]
        if first.get("kind") != "character_died":
            index += 1
            continue
        loop, day = first.get("loop"), first.get("round")
        deaths: list[str] = []
        while (index < len(events) and events[index].get("kind") == "character_died"
               and events[index].get("loop") == loop
               and events[index].get("round") == day):
            target = events[index].get("target")
            if isinstance(target, str):
                deaths.append(target)
            index += 1
        recipients: list[str] = []
        while index < len(events):
            event = events[index]
            before, after = event.get("before"), event.get("after")
            if (event.get("kind") != "counter_changed"
                    or event.get("loop") != loop or event.get("round") != day
                    or event.get("counter") != "paranoia"
                    or not isinstance(before, int) or not isinstance(after, int)
                    or after - before != 6):
                break
            recipient = event.get("target")
            if isinstance(recipient, str) and recipient not in deaths:
                recipients.append(recipient)
            index += 1
        if not recipients or loop is None or day is None:
            continue
        timing = str(first.get("timing", "death"))
        result.append(PublicWitness(
            "plot_present", "love", True, int(loop), int(day), timing,
            "public_love_death_reaction"))
        for recipient in dict.fromkeys(recipients):
            result.append(PublicWitness(
                "role_in", recipient, ("loved", "lover"),
                int(loop), int(day), timing, "public_love_death_reaction"))
        if len(deaths) == 1:
            result.append(PublicWitness(
                "role_in", deaths[0], ("loved", "lover"),
                int(loop), int(day), timing, "public_love_death_reaction"))
    return result
