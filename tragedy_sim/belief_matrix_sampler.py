"""Constructive recovery using shared plot/count/domain support.

This is a proposal mechanism, not an exact posterior sampler. Random complete
assignments are drawn inside a conservative variant, then validated and matched
against all supplied witnesses. No secret game state is an input.
"""

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from .belief import (ConstraintBeliefSampler, FactorizedBeliefState,
                     HiddenWorldHypothesis)
from .belief_matrix import BeliefContradiction, role_domains
from .belief_plot_constraints import _genders, plot_role_variants
from .catalog import MODULES
from .engine import RuleError
from .scenario import validate_scenario
from .witness import FsbtxWitnessMatcher


@dataclass(frozen=True)
class RoleProposal:
    world: HiddenWorldHypothesis
    density: float
    policy: str = "uniform"


@lru_cache(maxsize=64)
def role_incident_placeholders(evidence):
    """One legal schedule for role validation, independent of cast sampling.

    Incidents are replaced by the culprit sampler before search. Reserving
    known culprits and backtracking avoids accidental role-space exclusions.
    """
    known = {day: "part_timer" if cid == "part_timer_question" else cid
             for day, cid in evidence.known_culprits}
    characters = evidence.characters

    @lru_cache(maxsize=None)
    def assign(index, ordinary_used, serial_used):
        if index == len(evidence.schedule):
            return ()
        day, kind = evidence.schedule[index]
        serial = kind == "serial_murder"
        options = (known[day],) if day in known else characters
        for cid in options:
            if cid not in characters:
                continue
            bit = 1 << characters.index(cid)
            if ordinary_used & bit or (not serial and serial_used & bit):
                continue
            tail = assign(index + 1, ordinary_used | (0 if serial else bit),
                          serial_used | (bit if serial else 0))
            if tail is not None:
                return ((day, kind, cid), *tail)
        return None

    return assign(0, 0, 0)


def _random_cast(variant, module, rng):
    result = dict(variant.extra_roles)
    remaining = Counter(variant.regular_counts)
    regular = [cid for cid in variant.domains if cid not in result]
    rng.shuffle(regular)
    male = female = False
    split = MODULES[module].friend_gender_split
    for cid, role in result.items():
        if split and role == "friend":
            next_male, next_female = _genders(cid)
            if next_male and male or next_female and female:
                return None
            male |= next_male
            female |= next_female
    domains = {cid: tuple(sorted(variant.domains[cid])) for cid in regular}
    for index, cid in enumerate(regular):
        choices, weights = [], []
        for role in domains[cid]:
            if remaining[role] < 1:
                continue
            next_male, next_female = male, female
            if split and role == "friend":
                is_male, is_female = _genders(cid)
                if is_male and male or is_female and female:
                    continue
                next_male |= is_male
                next_female |= is_female
            remaining[role] -= 1
            completions = FactorizedBeliefState._assignment_count(
                tuple(regular[index + 1:]), domains, remaining,
                friend_gender_split=split, used_friend_genders=(next_male, next_female))
            remaining[role] += 1
            if completions:
                choices.append(role)
                weights.append(completions)
        if not choices:
            return None
        selected = rng.choices(choices, weights=weights, k=1)[0]
        result[cid] = selected
        remaining[selected] -= 1
        if split and selected == "friend":
            next_male, next_female = _genders(cid)
            male |= next_male
            female |= next_female
    return result if not any(remaining.values()) else None


class MatrixWorldSampler:
    def propose_roles(self, evidence, witnesses, count, *, rng, max_attempts=None,
                      variant_policy="prior", target=None):
        """Repeated role draws with an explicit pre-rejection density.

        Variants can follow their initial-prior support mass; casts inside
        each variant are uniform by completion counts. Residual hard
        rejection has a common normalization constant, which cancels in
        normalized importance weights. No uniqueness filtering is applied.
        """
        from .belief_posterior import RolePosteriorTarget, variant_size

        if type(count) is not int or count < 1:
            raise ValueError("count must be a positive integer")
        if max_attempts is not None and (type(max_attempts) is not int or max_attempts < 1):
            raise ValueError("max_attempts must be a positive integer")
        if type(variant_policy) is not str or variant_policy not in {"uniform", "prior"}:
            raise ValueError("variant_policy must be uniform or prior")
        hard = tuple(w for w in FactorizedBeliefState._role_witnesses(witnesses)
                     if w.strength == "hard")
        view = {"module": evidence.module,
                "characters": dict.fromkeys(evidence.characters, {}),
                "known_roles": {cid: {"role": role} for cid, role in evidence.known_roles}}
        try:
            _, domains, _ = role_domains(view, hard)
        except BeliefContradiction:
            return ()
        variants = plot_role_variants(evidence, domains, hard)
        sized = tuple((v, variant_size(v, evidence.module)) for v in variants)
        sized = tuple((v, size) for v, size in sized if size)
        placeholders = role_incident_placeholders(evidence)
        if not sized or placeholders is None:
            return ()
        if variant_policy == "prior":
            target = target or RolePosteriorTarget(evidence)
            variant_weights = tuple(size * target.plot_cast_weight(v.main_plot, v.subplots)
                                    for v, size in sized)
        else:
            variant_weights = (1,) * len(sized)
        normalizer = sum(variant_weights)
        if not normalizer:
            return ()
        incidents = [{"day": day, "kind": kind, "culprit": cid}
                     for day, kind, cid in placeholders]
        matcher = FsbtxWitnessMatcher()
        results = []
        for _ in range(max_attempts or max(64, count * 12)):
            index = (rng.randrange(len(sized)) if variant_policy == "uniform" else
                     rng.choices(range(len(sized)), weights=variant_weights, k=1)[0])
            variant, size = sized[index]
            cast = _random_cast(variant, evidence.module, rng)
            if cast is None:
                continue
            try:
                scenario = validate_scenario({
                    "id": "belief-role-proposal", "title": "Weighted role proposal",
                    "module": evidence.module, "days": evidence.days, "loops": evidence.loops,
                    "main_plot": variant.main_plot, "subplots": list(variant.subplots),
                    "cast": cast, "incidents": incidents, "table_talk": evidence.table_talk,
                    **evidence.setup_fields()})
            except RuleError:
                continue
            world = HiddenWorldHypothesis.from_scenario(scenario)
            if matcher.matches(world, hard):
                density = (1.0 / (len(sized) * size) if variant_policy == "uniform" else
                           variant_weights[index] / normalizer / size)
                results.append(RoleProposal(world, density, variant_policy))
                if len(results) == count:
                    break
        return tuple(results)

    def sample(self, evidence, witnesses, count, *, rng, max_attempts=None):
        if type(count) is not int or count < 1:
            raise ValueError("count must be a positive integer")
        view = {"module": evidence.module,
                "characters": dict.fromkeys(evidence.characters, {}),
                "known_roles": {cid: {"role": role} for cid, role in evidence.known_roles}}
        try:
            _, domains, _ = role_domains(view, witnesses)
        except BeliefContradiction:
            return ()
        variants = plot_role_variants(evidence, domains, witnesses)
        if not variants:
            return ()
        matcher = FsbtxWitnessMatcher()
        results, seen = [], set()
        for _ in range(max_attempts or max(64, count * 12)):
            variant = rng.choice(variants)
            cast = _random_cast(variant, evidence.module, rng)
            incidents = ConstraintBeliefSampler._incidents(evidence, rng)
            if cast is None or incidents is None:
                continue
            try:
                scenario = validate_scenario({
                    "id": "belief-matrix-recovery", "title": "Matrix proposal",
                    "module": evidence.module, "days": evidence.days, "loops": evidence.loops,
                    "main_plot": variant.main_plot, "subplots": list(variant.subplots),
                    "cast": cast, "incidents": incidents, "table_talk": evidence.table_talk,
                    **evidence.setup_fields()})
            except RuleError:
                continue
            world = HiddenWorldHypothesis.from_scenario(scenario)
            signature = (world.main_plot, world.subplots, world.roles, world.incidents)
            if signature in seen or not matcher.matches(world, witnesses):
                continue
            seen.add(signature)
            results.append(world)
            if len(results) == count:
                break
        return tuple(results)
