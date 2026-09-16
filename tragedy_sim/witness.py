"""Rule-scoped public witnesses used to reject impossible hidden worlds.

Witness compilation accepts only a player projection.  Matchers deliberately
return UNKNOWN when a public phenomenon has multiple legal explanations.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Sequence

from .catalog import CHARACTERS


class WitnessStrength(StrEnum):
    HARD = "hard"
    SOFT = "soft"


class WitnessVerdict(StrEnum):
    SATISFIED = "satisfied"
    CONTRADICTED = "contradicted"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PublicWitness:
    kind: str
    subject: str
    value: Any
    loop: int
    day: int
    timing: str
    source: str
    strength: WitnessStrength = WitnessStrength.HARD


@dataclass(frozen=True)
class WitnessEvaluation:
    compatible: bool
    verdicts: tuple[tuple[PublicWitness, WitnessVerdict], ...]

    @property
    def contradicted(self) -> tuple[PublicWitness, ...]:
        return tuple(witness for witness, verdict in self.verdicts
                     if verdict == WitnessVerdict.CONTRADICTED)


class FsbtxWitnessCompiler:
    """Compile the conservative, rules-certain FS/BTX witness subset."""

    modules = frozenset({"FS", "BTX"})

    def compile(self, view: Mapping[str, Any]) -> tuple[PublicWitness, ...]:
        module = str(view.get("module", ""))
        if module not in self.modules:
            return ()
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
        for record in view.get("incidents", ()):
            incident_day = int(record["day"])
            happened = bool(record.get("happened", False))
            # The board embedded in this witness is only a hard timing snapshot
            # while the incident is being observed on its own day.  Old records
            # remain useful facts but cannot safely use today's counters.
            observed_characters = None
            if incident_day == day:
                observed_characters = {
                    cid: {
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
                    "kind": str(record["kind"]),
                    "characters": observed_characters,
                }, loop, incident_day, "incident", "public_incident_status"))
        return tuple(result)


class FsbtxWitnessMatcher:
    """Match an FS/BTX hidden setup without consulting the real game."""

    @staticmethod
    def _incident(hypothesis: Any, day: int) -> tuple[int, str, str, str] | None:
        return next((item for item in hypothesis.incidents if item[0] == day), None)

    def verdict(self, hypothesis: Any, witness: PublicWitness) -> WitnessVerdict:
        roles = dict(hypothesis.roles)
        if witness.kind == "role_is":
            return (WitnessVerdict.SATISFIED
                    if roles.get(witness.subject) == witness.value
                    else WitnessVerdict.CONTRADICTED)
        if witness.kind == "culprit_is":
            incident = self._incident(hypothesis, int(witness.subject))
            if incident is None:
                return WitnessVerdict.CONTRADICTED
            return (WitnessVerdict.SATISFIED if incident[3] == witness.value
                    else WitnessVerdict.CONTRADICTED)
        if witness.kind == "plot_present":
            plots = {hypothesis.main_plot, *hypothesis.subplots}
            return (WitnessVerdict.SATISFIED if witness.subject in plots
                    else WitnessVerdict.CONTRADICTED)
        if witness.kind == "incident_not_happened":
            # Absence has several explanations (dead/absent culprit and optional
            # prevention among them), so it is evidence but not a hard exclusion.
            return WitnessVerdict.UNKNOWN
        if witness.kind == "incident_happened":
            incident = self._incident(hypothesis, int(witness.subject))
            if incident is None or incident[2] != witness.value["kind"]:
                return WitnessVerdict.CONTRADICTED
            characters = witness.value.get("characters")
            if not characters:
                return WitnessVerdict.UNKNOWN
            culprit = incident[3]
            if (culprit == "part_timer"
                    and characters.get("part_timer_question", {}).get("present")):
                culprit = "part_timer_question"
            observed = characters.get(culprit)
            definition = CHARACTERS.get(culprit)
            if observed is None or definition is None:
                return WitnessVerdict.CONTRADICTED
            score = observed["paranoia"]
            if culprit == "ai":
                score = (observed["paranoia"] + observed["goodwill"]
                         + observed["intrigue"] + observed["guard"])
            return (WitnessVerdict.SATISFIED if score >= definition.limit
                    else WitnessVerdict.CONTRADICTED)
        return WitnessVerdict.UNKNOWN

    def evaluate(self, hypothesis: Any,
                 witnesses: Sequence[PublicWitness]) -> WitnessEvaluation:
        verdicts = tuple((witness, self.verdict(hypothesis, witness))
                         for witness in witnesses)
        compatible = not any(
            witness.strength == WitnessStrength.HARD
            and verdict == WitnessVerdict.CONTRADICTED
            for witness, verdict in verdicts)
        return WitnessEvaluation(compatible, verdicts)

    def matches(self, hypothesis: Any,
                witnesses: Sequence[PublicWitness]) -> bool:
        return self.evaluate(hypothesis, witnesses).compatible
