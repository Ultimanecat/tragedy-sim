"""Public facts and status records shared by FS and BTX."""

from __future__ import annotations

from typing import Any, Mapping

from ..catalog import REFUSAL
from ..witness_types import PublicWitness, WitnessStrength


def compile_accepted_goodwill(view: Mapping[str, Any]) -> list[PublicWitness]:
    """Accepting a refusable ability rules out mandatory refusers.

    Old journals lack the unrefusable flag, so they cannot support this hard
    deduction.
    """
    result: list[PublicWitness] = []
    mandatory = tuple(sorted(
        role for role in ("cultist", "witch")
        if REFUSAL.get(role) == "mandatory"))
    for event in view.get("events", ()):
        if (event.get("kind") != "goodwill_accepted"
                or event.get("unrefusable") is not False):
            continue
        source = event.get("source")
        if not isinstance(source, str):
            continue
        result.append(PublicWitness(
            "role_not_in", source, mandatory,
            int(event.get("loop", view.get("loop", 1))),
            int(event.get("round", view.get("round", 1))),
            str(event.get("timing", "protagonist_ability")),
            "public_refusable_goodwill_accepted"))
    return result


def compile_public_reveals(view: Mapping[str, Any]) -> list[PublicWitness]:
    loop = int(view.get("loop", 1))
    day = int(view.get("round", 1))
    timing = str(view.get("timing", view.get("phase", "unknown")))
    result: list[PublicWitness] = []
    for cid, fact in sorted(view.get("known_roles", {}).items()):
        role = fact.get("role") if isinstance(fact, Mapping) else None
        if isinstance(role, str):
            result.append(PublicWitness(
                "role_is", str(cid), role, loop, day, timing,
                "public_role_reveal"))
    for incident_day, cid in sorted(
            ((int(key), value)
             for key, value in view.get("known_culprits", {}).items())):
        result.append(PublicWitness(
            "culprit_is", str(incident_day), str(cid), loop, day, timing,
            "public_culprit_reveal"))
    for plot in sorted(str(item) for item in view.get("known_plots", ())):
        result.append(PublicWitness(
            "plot_present", plot, True, loop, day, timing,
            "public_plot_reveal"))
    return result


def compile_goodwill_refusals(view: Mapping[str, Any]) -> list[PublicWitness]:
    loop = int(view.get("loop", 1))
    day = int(view.get("round", 1))
    result: list[PublicWitness] = []
    for event in view.get("events", ()):
        if event.get("kind") != "goodwill_refused":
            continue
        source = event.get("source")
        if not isinstance(source, str):
            continue
        result.append(PublicWitness(
            "role_in", source, tuple(sorted(REFUSAL)),
            int(event.get("loop", loop)), int(event.get("round", day)),
            str(event.get("timing", "protagonist_ability")),
            "public_goodwill_refusal"))
    return result


def compile_incident_status(view: Mapping[str, Any]) -> list[PublicWitness]:
    loop = int(view.get("loop", 1))
    day = int(view.get("round", 1))
    result: list[PublicWitness] = []
    incident_events = [
        event for event in view.get("events", ())
        if event.get("kind") == "incident_status"
    ]
    # Old saves lack immutable snapshots. Their current-day board is the only
    # safe fallback for an incident's characters and counters.
    if incident_events:
        records = incident_events
    else:
        records = [
            {**record, "round": record.get("day", day), "loop": loop,
             "incident": record.get("kind")}
            for record in view.get("incidents", ())
        ]
    for record in records:
        incident_day = int(record.get("round", record.get("day", day)))
        incident_loop = int(record.get("loop", loop))
        happened = bool(record.get("happened", False))
        observed_characters = record.get("characters")
        if observed_characters is None and incident_day == day:
            observed_characters = {
                cid: {
                    "location": character.get("location"),
                    "paranoia": int(character.get("paranoia", 0)),
                    "goodwill": int(character.get("goodwill", 0)),
                    "intrigue": int(character.get("intrigue", 0)),
                    "guard": int(character.get("guard", 0)),
                    "present": bool(character.get("present", False)),
                    "alive": bool(character.get("alive", False)),
                }
                for cid, character in view.get("characters", {}).items()
            }
        result.append(PublicWitness(
            "incident_happened" if happened else "incident_not_happened",
            str(incident_day), {
                "kind": str(record.get("incident", record.get("kind"))),
                "characters": observed_characters,
            }, incident_loop, incident_day, "incident",
            "public_incident_status",
            (WitnessStrength.HARD if happened else WitnessStrength.SOFT)))
    return result
