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
from .witness_rules.role_routes import HARD_ROLE_ROUTES, role_route_realizations


_PLOT_FACTS = {"plot_present", "plot_not_present", "plot_pressure"}
_INCIDENT_FACTS = {"culprit_is", "culprit_in", "incident_happened", "incident_not_happened"}

def _role_tests(witnesses, variants, domains):
    """Unary membership tests sufficient to preserve every role verdict.

    Existential routes with one role per alternative can group roles by
    character; conjunctive routes retain each separate equality. Distinct
    latent plots keep separate tests. Unknown future role factors fall back
    to complete identity branching, never inferred equivalence.
    """
    tests = defaultdict(set)

    def add(cid, roles):
        cid = "part_timer" if cid == "part_timer_question" else cid
        if cid in domains:
            tests[cid].add(frozenset(roles))

    def add_routes(routes):
        if any(not route for route in routes):
            return  # A plot-only explanation makes this predicate constant.
        if all(len(route) == 1 for route in routes):
            by_character = defaultdict(set)
            for route in routes:
                for cid, role in route.items():
                    by_character[cid].add(role)
            for cid, roles in by_character.items():
                add(cid, roles)
        else:
            for route in routes:
                for cid, role in route.items():
                    add(cid, (role,))

    for witness in witnesses:
        kind, subject, value = witness.kind, witness.subject, witness.value
        if witness.kind in _PLOT_FACTS:
            continue
        if witness.strength == "hard" and witness.kind in {"role_is", "role_in", "role_not_in"}:
            # Fully enforced by each plot domain, including Virus conditions.
            continue
        if kind in HARD_ROLE_ROUTES:
            for main, subs in {(v.main_plot, v.subplots) for v in variants}:
                add_routes(role_route_realizations(witness, (main, *subs)))
        elif kind == "role_is":
            add(subject, (value,))
            if value == "serial":
                add(subject, ("ordinary",))
        elif kind in {"role_in", "role_not_in"}:
            add(subject, value)
        elif kind == "joint_plot_role_pressure":
            for cid in value.get("candidates", ()):
                add(cid, (value.get("role"),))
        elif kind == "day_end_death_companion":
            cid = value.get("character") if isinstance(value, Mapping) else value
            add(cid, ("serial",))
            if isinstance(value, Mapping) and value.get("virus_eligible"):
                add(cid, ("ordinary",))
        elif kind == "day_end_killer_candidate":
            add(subject, ("key",))
            add(value, ("killer",))
        elif kind == "loss_after_death":
            roles = {"key", "friend"}
            if value.get("factor_key_possible"):
                roles.add("factor")
            add(subject, roles)
        else:
            for cid, roles in domains.items():
                for role in roles:
                    add(cid, (role,))
    return tests


def _role_classes(witnesses, variants, domains, extras):
    tests = _role_tests(witnesses, variants, domains)
    classes = {}
    for cid, roles in domains.items():
        if cid in extras:
            continue
        predicates = sorted(tests[cid], key=lambda values: tuple(sorted(values)))
        grouped = defaultdict(list)
        for role in roles:
            signature = (tuple(role in v.domains[cid] for v in variants),
                         tuple(role in values for values in predicates))
            grouped[signature].append(role)
        choices = tuple(sorted(tuple(values) for values in grouped.values()))
        if len(choices) > 1:
            classes[cid] = choices
    return classes


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
    _extra_characters: tuple[str, ...] = field(default=(), repr=False)

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
        extra_groups = self._index.get(tuple(sorted(Counter(guess.values()).items())), {})
        extra_key = tuple((cid, guess[cid]) for cid in self._extra_characters)
        row = extra_groups.get(extra_key)
        if row is None:
            return 0.0
        classifiers, groups = row
        group = groups.get(tuple(roles.get(guess[cid], -1) for cid, roles in classifiers))
        return (group.per_cast_mass / self.total_mass
                if group is not None and group.contains(guess) else 0.0)

    def to_dict(self):
        return {"version": "joint-cast-probability-v1", "status": self.status,
                "exact": self.exact, "method": "counted_cast_partition",
                "solver_policy": "predicate_role_classes-v3",
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
        extra_characters = tuple(cid for cid in characters if cid in {"irregular", "copycat"})
        for variant in variants:
            counts = tuple(sorted((role, amount) for role, amount in variant.counts.items() if amount))
            # Different extra identities describe disjoint cast sets. Their
            # printed-slot subtraction changes regular domains, so establish
            # this choice before finding role dependencies across plots.
            extra_key = tuple(sorted(variant.extra_roles.items()))
            by_counts[counts, extra_key].append(variant)
        groups, index = [], {}
        from .belief_plot_constraints import _genders

        try:
            for (count_key, extra_key), selected in sorted(by_counts.items()):
                union = {cid: tuple(sorted(set().union(*(v.domains[cid] for v in selected))))
                         for cid in characters}
                fixed = dict(extra_key)
                classes = _role_classes(role_facts, selected, union, fixed)
                order = tuple(sorted(classes, key=lambda cid: (len(classes[cid]), cid)))
                classifiers = tuple((cid, {role: i for i, values in enumerate(classes[cid]) for role in values})
                                    for cid in order)
                rows = {}
                index.setdefault(count_key, {})[extra_key] = classifiers, rows
                active_domains = dict(union)
                signature = []
                remaining = Counter(dict(count_key))
                remaining.subtract(fixed.values())
                if any(amount < 0 for amount in remaining.values()) or not _gender_ok(fixed, split):
                    continue
                initial_male = initial_female = False
                if split:
                    for cid, role in fixed.items():
                        if role == "friend":
                            m, f = _genders(cid)
                            initial_male, initial_female = initial_male or m, initial_female or f

                def visit(index, male=False, female=False):
                    nonlocal nodes
                    nodes += 1
                    if nodes > self.node_limit:
                        raise _WorkLimit
                    if not any(all(set(active_domains[cid]) & v.domains[cid] for cid in characters)
                               for v in selected):
                        return
                    tail = tuple(cid for cid in characters if cid not in fixed)
                    completions = FactorizedBeliefState._assignment_count(
                        tail, active_domains, remaining, friend_gender_split=split,
                        used_friend_genders=(male, female))
                    if not completions:
                        return
                    if index < len(order):
                        cid = order[index]
                        for choice, values in enumerate(classes[cid]):
                            if not any(remaining[role] for role in values):
                                continue
                            active_domains[cid] = values
                            signature.append(choice)
                            if len(values) == 1:
                                role = values[0]
                                m, f = _genders(cid) if split and role == "friend" else (False, False)
                                if not (m and male or f and female):
                                    fixed[cid] = role
                                    remaining[role] -= 1
                                    visit(index + 1, male or m, female or f)
                                    remaining[role] += 1
                                    del fixed[cid]
                            else:
                                visit(index + 1, male, female)
                            signature.pop()
                        active_domains[cid] = union[cid]
                        return
                    cast = FactorizedBeliefState._complete_assignment(
                        characters, active_domains, Counter(dict(count_key)), fixed,
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
                        group = _CastGroup(count_key, tuple(active_domains.items()), tuple(sorted(fixed.items())),
                                           roles, completions, mass)
                        if tuple(signature) in rows:
                            raise AssertionError("Cast predicate partitions overlap")
                        rows[tuple(signature)] = group
                        groups.append(group)

                visit(0, initial_male, initial_female)
        except _WorkLimit:
            return unavailable("work_limit", "exact partition exceeded node limit; no partial probabilities")
        if not groups:
            return unavailable("no_compatible_worlds", "all complete role groups were rejected")
        total = fsum(g.completions * g.per_cast_mass for g in groups)
        best = max(groups, key=lambda g: (g.per_cast_mass, g.representative))
        return JointGuessProbability("exact", total, sum(g.completions for g in groups),
                                     best.representative, best.per_cast_mass / total, len(groups), nodes,
                                     _characters=characters, _split=split, _groups=tuple(groups), _index=index,
                                     _extra_characters=extra_characters)
