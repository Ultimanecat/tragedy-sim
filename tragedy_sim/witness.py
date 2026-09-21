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


@dataclass
class PublicEvidenceLedger:
    """Seat-private evidence dimension, independent from search accounting."""

    module: str = ""
    witnesses: tuple[PublicWitness, ...] = ()
    updates: int = 0

    def update(self, view: Mapping[str, Any],
               compiler: "FsbtxWitnessCompiler") -> tuple[PublicWitness, ...]:
        compiled = compiler.compile(view)
        module = str(view.get("module", ""))
        module_changed = self.module != module
        if module_changed:
            self.module = module
            self.witnesses = ()
            self.updates = 0
        if module_changed or compiled != self.witnesses:
            self.witnesses = compiled
            self.updates += 1
        return self.witnesses

    @property
    def hard_count(self) -> int:
        return sum(item.strength == WitnessStrength.HARD
                   for item in self.witnesses)

    @property
    def soft_count(self) -> int:
        return sum(item.strength == WitnessStrength.SOFT
                   for item in self.witnesses)


class FsbtxWitnessCompiler:
    """Compile the conservative, rules-certain FS/BTX witness subset."""

    modules = frozenset({"FS", "BTX"})

    @staticmethod
    def _hard_fs_key_deaths(view: Mapping[str, Any]) -> list[PublicWitness]:
        """An immediate FS loss after one death certifies the Key Person.

        Normal final-day failure follows ``day_ended``. BTX also has Factor,
        which can temporarily gain the Key Person ability, so it is excluded.
        """
        if view.get("module") != "FS":
            return []
        events = view.get("events", ())
        result = []
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
            if (cursor >= 1 and events[cursor - 1].get("kind") == "character_died"):
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

    @staticmethod
    def _soft_death_witnesses(view: Mapping[str, Any]) -> list[PublicWitness]:
        """Reconstruct death clues from the public journal.

        Ambiguous causes remain soft. FS lone-companion deaths with low
        intrigue have a unique day-end role explanation and can be hard.
        """
        characters = view.get("characters", {})
        initial = {
            str(cid): str(character.get("initial_location", character.get("location", "")))
            for cid, character in characters.items()
        }
        locations = dict(initial)
        intrigue = {str(cid): 0 for cid in characters}
        alive = {str(cid) for cid, character in characters.items()
                 if bool(character.get("present", True))}
        deaths_by_loop: dict[int, list[tuple[str, tuple[str, ...], int]]] = {}
        result: list[PublicWitness] = []
        for event in view.get("events", ()):
            kind = event.get("kind")
            event_loop = int(event.get("loop", view.get("loop", 1)))
            event_day = int(event.get("round", view.get("round", 1)))
            if kind == "loop_started":
                locations = dict(initial)
                intrigue = {str(cid): 0 for cid in characters}
                alive = {str(cid) for cid, character in characters.items()
                         if bool(character.get("present", True))}
                continue
            if kind == "counter_changed":
                target = event.get("target")
                if (event.get("counter") == "intrigue"
                        and isinstance(target, str)
                        and target in intrigue
                        and isinstance(event.get("after"), int)):
                    intrigue[target] = event["after"]
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
                    (victim, companions, event_day))
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
                                "day_end_death_companion", victim, companions[0],
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
                same_day = [(victim, companions) for victim, companions, death_day
                            in deaths_by_loop.get(event_loop, ())
                            if death_day == event_day]
                for victim, companions in same_day:
                    result.append(PublicWitness(
                        "loss_after_death", victim,
                        {"companions": companions}, event_loop, event_day,
                        str(event.get("timing", "loop_end")),
                        "public_death_before_loop_loss", WitnessStrength.SOFT))
        return result

    @staticmethod
    def _soft_plot_pressure(view: Mapping[str, Any]) -> list[PublicWitness]:
        """A loop-end loss with a pressured school supports, but cannot prove, Protect."""
        if view.get("module") != "FS":
            return []
        school = 0
        events = view.get("events", ())
        result = []
        for index, event in enumerate(events):
            if event.get("kind") == "loop_started":
                school = 0
            elif (event.get("kind") == "counter_changed"
                  and event.get("target") == "school"
                  and event.get("counter") == "intrigue"
                  and isinstance(event.get("after"), int)):
                school = event["after"]
            elif (event.get("kind") == "loop_lost" and school >= 2
                  and index > 0 and events[index - 1].get("kind") == "day_ended"
                  and events[index - 1].get("loop") == event.get("loop")):
                result.append(PublicWitness(
                    "plot_pressure", "protect", True,
                    int(event["loop"]), int(event["round"]), "loop_end",
                    "public_school_pressure_and_loss", WitnessStrength.SOFT))
        return result

    def compile(self, view: Mapping[str, Any]) -> tuple[PublicWitness, ...]:
        module = str(view.get("module", ""))
        if module not in self.modules:
            return ()
        loop = int(view.get("loop", 1))
        day = int(view.get("round", 1))
        timing = str(view.get("timing", view.get("phase", "unknown")))
        result: list[PublicWitness] = self._hard_fs_key_deaths(view)
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
                }, loop, incident_day, "incident", "public_incident_status",
                (WitnessStrength.HARD if happened else WitnessStrength.SOFT)))
        result.extend(self._soft_death_witnesses(view))
        result.extend(self._soft_plot_pressure(view))
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
        if witness.kind == "plot_pressure":
            return (WitnessVerdict.SATISFIED
                    if hypothesis.main_plot == witness.subject
                    else WitnessVerdict.UNKNOWN)
        if witness.kind == "incident_not_happened":
            # Absence has several explanations (dead/absent culprit and optional
            # prevention among them), so it is evidence but not a hard exclusion.
            incident = self._incident(hypothesis, int(witness.subject))
            characters = witness.value.get("characters")
            if incident is not None and characters:
                culprit = incident[3]
                observed = characters.get(culprit)
                definition = CHARACTERS.get(culprit)
                if (observed is not None and definition is not None
                        and observed.get("alive") and observed.get("present")):
                    score = observed["paranoia"]
                    if culprit == "ai":
                        score += (observed["goodwill"] + observed["intrigue"]
                                  + observed["guard"])
                    if score < definition.limit:
                        return WitnessVerdict.SATISFIED
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
        if witness.kind == "day_end_death_companion":
            return (WitnessVerdict.SATISFIED
                    if roles.get(str(witness.value)) == "serial"
                    else WitnessVerdict.UNKNOWN)
        if witness.kind == "day_end_killer_candidate":
            return (WitnessVerdict.SATISFIED
                    if roles.get(witness.subject) == "key"
                    and roles.get(str(witness.value)) == "killer"
                    else WitnessVerdict.UNKNOWN)
        if witness.kind == "loss_after_death":
            return (WitnessVerdict.SATISFIED
                    if roles.get(witness.subject) in {"key", "friend"}
                    else WitnessVerdict.UNKNOWN)
        return WitnessVerdict.UNKNOWN

    def soft_score(self, hypothesis: Any,
                   witnesses: Sequence[PublicWitness]) -> float:
        weights = {"incident_not_happened": 0.75,
                   "plot_pressure": 2.0,
                   "day_end_death_companion": 4.0,
                   "day_end_killer_candidate": 1.5,
                   "loss_after_death": 2.0}
        by_kind: dict[str, float] = {}
        for witness in witnesses:
            if (witness.strength != WitnessStrength.SOFT
                    or self.verdict(hypothesis, witness) != WitnessVerdict.SATISFIED):
                continue
            by_kind[witness.kind] = by_kind.get(witness.kind, 0.0) \
                + weights.get(witness.kind, 0.5)
        # Repetition should increase confidence.  Causal day-end co-location
        # can become much stronger than the generic fact that a death preceded
        # a failed loop, while each channel remains bounded independently.
        caps = {"day_end_death_companion": 8.0,
                "day_end_killer_candidate": 6.0,
                "loss_after_death": 4.0}
        return sum(min(caps.get(kind, 3.0), score)
                   for kind, score in by_kind.items())

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
