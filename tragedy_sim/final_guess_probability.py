"""Exact cast-marginal probabilities under the public FS/BTX role model.

Partition casts by total counts and witness-relevant identities. Within each
group all latent plots have the same per-cast weight, so irrelevant completions
can be counted without enumerating them. No Game, true script or RNG is input.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from math import fsum
from typing import Mapping

from .belief import FactorizedBeliefState, HiddenWorldHypothesis, PublicEvidence
from .belief_culprit_constraints import culprit_domains
from .belief_culprit_posterior import joint_culprit_posterior
from .belief_matrix_sampler import role_incident_placeholders
from .belief_posterior import RolePosteriorTarget
from .belief_role_solver import _variants
from .catalog import MODULES
from .engine import RuleError
from .witness_rules.common_loop_end import loop_end_realizations


_PLOT_FACTS = {"plot_present", "plot_not_present", "plot_pressure"}
_INCIDENT_FACTS = {"culprit_is", "culprit_in", "incident_happened", "incident_not_happened"}
_ROLE_DEPENDENCIES = {
    "role_is", "role_in", "role_not_in", "role_pressure", "role_route_pressure",
    "joint_plot_role_pressure", "day_end_death_companion", "day_end_killer_candidate",
    "loss_after_death", "mastermind_ability_route", "mandatory_serial_route",
}


def _character_references(value, characters):
    if isinstance(value, str):
        cid = "part_timer" if value == "part_timer_question" else value
        return {cid} if cid in characters else set()
    if isinstance(value, Mapping):
        return set().union(*(_character_references(item, characters)
                            for pair in value.items() for item in pair))
    if isinstance(value, (list, tuple, set, frozenset)):
        return set().union(*(_character_references(item, characters) for item in value))
    return set()


def _dependencies(witnesses, variants, characters):
    result = set()
    for witness in witnesses:
        if witness.kind in _PLOT_FACTS:
            continue
        if witness.strength == "hard" and witness.kind in {"role_is", "role_in", "role_not_in"}:
            # These unary predicates are fully enforced in each plot's
            # domains (including Virus's current/initial interpretation).
            # Differences between plot domains are handled separately below.
            continue
        if witness.kind == "loop_end_plot_explanation":
            for main in {variant.main_plot for variant in variants}:
                for route in loop_end_realizations(witness.subject, main, witness.value):
                    result.update(route)
        elif witness.kind in _ROLE_DEPENDENCIES:
            result.update(_character_references((witness.subject, witness.value), characters))
        else:
            # Future role predicates require an explicit dependency contract.
            # Until then full identity branching is sound, though expensive.
            result.update(characters)
    return result & set(characters)


def _gender_ok(cast, split):
    if not split:
        return True
    from .belief_plot_constraints import _genders
    male = female = False
    for cid, role in cast.items():
        if role == "friend":
            m, f = _genders(cid)
            if m and male or f and female:
                return False
            male, female = male or m, female or f
    return True


@dataclass(frozen=True)
class _CastGroup:
    counts: tuple[tuple[str, int], ...]
    domains: tuple[tuple[str, tuple[str, ...]], ...]
    fixed: tuple[tuple[str, str], ...]
    representative: tuple[tuple[str, str], ...]
    completions: int
    per_cast_mass: float

    def contains(self, cast):
        return (tuple(sorted(Counter(cast.values()).items())) == self.counts
                and all(cast[cid] == role for cid, role in self.fixed)
                and all(cast[cid] in roles for cid, roles in self.domains))


@dataclass(frozen=True)
class JointGuessProbability:
    status: str
    total_mass: float | None = None
    support_count: int | None = None
    best_guess: tuple[tuple[str, str], ...] | None = None
    best_guess_probability: float | None = None
    partition_groups: int = 0
    nodes: int = 0
    reason: str | None = None
    _characters: tuple[str, ...] = field(default=(), repr=False)
    _split: bool = field(default=False, repr=False)
    _groups: tuple[_CastGroup, ...] = field(default=(), repr=False)
    _index: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def exact(self):
        return self.status == "exact"

    def probability_for(self, guess):
        """Score a complete initial cast; the query never changes inference."""
        if (not isinstance(guess, Mapping) or set(guess) != set(self._characters)
                or any(not isinstance(role, str) for role in guess.values())):
            raise ValueError("guess must contain every initial character with string roles")
        if not self.exact:
            return None
        if not _gender_ok(guess, self._split):
            return 0.0
        row = self._index.get(tuple(sorted(Counter(guess.values()).items())))
        if row is None:
            return 0.0
        fixed_ids, groups = row
        group = groups.get(tuple((cid, guess[cid]) for cid in fixed_ids))
        return (group.per_cast_mass / self.total_mass
                if group is not None and group.contains(guess) else 0.0)

    def to_dict(self):
        return {"version": "joint-cast-probability-v1", "status": self.status,
                "exact": self.exact, "method": "counted_cast_partition",
                "model": "factorized-role-posterior-v1",
                "target_version": RolePosteriorTarget.version,
                "total_mass": self.total_mass, "support_count": self.support_count,
                "best_guess": dict(self.best_guess) if self.best_guess is not None else None,
                "best_guess_probability": self.best_guess_probability,
                "partition_groups": self.partition_groups, "nodes": self.nodes,
                "reason": self.reason, "ess": None, "numerical_error": None}


class _WorkLimit(Exception):
    pass


class JointGuessProbabilitySolver:
    """Bounded exact partition; failure never yields a truncated probability.

    Incident weights cancel in the current independent role model, provided
    their joint support is nonempty. Dark-card observations affect identities
    only through the compiled role witnesses. This is not a correlated-world
    posterior or a calibrated human opponent success probability.
    """

    def __init__(self, *, node_limit=100_000):
        if type(node_limit) is not int or node_limit < 1:
            raise ValueError("node_limit must be a positive integer")
        self.node_limit = node_limit

    def solve(self, evidence: PublicEvidence, witnesses=()):
        characters = tuple(sorted(evidence.characters))
        split = bool(MODULES[evidence.module].friend_gender_split) if evidence.module in MODULES else False
        nodes = 0

        def unavailable(status, reason):
            return JointGuessProbability(status, nodes=nodes, reason=reason,
                                         _characters=characters, _split=split)

        if evidence.module not in {"FS", "BTX"}:
            return unavailable("unsupported_module", "only FS/BTX role targets are supported")
        facts = tuple(witnesses)
        role_facts = FactorizedBeliefState._role_witnesses(facts)
        if any(w.kind not in _INCIDENT_FACTS and w not in role_facts for w in facts):
            return unavailable("unsupported_witness", "unclassified witness requires a factorization contract")
        domains = culprit_domains(characters, evidence.schedule, dict(evidence.known_culprits), facts)
        if not joint_culprit_posterior(evidence.schedule, domains).partition:
            return unavailable("no_compatible_worlds", "incident support is empty")
        placeholders = role_incident_placeholders(evidence)
        variants = _variants(evidence, role_facts)
        if placeholders is None or not variants:
            return unavailable("no_compatible_worlds", "role or incident support is empty")
        incidents = tuple((day, kind, kind, cid) for day, kind, cid in placeholders)
        target = RolePosteriorTarget(evidence)
        by_counts = defaultdict(list)
        for variant in variants:
            counts = tuple(sorted((role, amount) for role, amount in variant.counts.items() if amount))
            by_counts[counts].append(variant)
        groups = []
        from .belief_plot_constraints import _genders

        try:
            for count_key, selected in sorted(by_counts.items()):
                union = {cid: tuple(sorted(set().union(*(v.domains[cid] for v in selected))))
                         for cid in characters}
                relevant = _dependencies(role_facts, selected, characters)
                # Plot-specific domains and extra-character choices must be
                # fixed before counting a common suffix across latent plots.
                relevant.update(cid for cid in characters
                                if len({v.domains[cid] for v in selected}) > 1)
                relevant.update(cid for v in selected for cid in v.extra_roles)
                order = tuple(sorted(relevant, key=lambda cid: (len(union[cid]), cid)))
                remaining = Counter(dict(count_key))
                fixed = {}

                def visit(index, male=False, female=False):
                    nonlocal nodes
                    nodes += 1
                    if nodes > self.node_limit:
                        raise _WorkLimit
                    if not any(all(role in v.domains[cid] for cid, role in fixed.items()) for v in selected):
                        return
                    tail = tuple(cid for cid in characters if cid not in fixed)
                    completions = FactorizedBeliefState._assignment_count(
                        tail, union, remaining, friend_gender_split=split,
                        used_friend_genders=(male, female))
                    if not completions:
                        return
                    if index < len(order):
                        cid = order[index]
                        for role in union[cid]:
                            if not remaining[role]:
                                continue
                            m, f = _genders(cid) if split and role == "friend" else (False, False)
                            if m and male or f and female:
                                continue
                            fixed[cid] = role
                            remaining[role] -= 1
                            visit(index + 1, male or m, female or f)
                            remaining[role] += 1
                            del fixed[cid]
                        return
                    cast = FactorizedBeliefState._complete_assignment(
                        characters, union, Counter(dict(count_key)), fixed,
                        friend_gender_split=split)
                    if cast is None:
                        return
                    roles = tuple(sorted(cast.items()))
                    masses, seen = [], set()
                    for variant in selected:
                        plot_key = (variant.main_plot, tuple(sorted(variant.subplots)))
                        if plot_key in seen or any(cast[cid] not in allowed for cid, allowed in variant.domains.items()):
                            continue
                        world = HiddenWorldHypothesis("joint-cast-probability", variant.main_plot,
                                                      variant.subplots, roles, incidents)
                        try:
                            world.materialize(evidence)
                        except RuleError:
                            continue
                        weight = target.weight(world, role_facts)
                        if weight:
                            masses.append(weight)
                            seen.add(plot_key)
                    mass = fsum(masses)
                    if mass:
                        groups.append(_CastGroup(count_key, tuple(union.items()), tuple(sorted(fixed.items())),
                                                 roles, completions, mass))

                visit(0)
        except _WorkLimit:
            return unavailable("work_limit", "exact partition exceeded node limit; no partial probabilities")
        if not groups:
            return unavailable("no_compatible_worlds", "all complete role groups were rejected")
        total = fsum(g.completions * g.per_cast_mass for g in groups)
        best = max(groups, key=lambda g: (g.per_cast_mass, g.representative))
        index = {}
        for group in groups:
            fixed_ids = tuple(cid for cid, _ in group.fixed)
            ids, rows = index.setdefault(group.counts, (fixed_ids, {}))
            if ids != fixed_ids or group.fixed in rows:
                raise AssertionError("Cast partition groups overlap or have inconsistent dependencies")
            rows[group.fixed] = group
        return JointGuessProbability("exact", total, sum(g.completions for g in groups),
                                     best.representative, best.per_cast_mass / total, len(groups), nodes,
                                     _characters=characters, _split=split, _groups=tuple(groups), _index=index)
