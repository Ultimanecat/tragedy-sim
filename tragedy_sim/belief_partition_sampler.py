"""Exact role/plot posterior draws from counted cast partitions.

The public role model is exact up to its floating soft weights. Draws are
independent with replacement; compressed MAP representatives are never a
sampling population. Culprit and dark-card factors remain separate.
"""

from collections import Counter
from copy import deepcopy

from .belief import HiddenWorldHypothesis
from .belief_matrix_sampler import RoleProposal, _completion_count_cached, role_incident_placeholders
from .belief_plot_constraints import _genders
from .belief_posterior import RolePosteriorTarget
from .final_guess_probability import JointGuessProbabilitySolver


def validate_role_sampling_options(policy, node_limit, matrix_proposals):
    if type(policy) is not str or policy not in {"importance", "exact_partition"}:
        raise ValueError("role_sampling_policy must be importance or exact_partition")
    if type(node_limit) is not int or node_limit < 1:
        raise ValueError("role_partition_node_limit must be a positive integer")
    if policy == "exact_partition" and not matrix_proposals:
        raise ValueError("exact_partition requires matrix_proposals")


def _unrank_cast(group, *, split, rank):
    """Uniform integer rank -> full cast, with exact suffix completion counts."""
    if type(rank) is not int or not 0 <= rank < group.completions:
        raise ValueError("rank must index a group completion")
    cast = dict(group.fixed)
    remaining = Counter(dict(group.counts))
    remaining.subtract(cast.values())
    domains = dict(group.domains)
    characters = tuple(sorted(cid for cid in domains if cid not in cast))
    male = female = False
    if split:
        for cid, role in cast.items():
            if role == "friend":
                m, f = _genders(cid)
                if male and m or female and f:
                    raise AssertionError("partition fixed identities violate friend genders")
                male, female = male or m, female or f
    for index, cid in enumerate(characters):
        tail = characters[index + 1:]
        for role in domains[cid]:
            if remaining[role] < 1:
                continue
            m, f = _genders(cid) if split and role == "friend" else (False, False)
            if male and m or female and f:
                continue
            genders = male or m, female or f
            remaining[role] -= 1
            size = _completion_count_cached(
                tail, tuple((who, domains[who]) for who in tail),
                tuple(sorted(remaining.items())), split, genders)
            if rank < size:
                cast[cid] = role
                male, female = genders
                break
            remaining[role] += 1
            rank -= size
        else:
            raise AssertionError("counted partition cannot complete its sampled rank")
    if rank or any(remaining.values()):
        raise AssertionError("partition rank or remaining counts did not exhaust")
    return tuple(sorted(cast.items()))


class PartitionRoleSampler:
    """Bound one public evidence snapshot, counted mass and explicit q.

    Unavailable partitions return no proposals and consume no RNG. Callers
    must inspect status and explicitly choose a baseline fallback. Validation
    failures after an exact count are bugs, never rejection/resampling that
    could hide a wrong normalization.
    """
    policy = "exact_partition"

    def __init__(self, evidence, witnesses=(), *, node_limit=100_000):
        self.evidence = deepcopy(evidence)
        self.witnesses = deepcopy(tuple(witnesses))
        self.partition = JointGuessProbabilitySolver(node_limit=node_limit).solve(
            self.evidence, self.witnesses)
        self._group_weights = tuple(group.completions * group.per_cast_mass
                                    for group in self.partition._groups)
        self.role_witnesses = ()
        self.target = None
        self.incidents = ()
        if self.partition.exact:
            from .belief import FactorizedBeliefState
            self.role_witnesses = FactorizedBeliefState._role_witnesses(self.witnesses)
            self.target = RolePosteriorTarget(self.evidence)
            self.incidents = tuple((day, kind, kind, cid)
                                   for day, kind, cid in role_incident_placeholders(self.evidence))
        self.draws = 0

    def propose_roles(self, count, *, rng):
        if type(count) is not int or count < 1:
            raise ValueError("count must be a positive integer")
        if not self.partition.exact:
            return ()
        groups = self.partition._groups
        proposals = []
        for _ in range(count):
            group = rng.choices(groups, weights=self._group_weights, k=1)[0]
            cast = _unrank_cast(group, split=self.partition._split,
                                rank=rng.randrange(group.completions))
            main, subs, mass = rng.choices(group.latent_weights,
                                          weights=[item[2] for item in group.latent_weights], k=1)[0]
            world = HiddenWorldHypothesis("belief-partition-posterior", main, subs, cast, self.incidents)
            # The full validator and matcher/target prove the class really
            # has constant mass. No successful prefix is returned on error.
            world.materialize(self.evidence)
            actual_mass = self.target.weight(world, self.role_witnesses)
            if actual_mass != mass:
                raise AssertionError("sampled world differs from its counted role-class mass")
            density = mass / self.partition.total_mass
            proposals.append(RoleProposal(world, density, self.policy))
        self.draws += count
        return tuple(proposals)

    def diagnostics(self):
        return {"policy": self.policy, "partition": self.partition.to_dict(),
                "density_scope": "initial_roles_and_plots_given_role_evidence",
                "draws": self.draws, "independent_with_replacement": True}
