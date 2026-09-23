"""Rule-scoped public witnesses used to reject impossible hidden worlds.

Witness compilation accepts only a player projection.  Matchers deliberately
return UNKNOWN when a public phenomenon has multiple legal explanations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .catalog import CHARACTERS
from .witness_components import components_for
from .witness_types import (PublicWitness, WitnessEvaluation,
                            WitnessStrength, WitnessVerdict)


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


class RulesetWitnessCompiler:
    """Compile witnesses from the components registered for a ruleset."""

    modules = frozenset({"FS", "BTX"})

    def __init__(self, *, include_joint: bool = True,
                 disabled_sources: Iterable[str] = (),
                 disabled_components: Iterable[str] = ()):
        self.include_joint = bool(include_joint)
        self.disabled_sources = frozenset(str(item) for item in disabled_sources)
        self.disabled_components = frozenset(
            str(item) for item in disabled_components)

    def compile(self, view: Mapping[str, Any]) -> tuple[PublicWitness, ...]:
        module = str(view.get("module", ""))
        components = components_for(module)
        if not components:
            return ()
        result: list[PublicWitness] = []
        for component in components:
            if component.component_id in self.disabled_components:
                continue
            result.extend(component.compile(view))
        if not self.include_joint:
            result = [item for item in result
                      if item.kind != "joint_plot_role_pressure"
                      and not (item.kind == "role_pressure"
                               and item.strength == WitnessStrength.SOFT)]
        if self.disabled_sources:
            result = [item for item in result
                      if item.source not in self.disabled_sources]
        return tuple(result)


class FsbtxWitnessCompiler(RulesetWitnessCompiler):
    """Backward-compatible name for the original FS/BTX public API."""


class FsbtxWitnessMatcher:
    """Match an FS/BTX hidden setup without consulting the real game."""

    @staticmethod
    def _incident(hypothesis: Any, day: int) -> tuple[int, str, str, str] | None:
        return next((item for item in hypothesis.incidents if item[0] == day), None)

    def verdict(self, hypothesis: Any, witness: PublicWitness) -> WitnessVerdict:
        roles = dict(hypothesis.roles)
        if witness.kind == "role_is":
            subject = ("part_timer" if witness.subject == "part_timer_question"
                       else witness.subject)
            initial = roles.get(subject)
            plots = {hypothesis.main_plot, *hypothesis.subplots}
            compatible = initial == witness.value or (
                witness.value == "serial" and initial == "ordinary"
                and "virus" in plots)
            return (WitnessVerdict.SATISFIED if compatible
                    else WitnessVerdict.CONTRADICTED)
        if witness.kind == "role_in":
            subject = ("part_timer" if witness.subject == "part_timer_question"
                       else witness.subject)
            return (WitnessVerdict.SATISFIED
                    if roles.get(subject) in set(witness.value)
                    else WitnessVerdict.CONTRADICTED)
        if witness.kind == "role_not_in":
            subject = ("part_timer" if witness.subject == "part_timer_question"
                       else witness.subject)
            return (WitnessVerdict.CONTRADICTED
                    if roles.get(subject) in set(witness.value)
                    else WitnessVerdict.SATISFIED)
        if witness.kind == "culprit_is":
            incident = self._incident(hypothesis, int(witness.subject))
            if incident is None:
                return WitnessVerdict.CONTRADICTED
            return (WitnessVerdict.SATISFIED if incident[3] == witness.value
                    else WitnessVerdict.CONTRADICTED)
        if witness.kind == "culprit_in":
            incident = self._incident(hypothesis, int(witness.subject))
            if incident is None:
                return WitnessVerdict.CONTRADICTED
            return (WitnessVerdict.SATISFIED
                    if incident[3] in set(witness.value)
                    else WitnessVerdict.CONTRADICTED)
        if witness.kind == "plot_present":
            plots = {hypothesis.main_plot, *hypothesis.subplots}
            return (WitnessVerdict.SATISFIED if witness.subject in plots
                    else WitnessVerdict.CONTRADICTED)
        if witness.kind == "plot_not_present":
            plots = {hypothesis.main_plot, *hypothesis.subplots}
            return (WitnessVerdict.CONTRADICTED if witness.subject in plots
                    else WitnessVerdict.SATISFIED)
        if witness.kind == "plot_pressure":
            return (WitnessVerdict.SATISFIED
                    if hypothesis.main_plot == witness.subject
                    else WitnessVerdict.UNKNOWN)
        if witness.kind == "joint_plot_role_pressure":
            candidates = witness.value.get("candidates", ())
            role = witness.value.get("role")
            return (WitnessVerdict.SATISFIED
                    if hypothesis.main_plot == witness.subject
                    and any(roles.get(cid) == role for cid in candidates)
                    else WitnessVerdict.UNKNOWN)
        if witness.kind == "role_pressure":
            candidates = witness.value.get("candidates", ())
            return (WitnessVerdict.SATISFIED
                    if any(roles.get("part_timer" if cid == "part_timer_question"
                                     else cid) == witness.subject
                           for cid in candidates)
                    else (WitnessVerdict.CONTRADICTED
                          if witness.strength == WitnessStrength.HARD
                          else WitnessVerdict.UNKNOWN))
        if witness.kind == "role_route_pressure":
            for role, candidates in witness.value.items():
                if any(roles.get("part_timer" if cid == "part_timer_question"
                                 else cid) == role for cid in candidates):
                    return WitnessVerdict.SATISFIED
            return (WitnessVerdict.CONTRADICTED
                    if witness.strength == WitnessStrength.HARD
                    else WitnessVerdict.UNKNOWN)
        if witness.kind == "mastermind_ability_route":
            value = witness.value
            plots = {hypothesis.main_plot, *hypothesis.subplots}
            if plots.intersection(value.get("plots", ())):
                return WitnessVerdict.SATISFIED
            for role, candidates in value.get("roles", {}).items():
                if any(roles.get("part_timer" if cid == "part_timer_question"
                                 else cid) == role for cid in candidates):
                    return WitnessVerdict.SATISFIED
            return WitnessVerdict.CONTRADICTED
        if witness.kind == "mandatory_serial_route":
            value = witness.value
            if any(roles.get("part_timer" if cid == "part_timer_question"
                             else cid) == "serial"
                   for cid in value.get("serial", ())):
                return WitnessVerdict.SATISFIED
            plots = {hypothesis.main_plot, *hypothesis.subplots}
            if ("virus" in plots and any(
                    roles.get("part_timer" if cid == "part_timer_question"
                              else cid) == "ordinary"
                    for cid in value.get("virus_ordinary", ()))):
                return WitnessVerdict.SATISFIED
            return WitnessVerdict.CONTRADICTED
        if witness.kind == "loop_end_plot_explanation":
            value = witness.value
            boards = value.get("location_intrigue", {})
            characters = value.get("character_intrigue", {})
            initial = value.get("initial_locations", {})

            def role_of(cid: str) -> str | None:
                return roles.get("part_timer" if cid == "part_timer_question"
                                 else cid)

            main = hypothesis.main_plot
            if witness.subject == "FS":
                explained = (
                    main == "protect" and boards.get("school", 0) >= 2
                    or main == "avenger" and any(
                        role_of(str(cid)) == "brain"
                        and boards.get(location, 0) >= 2
                        for cid, location in initial.items()))
            elif witness.subject == "BTX":
                explained = (
                    main == "sealed" and boards.get("shrine", 0) >= 2
                    or main == "sign" and any(
                        role_of(str(cid)) == "key" and intrigue >= 2
                        for cid, intrigue in characters.items())
                    or main == "change" and bool(
                        value.get("butterfly_happened"))
                    or main == "bomb" and any(
                        role_of(str(cid)) == "witch"
                        and boards.get(location, 0) >= 2
                        for cid, location in initial.items()))
            else:
                return WitnessVerdict.UNKNOWN
            return (WitnessVerdict.SATISFIED if explained
                    else WitnessVerdict.CONTRADICTED)
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
                    and not characters.get("part_timer", {}).get("alive", True)
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
            value = witness.value
            candidate = (str(value.get("character"))
                         if isinstance(value, Mapping) else str(value))
            virus_eligible = (bool(value.get("virus_eligible"))
                              if isinstance(value, Mapping) else False)
            plots = {hypothesis.main_plot, *hypothesis.subplots}
            return (WitnessVerdict.SATISFIED
                    if (roles.get(candidate) == "serial"
                        or (virus_eligible and roles.get(candidate) == "ordinary"
                            and "virus" in plots))
                    else WitnessVerdict.UNKNOWN)
        if witness.kind == "day_end_killer_candidate":
            return (WitnessVerdict.SATISFIED
                    if roles.get(witness.subject) == "key"
                    and roles.get(str(witness.value)) == "killer"
                    else WitnessVerdict.UNKNOWN)
        if witness.kind == "loss_after_death":
            return (WitnessVerdict.SATISFIED
                    if (roles.get(witness.subject) in {"key", "friend"}
                        or (roles.get(witness.subject) == "factor"
                            and witness.value.get("factor_key_possible", False)))
                    else WitnessVerdict.UNKNOWN)
        return WitnessVerdict.UNKNOWN

    def soft_score(self, hypothesis: Any,
                   witnesses: Sequence[PublicWitness]) -> float:
        weights = {"incident_not_happened": 0.75,
                   "plot_pressure": 3.0,
                   "joint_plot_role_pressure": 2.5,
                   "role_pressure": 1.5,
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
        caps = {"plot_pressure": 6.0,
                "day_end_death_companion": 8.0,
                "day_end_killer_candidate": 6.0,
                "loss_after_death": 4.0,
                "joint_plot_role_pressure": 6.0,
                "role_pressure": 4.0}
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
