"""Bounded, certified residual draws from a complete small role posterior.

Replica counts have expectation N*p, including unequal role probabilities.
This reduces resampling variance, not the underlying posterior uncertainty.
The IID path remains the fallback when composition might reject a role.
"""

from dataclasses import replace
from itertools import product
from math import floor, fsum, isfinite, prod


def residual_indices(weights, count, *, rng):
    if type(count) is not int or count < 1:
        raise ValueError("count must be a positive integer")
    weights = tuple(weights)
    if not weights or any(not isfinite(w) or w < 0 for w in weights):
        raise ValueError("weights must be finite and non-negative")
    try:
        total = fsum(weights)
    except OverflowError as error:
        raise ValueError("weights must have finite positive mass") from error
    if not isfinite(total) or total <= 0:
        raise ValueError("weights must have finite positive mass")
    expected = [count * (w / total) for w in weights]
    copies = [floor(p) for p in expected]
    result = [i for i, n in enumerate(copies) for _ in range(n)]
    remaining = count - len(result)
    if remaining:
        result.extend(rng.choices(range(len(weights)),
                                  weights=[p - n for p, n in zip(expected, copies)],
                                  k=remaining))
    rng.shuffle(result)
    return tuple(result)


def certified_residual_roles(roles, weights, evidence, witnesses, domains, joint,
                             count, *, exact, rng, composition_limit=2048):
    from .engine import RuleError
    from .witness import FsbtxWitnessMatcher

    diagnostic = {"requested": "residual_small", "used": "iid",
                  "role_support": len(roles), "composition_checks": 0,
                  "fallback": None}
    def fallback(reason):
        diagnostic["fallback"] = reason
        return None, diagnostic
    if not roles:
        return fallback("no_role_support")
    if not exact:
        return fallback("role_support_not_complete")
    if len(roles) > count:
        return fallback("role_support_exceeds_budget")
    if joint is None:
        return fallback("joint_culprits_required")
    if not joint.partition:
        return fallback("no_joint_support")
    schedule = evidence.schedule
    if any({day for day, _, _, _ in role.incidents} != {day for day, _ in schedule}
           for role in roles):
        return fallback("incident_schedule_mismatch")
    bound = len(roles) * prod(len(domains[day]) for day, _ in schedule)
    if bound > composition_limit:
        return fallback("composition_limit")
    matcher = FsbtxWitnessMatcher()
    for assignment in product(*(domains[day] for day, _ in schedule)):
        by_day = dict(zip((day for day, _ in schedule), assignment))
        if joint.supports_assignment(by_day):
            for role in roles:
                incidents = tuple((day, kind, public_kind, by_day[day])
                                  for day, kind, public_kind, _ in role.incidents)
                candidate = replace(role, incidents=incidents)
                diagnostic["composition_checks"] += 1
                try:
                    candidate.materialize(evidence)
                except RuleError:
                    return fallback("role_dependent_composition")
                if not matcher.matches(candidate, witnesses):
                    return fallback("role_dependent_witness")
    diagnostic["used"] = "residual_small"
    indices = residual_indices(weights, count, rng=rng)
    diagnostic["role_replicas"] = [indices.count(i) for i in range(len(roles))]
    diagnostic["role_masses"] = [w / fsum(weights) for w in weights]
    diagnostic["role_keys"] = [(role.main_plot, role.subplots, role.roles) for role in roles]
    return tuple(roles[i] for i in indices), diagnostic
