"""Shared public incident domains for sampling and matrix projection.

Thresholds are evaluated against the witness's incident-time snapshot. Neither
current board counters nor a hidden script are needed for these deductions.
"""

from dataclasses import replace
from typing import Mapping, Sequence

from .witness_types import PublicWitness, WitnessStrength


CULPRIT_WITNESS_KINDS = frozenset({
    "culprit_is", "culprit_in", "incident_happened", "incident_not_happened"})


def culprit_domains(characters: Sequence[str], schedule: Sequence[tuple[int, str]],
                    known: Mapping[int, str], witnesses: Sequence[PublicWitness]
                    ) -> dict[int, tuple[str, ...]]:
    # Local imports keep the belief representation independent of the sampler.
    from .belief import HiddenWorldHypothesis
    from .witness import FsbtxWitnessMatcher, WitnessVerdict

    matcher = FsbtxWitnessMatcher()
    def initial(cid):
        return "part_timer" if cid == "part_timer_question" else cid

    known = {day: initial(cid) for day, cid in known.items()}
    normalized = tuple(
        replace(w, value=initial(w.value)) if w.kind == "culprit_is" else
        replace(w, value=tuple(initial(cid) for cid in w.value)) if w.kind == "culprit_in" else w
        for w in witnesses)
    result = {}
    for day, kind in schedule:
        facts = tuple(w for w in normalized if w.kind in CULPRIT_WITNESS_KINDS
                      and int(w.subject) == day and w.strength == WitnessStrength.HARD)
        candidates = []
        for cid in characters:
            if day in known and known[day] != cid:
                continue
            candidate = HiddenWorldHypothesis(
                "belief-culprit", "", (), (), ((day, kind, kind, cid),))
            if all(matcher.verdict(candidate, fact) != WitnessVerdict.CONTRADICTED
                   for fact in facts):
                candidates.append(cid)
        result[day] = tuple(candidates)
    return result
