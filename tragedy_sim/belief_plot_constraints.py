"""Conservative plot/count propagation from public role domains.

Each variant keeps a complete plot selection and exact initial-role counts.
Marginal unions are outer bounds; retained witness matchers still check worlds.
No finite particle collection is used to prove a hard state.
"""

from collections import Counter
from dataclasses import dataclass
from itertools import product
from typing import Mapping, Sequence

from .belief import ConstraintBeliefSampler, FactorizedBeliefState, PublicEvidence
from .catalog import CHARACTERS, MODULES, REFUSAL
from .witness_rules.role_routes import HARD_ROLE_ROUTES, role_route_realizations


@dataclass(frozen=True)
class PlotRoleVariant:
    main_plot: str
    subplots: tuple[str, ...]
    counts: dict[str, int]
    domains: dict[str, frozenset[str]]
    extra_roles: dict[str, str]
    regular_counts: dict[str, int]


def _genders(cid):
    traits = CHARACTERS[cid].traits
    return "boy" in traits or "man" in traits, "girl" in traits or "woman" in traits


def _propagate(domains, counts, clauses, *, friend_gender_split=False):
    """Cardinality saturation and a single surviving disjunct to fixed point."""
    changed = True
    while changed:
        before = {cid: frozenset(values) for cid, values in domains.items()}
        if any(not values for values in domains.values()):
            return False
        for role in set(counts) | {role for values in domains.values() for role in values}:
            holders = [cid for cid, values in domains.items() if role in values]
            fixed = [cid for cid in holders if domains[cid] == {role}]
            needed = counts.get(role, 0)
            if len(fixed) > needed or len(holders) < needed:
                return False
            if len(fixed) == needed:
                for cid in holders:
                    if cid not in fixed:
                        domains[cid].discard(role)
            elif len(holders) == needed:
                for cid in holders:
                    domains[cid].intersection_update({role})
        for clause in clauses:
            viable = [route for route in clause
                      if all(role in domains.get(cid, ()) for cid, role in route.items())]
            if not viable:
                return False
            if len(viable) == 1:
                for cid, role in viable[0].items():
                    domains[cid].intersection_update({role})
            # An existential on an exactly-one role excludes all holders
            # outside the disjunction, without selecting either disjunct.
            if viable and all(len(route) == 1 for route in viable):
                clause_roles = {next(iter(route.values())) for route in viable}
                if len(clause_roles) == 1:
                    role = next(iter(clause_roles))
                    if counts.get(role, 0) == 1:
                        candidates = {next(iter(route)) for route in viable}
                        for cid in domains:
                            if cid not in candidates:
                                domains[cid].discard(role)
        if friend_gender_split:
            fixed_friends = [cid for cid, values in domains.items() if values == {"friend"}]
            for cid in fixed_friends:
                male, female = _genders(cid)
                for other in domains:
                    if other == cid:
                        continue
                    other_male, other_female = _genders(other)
                    if male and other_male or female and other_female:
                        domains[other].discard("friend")
        changed = before != {cid: frozenset(values) for cid, values in domains.items()}
    return True


def plot_role_variants(evidence: PublicEvidence, domains: Mapping[str, set[str]],
                       witnesses: Sequence) -> tuple[PlotRoleVariant, ...]:
    """Return sound outer-support variants, including extra printed roles."""
    if evidence.module not in {"FS", "BTX"}:
        raise ValueError("Plot role propagation currently supports FS/BTX")
    spec = MODULES[evidence.module]
    hard = tuple(w for w in witnesses if w.strength == "hard")
    required = {w.subject for w in hard if w.kind == "plot_present"}
    excluded = {w.subject for w in hard if w.kind == "plot_not_present"}
    regular = tuple(cid for cid in evidence.characters if cid not in {"irregular", "copycat"})
    result = []
    for main, subplots in ConstraintBeliefSampler._plot_sets(evidence):
        plots = (main, *subplots)
        if not required.issubset(plots) or excluded.intersection(plots):
            continue
        slots = ConstraintBeliefSampler._role_slots(evidence.module, plots)
        irregular = (ConstraintBeliefSampler._irregular_roles(evidence.module, plots)
                     if "irregular" in domains else (None,))
        # Hideous permits 0–2 optional Curmudgeons, outside normal slots.
        for extra_amount, irregular_role in product(range(3) if "hideous" in plots else (0,), irregular):
            bag = slots.copy()
            if extra_amount:
                bag["curmudgeon"] += extra_amount
            if sum(bag.values()) > len(regular):
                continue
            bag["ordinary"] += len(regular) - sum(bag.values())
            copy_roles = ({*bag, *((irregular_role,) if irregular_role else ())}
                          if "copycat" in domains else {None})
            for copy_role in sorted(copy_roles, key=str):
                extras = {}
                if irregular_role:
                    extras["irregular"] = irregular_role
                if copy_role:
                    extras["copycat"] = copy_role
                candidate = {cid: ({extras[cid]} if cid in extras else
                                   {role for role, count in bag.items() if count}) & set(allowed)
                             for cid, allowed in domains.items()}
                # These constraints are printed character/script rules.
                for cid, allowed in candidate.items():
                    if "sign" in plots and "girl" not in CHARACTERS[cid].traits:
                        allowed.discard("key")
                    if cid == "little_sister":
                        allowed.difference_update(REFUSAL)
                    if cid == "ai":
                        allowed.discard("ordinary")
                if "virus" not in plots:
                    serial_reveals = {cid for cid, role in evidence.known_roles if role == "serial"}
                    serial_reveals.update("part_timer" if w.subject == "part_timer_question" else w.subject
                                          for w in hard if w.kind == "role_is" and w.value == "serial")
                    for cid in serial_reveals:
                        if cid in candidate:
                            candidate[cid].discard("ordinary")
                clauses = [role_route_realizations(w, plots) for w in hard if w.kind in HARD_ROLE_ROUTES]
                if copy_role:
                    clauses.append(tuple({cid: copy_role} for cid in candidate if cid != "copycat"))
                counts = bag.copy()
                counts.update(extras.values())
                if not _propagate(candidate, counts, clauses, friend_gender_split=spec.friend_gender_split):
                    continue
                used_male = used_female = False
                valid = True
                for cid, role in extras.items():
                    if spec.friend_gender_split and role == "friend":
                        male, female = _genders(cid)
                        if male and used_male or female and used_female:
                            valid = False
                            break
                        used_male |= male
                        used_female |= female
                if not valid or not FactorizedBeliefState._assignment_count(
                        regular, {cid: tuple(sorted(candidate[cid])) for cid in regular}, bag,
                        friend_gender_split=spec.friend_gender_split,
                        used_friend_genders=(used_male, used_female)):
                    continue
                result.append(PlotRoleVariant(main, subplots, dict(counts),
                    {cid: frozenset(allowed) for cid, allowed in candidate.items()}, extras, dict(bag)))
    return tuple(result)
