"""Script-independent FS/BTX role target, separate from proposal algorithms.

Printed setup defines the prior. Observations affect likelihood/support only.
The omitted uniform plot constant cancels in MAP and normalized posteriors.
"""
from collections import Counter
from dataclasses import replace
from functools import lru_cache
from math import isfinite

from .belief import FactorizedBeliefState
from .belief_plot_constraints import _genders, plot_role_variants
from .catalog import MODULES


def variant_size(variant, module):
    """Exact count inside one matrix outer-support count/domain variant."""
    split = MODULES[module].friend_gender_split
    male = female = False
    for cid, role in variant.extra_roles.items():
        if split and role == "friend":
            next_male, next_female = _genders(cid)
            if next_male and male or next_female and female:
                return 0
            male |= next_male
            female |= next_female
    regular = tuple(sorted(cid for cid in variant.domains if cid not in variant.extra_roles))
    return FactorizedBeliefState._assignment_count(
        regular, {cid: tuple(sorted(variant.domains[cid])) for cid in regular},
        Counter(variant.regular_counts), friend_gender_split=split,
        used_friend_genders=(male, female))


@lru_cache(maxsize=64)
def _initial_plot_sizes(setup):
    from .belief_matrix import role_domains

    view = {"module": setup.module,
            "characters": dict.fromkeys(setup.characters, {})}
    _, domains, _ = role_domains(view, ())
    result = Counter()
    for variant in plot_role_variants(setup, domains, ()):
        result[variant.main_plot, variant.subplots] += variant_size(variant, setup.module)
    return tuple(sorted(result.items()))


class RolePosteriorTarget:
    """Uniform initial plot sets, uniform printed-valid casts within a plot.

    Soft scores are an explicit heuristic log2 likelihood, not calibrated
    behavior probabilities. This class consumes no RNG or private script.
    """
    version = "uniform-printed-casts-v1"

    def __init__(self, evidence):
        if evidence.module not in {"FS", "BTX"}:
            raise ValueError("Role posterior target currently supports FS/BTX")
        self.evidence = evidence
        initial = replace(evidence, known_roles=(), known_initial_roles=(), known_plots=(), known_culprits=())
        self.plot_sizes = dict(_initial_plot_sizes(initial))
        self._canonical_sizes = {(main, tuple(sorted(subs))): size
                                 for (main, subs), size in self.plot_sizes.items()}

    def prior_weight(self, world):
        return self.plot_cast_weight(world.main_plot, world.subplots)

    def plot_cast_weight(self, main_plot, subplots):
        size = self._canonical_sizes.get((main_plot, tuple(sorted(subplots))), 0)
        return 1.0 / size if size else 0.0

    def weight(self, world, witnesses):
        from .witness import FsbtxWitnessMatcher

        matcher = FsbtxWitnessMatcher()
        if (not self.evidence.matches_roles(world.main_plot, world.subplots, world.roles)
                or not matcher.matches(world, witnesses)):
            return 0.0
        return self.prior_weight(world) * (2.0 ** matcher.soft_score(world, witnesses))

    def diagnostics(self):
        return {"version": self.version, "prior": "uniform_initial_plot_then_printed_cast",
                "likelihood": "heuristic_exp2_soft_score",
                "initial_plot_sets": len(self.plot_sizes)}


class RoleImportancePool:
    """A fixed batch with duplicate draws and proposal densities retained.

    Recompute current evidence weights from scratch; q never changes. An
    unknown-density legacy reservoir is deliberately not an input.
    """
    version = "matrix-role-importance-v1"

    def __init__(self, proposals):
        self.proposals = tuple(proposals)
        if any(not isfinite(p.density) or not 0 < p.density <= 1 for p in self.proposals):
            raise ValueError("Proposal densities must be finite and in (0, 1]")

    def posterior(self, target, witnesses):
        worlds, masses = {}, Counter()
        for proposal in self.proposals:
            key = FactorizedBeliefState._key(proposal.world)
            worlds[key] = proposal.world
            masses[key] += target.weight(proposal.world, witnesses) / proposal.density
        return tuple((worlds[key], mass) for key, mass in masses.items() if mass > 0)

    def diagnostics(self, target, witnesses):
        weights = tuple(target.weight(p.world, witnesses) / p.density for p in self.proposals)
        total = sum(weights)
        square_sum = sum(weight * weight for weight in weights)
        return {"estimator": self.version, "proposal_draws": len(weights),
                "proposal_policies": sorted({p.policy for p in self.proposals}),
                "unique_roles": len({FactorizedBeliefState._key(p.world) for p in self.proposals}),
                "effective_sample_size": total * total / square_sum if square_sum else 0.0,
                "max_normalized_draw_weight": max(weights, default=0) / total if total else 0.0}
