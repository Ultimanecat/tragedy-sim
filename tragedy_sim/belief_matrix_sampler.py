"""Constructive recovery using shared plot/count/domain support.

This is a proposal mechanism, not an exact posterior sampler. Random complete
assignments are drawn inside a conservative variant, then validated and matched
against all supplied witnesses. No secret game state is an input.
"""

from collections import Counter

from .belief import (ConstraintBeliefSampler, FactorizedBeliefState,
                     HiddenWorldHypothesis)
from .belief_matrix import BeliefContradiction, role_domains
from .belief_plot_constraints import _genders, plot_role_variants
from .catalog import MODULES
from .engine import RuleError
from .scenario import validate_scenario
from .witness import FsbtxWitnessMatcher


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
