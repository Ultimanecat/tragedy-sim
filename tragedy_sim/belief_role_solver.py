"""FS/BTX exact role support and compressed MAP over shared matrix variants.

Extra identities do not consume printed plot slots. Legal incident placeholders
only permit role validation; they never contribute incident posterior evidence.
"""

from collections import Counter
from itertools import permutations
import json

from .belief import ExactRoleMapResult, HiddenWorldHypothesis
from .belief_matrix import BeliefContradiction, evidence_role_domains
from .belief_matrix_sampler import role_incident_placeholders
from .belief_plot_constraints import _genders, plot_role_variants
from .belief_posterior import RolePosteriorTarget, variant_size
from .catalog import MODULES
from .engine import RuleError
from .witness import FsbtxWitnessMatcher
from .witness_rules.role_routes import HARD_ROLE_ROUTES


def _variants(evidence, witnesses):
    try:
        _, domains, _ = evidence_role_domains(evidence, witnesses)
    except BeliefContradiction:
        return ()
    return plot_role_variants(evidence, domains, witnesses)


def _incident_rows(evidence):
    placeholders = role_incident_placeholders(evidence)
    return (tuple((day, kind, kind, cid) for day, kind, cid in placeholders)
            if placeholders is not None else None)


def enumerate_role_worlds(evidence, witnesses=()):
    """Complete small role space, independent of any sampling RNG."""
    incidents = _incident_rows(evidence)
    if incidents is None:
        return
    matcher = FsbtxWitnessMatcher()
    for variant in _variants(evidence, witnesses):
        regular = tuple(sorted(cid for cid in variant.domains if cid not in variant.extra_roles))
        bag = tuple(Counter(variant.regular_counts).elements())
        for assignment in sorted(set(permutations(bag))):
            cast = {**variant.extra_roles, **dict(zip(regular, assignment))}
            if any(cast[cid] not in variant.domains[cid] for cid in cast):
                continue
            world = HiddenWorldHypothesis("belief-exact-roles", variant.main_plot,
                                          variant.subplots, tuple(sorted(cast.items())), incidents)
            try:
                world.materialize(evidence)
            except RuleError:
                continue
            if matcher.matches(world, witnesses):
                yield world


def solve_role_map(evidence, witnesses, *, top, solver):
    """Find MAP representatives without enumerating irrelevant permutations.

    All scores are monotone positive soft factors. Realize every subset of
    predicates and lexicographically complete irrelevant identities. The
    compatible_count remains a propagated-support upper bound when residual
    hard relations have not been expressed in the matrix domains.
    """
    incidents = _incident_rows(evidence)
    if incidents is None:
        return ExactRoleMapResult((), 0, 0)
    target = RolePosteriorTarget(evidence)
    matcher = FsbtxWitnessMatcher()
    unique = {}
    for witness in witnesses:
        if witness.strength == "soft" or witness.kind in HARD_ROLE_ROUTES:
            signature = json.dumps([witness.kind, witness.subject, witness.value],
                                   sort_keys=True, ensure_ascii=False, default=str)
            unique.setdefault(signature, witness)
    ranked, plot_sets, groups_by_plot = [], set(), {}
    compatible_count = 0
    for variant in _variants(evidence, witnesses):
        size = variant_size(variant, evidence.module)
        if not size:
            continue
        main, subplots = variant.main_plot, variant.subplots
        plot_sets.add((main, subplots))
        compatible_count += size
        plot_key = (main, subplots)
        if plot_key not in groups_by_plot:
            groups_by_plot[plot_key] = tuple(tuple(solver._soft_realizations(w, main, subplots))
                                            for w in unique.values())
        groups = groups_by_plot[plot_key]
        regular = tuple(cid for cid in variant.domains if cid not in variant.extra_roles)
        counts = Counter(variant.regular_counts)
        domains = {cid: tuple(sorted(variant.domains[cid])) for cid in regular}
        split = MODULES[evidence.module].friend_gender_split
        male = female = False
        for cid, role in variant.extra_roles.items():
            if split and role == "friend":
                is_male, is_female = _genders(cid)
                male |= is_male
                female |= is_female
        seen_partial, seen_roles = set(), set()

        def propose(index, fixed):
            signature = (index, tuple(sorted(fixed.items())))
            if signature in seen_partial:
                return
            seen_partial.add(signature)
            if index < len(groups):
                for addition in groups[index]:
                    merged = dict(fixed)
                    valid = True
                    for cid, role in addition.items():
                        cid = "part_timer" if cid == "part_timer_question" else cid
                        if (role not in variant.domains.get(cid, ())
                                or cid in merged and merged[cid] != role):
                            valid = False
                            break
                        merged[cid] = role
                    used = Counter(role for cid, role in merged.items() if cid in regular)
                    if valid and all(amount <= counts[role] for role, amount in used.items()):
                        propose(index + 1, merged)
                return
            cast = solver._complete_assignment(
                regular, domains, counts, fixed, friend_gender_split=split,
                used_friend_genders=(male, female))
            if cast is None:
                return
            signature = tuple(sorted(cast.items()))
            if signature in seen_roles:
                return
            seen_roles.add(signature)
            world = HiddenWorldHypothesis("belief-exact-map", main, subplots, signature, incidents)
            if not matcher.matches(world, witnesses):
                return
            try:
                world.materialize(evidence)
            except RuleError:
                return
            ranked.append((world, target.weight(world, witnesses)))

        propose(0, dict(variant.extra_roles))
    ordered = sorted(ranked, key=lambda pair: (
        pair[1], pair[0].roles, pair[0].main_plot, pair[0].subplots), reverse=True)
    return ExactRoleMapResult(tuple(ordered[:max(1, top)]), compatible_count, len(plot_sets))
