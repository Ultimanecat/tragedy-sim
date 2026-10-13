"""Exact conditional incident assignments within the culprit dimension.

Unary witness likelihoods are conditioned on printed repeat restrictions.
Suffix partition masses support direct legal sampling and joint marginals.
Only public candidate domains, schedules and witness scores are inputs.
"""

from collections import defaultdict
from functools import lru_cache
from math import isfinite


class JointCulpritPosterior:
    version = "legal-joint-culprits-v1"

    def __init__(self, schedule, domains, weights=None):
        self.schedule = tuple(schedule)
        if len({day for day, _ in self.schedule}) != len(self.schedule):
            raise ValueError("Incident days must be distinct")
        self.domains = {day: tuple(dict.fromkeys(domains[day])) for day, _ in self.schedule}
        characters = sorted({cid for options in self.domains.values() for cid in options})
        self._bits = {cid: 1 << index for index, cid in enumerate(characters)}
        self._rows = []
        for day, _ in self.schedule:
            values = [weights[day][cid] if weights is not None else 1
                      for cid in self.domains[day]]
            if any(not isfinite(value) or value <= 0 for value in values):
                raise ValueError("Culprit weights must be finite and positive")
            # Common per-day scaling cancels after conditioning; bound floats.
            scale = max(values, default=1) if weights is not None else 1
            self._rows.append(tuple((cid, value / scale if weights is not None else 1)
                                    for cid, value in zip(self.domains[day], values)))

        @lru_cache(maxsize=None)
        def mass(index, ordinary_used, serial_used):
            if index == len(self.schedule):
                return 1
            result = 0
            for cid, weight in self._rows[index]:
                masks = self._advance(index, cid, ordinary_used, serial_used)
                if masks is not None:
                    result += weight * mass(index + 1, *masks)
            return result

        self._mass = mass
        self.partition = mass(0, 0, 0)

    def _advance(self, index, cid, ordinary_used, serial_used):
        bit = self._bits[cid]
        serial = self.schedule[index][1] == "serial_murder"
        if ordinary_used & bit or (not serial and serial_used & bit):
            return None
        return (ordinary_used | (0 if serial else bit),
                serial_used | (bit if serial else 0))

    def sample(self, rng):
        """One direct conditional draw; no retry loop or forbidden repeats."""
        if not self.partition:
            return None
        ordinary_used = serial_used = 0
        result = {}
        for index, (day, _) in enumerate(self.schedule):
            choices, weights = [], []
            for cid, weight in self._rows[index]:
                masks = self._advance(index, cid, ordinary_used, serial_used)
                if masks is not None:
                    suffix = self._mass(index + 1, *masks)
                    if suffix:
                        choices.append((cid, masks))
                        weights.append(weight * suffix)
            cid, (ordinary_used, serial_used) = rng.choices(choices, weights=weights, k=1)[0]
            result[day] = cid
        return result

    def marginals(self):
        """Exact conditional probabilities, separately from hard support."""
        result = {day: dict.fromkeys(self.domains[day], 0.0) for day, _ in self.schedule}
        if not self.partition:
            return result
        forward = {(0, 0): 1.0}
        for index, (day, _) in enumerate(self.schedule):
            following = defaultdict(float)
            for (ordinary_used, serial_used), probability in forward.items():
                denominator = self._mass(index, ordinary_used, serial_used)
                for cid, weight in self._rows[index]:
                    masks = self._advance(index, cid, ordinary_used, serial_used)
                    if masks is None:
                        continue
                    suffix = self._mass(index + 1, *masks)
                    if not suffix:
                        continue
                    contribution = probability * weight * suffix / denominator
                    result[day][cid] += contribution
                    following[masks] += contribution
            forward = following
        return result

    def support(self):
        """Positive suffix support; no probability thresholds or samples."""
        result = {day: set() for day, _ in self.schedule}
        if not self.partition:
            return {day: () for day in result}
        forward = {(0, 0)}
        for index, (day, _) in enumerate(self.schedule):
            following = set()
            for ordinary_used, serial_used in forward:
                for cid, _ in self._rows[index]:
                    masks = self._advance(index, cid, ordinary_used, serial_used)
                    if masks is not None and self._mass(index + 1, *masks):
                        result[day].add(cid)
                        following.add(masks)
            forward = following
        return {day: tuple(cid for cid in self.domains[day] if cid in result[day])
                for day in result}

    def diagnostics(self):
        return {"version": self.version, "days": len(self.schedule),
                "feasible": bool(self.partition), "partition_states": self._mass.cache_info().currsize}


@lru_cache(maxsize=32)
def _posterior(schedule, domain_rows, weight_rows):
    return JointCulpritPosterior(schedule, dict(domain_rows),
                               {day: dict(row) for day, row in weight_rows} if weight_rows else None)


def joint_culprit_posterior(schedule, domains, weights=None):
    """Bounded shared cache for matrix projection and repeated root queries."""
    schedule = tuple(schedule)
    domain_rows = tuple((day, tuple(domains[day])) for day, _ in schedule)
    weight_rows = (tuple((day, tuple((cid, weights[day][cid]) for cid in domains[day]))
                         for day, _ in schedule) if weights is not None else ())
    return _posterior(schedule, domain_rows, weight_rows)
