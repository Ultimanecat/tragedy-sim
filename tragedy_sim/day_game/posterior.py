"""Public matrix/witness posterior -> weighted setup worlds -> FS day roots.

Uses counted role partitions and legal joint culprit suffixes. Selection is
lazy and probability ordered, retaining ORIGINAL mass under the declared
factorized model. Sampling frequencies/MAP representatives are not masses.
Hidden current-state reconstruction is a separate, explicitly scoped model.
"""

from copy import deepcopy
from collections.abc import Mapping
from dataclasses import dataclass, replace
from fractions import Fraction
from functools import lru_cache
import heapq
import random

from ..belief import FactorizedBeliefState, HiddenWorldHypothesis, PublicEvidence, PublicSnapshot
from ..belief_culprit_constraints import culprit_domains
from ..belief_culprit_posterior import JointCulpritPosterior, culprit_likelihood_weights
from ..belief_partition_sampler import PartitionRoleSampler, _unrank_cast
from ..belief_planner import PublicStateDeterminizer
from ..domain import ScriptDefinition
from ..engine import RuleError
from ..game import Game
from ..witness import FsbtxWitnessCompiler, FsbtxWitnessMatcher
from .fair_engine import bayesian_engine_game
from .matrix import rational


class PosteriorUnavailable(ValueError):
    pass


def _check_team_root(view):
    if (not isinstance(view, Mapping) or not isinstance(view.get("team_hands"), Mapping)
            or not isinstance(view.get("pending"), (tuple, list))
            or any(not isinstance(p, Mapping) for p in view.get("pending", ()))
            or view.get("module") not in {"FS", "BTX"}
            or view.get("viewer") != "team" or "secret" in view
            or set(view.get("team_hands", {})) != {"a", "b", "c"} or view.get("phase") != "protagonists"
            or len(view.get("pending", ())) != 3
            or any(p.get("actor") != "m" or p.get("card") is not None for p in view.get("pending", ()))):
        raise ValueError("requires an authorized uncommitted team placement view")


def _ordered_roles(sampler, weights, total):
    groups = sampler.partition._groups
    heap = [(-weight/total, 0, g, latent) for g, group in enumerate(groups)
            for latent, weight in enumerate(weights[g])]
    heapq.heapify(heap)
    while heap:
        negative, rank, g, latent = heapq.heappop(heap)
        group = groups[g]
        main, subplots, _ = group.latent_weights[latent]
        cast = _unrank_cast(group, split=sampler.partition._split, rank=rank)
        world = HiddenWorldHypothesis("public-day-posterior", main, subplots, cast, sampler.incidents)
        yield world, -negative
        if rank+1 < group.completions:
            heapq.heappush(heap, (negative, rank+1, g, latent))


def _ordered_culprits(joint):
    """A* over assignment prefixes; exact max-suffix bounds order leaves."""
    @lru_cache(maxsize=None)
    def best(index, ordinary, serial):
        if index == len(joint.schedule):
            return Fraction(1)
        return max((weight*best(index+1, *next_masks)
                    for cid, weight in joint._rows[index]
                    if (next_masks := joint._advance(index, cid, ordinary, serial)) is not None), default=Fraction(0))
    heap = [(-best(0, 0, 0), 0, (), Fraction(1), 0, 0)]
    while heap:
        _, negative_depth, choices, prefix, ordinary, serial = heapq.heappop(heap)
        index = -negative_depth
        if index == len(joint.schedule):
            yield choices, prefix/joint.partition
            continue
        for cid, weight in joint._rows[index]:
            masks = joint._advance(index, cid, ordinary, serial)
            if masks is not None and (bound := best(index+1, *masks)):
                score = prefix*weight
                heapq.heappush(heap, (-score*bound, -index-1, (*choices, cid), score, *masks))


def _culprit_count(joint):
    @lru_cache(maxsize=None)
    def count(index, ordinary, serial):
        if index == len(joint.schedule):
            return 1
        return sum(count(index+1, *masks) for cid, _ in joint._rows[index]
                   if (masks := joint._advance(index, cid, ordinary, serial)) is not None)
    return count(0, 0, 0)


class _Lazy:
    def __init__(self, iterator):
        self.iterator, self.values, self.done = iter(iterator), [], False

    def get(self, index):
        while index >= len(self.values) and not self.done:
            try:
                self.values.append(next(self.iterator))
            except StopIteration:
                self.done = True
        return self.values[index] if index < len(self.values) else None


@dataclass(frozen=True)
class WeightedSetup:
    hypothesis: HiddenWorldHypothesis
    mass: Fraction


@dataclass(frozen=True)
class PosteriorSelection:
    worlds: tuple[WeightedSetup, ...]
    selected_mass: Fraction
    missing_mass: Fraction
    joint_support: int
    role_support: int
    culprit_support: int
    status: str
    role_target: str
    snapshot_key: str
    probability_model: str = "factorized-setup/rational-prior-frozen-exp2-v1"


class PublicWorldPosterior:
    """No Game/private script input. Work failure never invents normalization."""
    def __init__(self, view, *, witnesses=None, node_limit=100000):
        _check_team_root(view)
        self.snapshot_key = PublicSnapshot.from_view(view).key
        self.evidence = PublicEvidence.from_view(view)
        self.witnesses = deepcopy(tuple(FsbtxWitnessCompiler().compile(view) if witnesses is None else witnesses))
        self.roles = PartitionRoleSampler(self.evidence, self.witnesses, node_limit=node_limit)
        if not self.roles.partition.exact:
            raise PosteriorUnavailable("role_partition_" + self.roles.partition.status)
        domains = culprit_domains(self.evidence.characters, self.evidence.schedule,
                                   dict(self.evidence.known_culprits), self.witnesses)
        self.role_weights = tuple(tuple(self.roles.target.rational_weight(HiddenWorldHypothesis(
            "public-day-posterior", main, subplots, group.representative, self.roles.incidents), self.roles.role_witnesses)
            for main, subplots, _ in group.latent_weights) for group in self.roles.partition._groups)
        self.role_total = sum(g.completions*sum(w) for g, w in zip(self.roles.partition._groups, self.role_weights))
        if self.role_total <= 0 or any(w <= 0 for row in self.role_weights for w in row):
            raise PosteriorUnavailable("invalid_counted_role_weight")
        weights = {day: {cid: rational(weight) for cid, weight in row.items()}
                   for day, row in culprit_likelihood_weights(self.evidence.schedule, domains, self.witnesses).items()}
        self.culprits = JointCulpritPosterior(self.evidence.schedule, domains, weights)
        if not self.culprits.partition:
            raise PosteriorUnavailable("no_legal_joint_culprits")
        self.role_support = sum(g.completions*len(g.latent_weights) for g in self.roles.partition._groups)
        self.culprit_support = _culprit_count(self.culprits)

    def select(self, limit):
        if type(limit) is not int or limit < 1:
            raise ValueError("world limit must be a positive integer")
        roles = _Lazy(_ordered_roles(self.roles, self.role_weights, self.role_total))
        culprits = _Lazy(_ordered_culprits(self.culprits))
        heap, seen = [], set()

        def push(i, j):
            if (i, j) in seen:
                return
            seen.add((i, j))
            a, b = roles.get(i), culprits.get(j)
            if a is not None and b is not None:
                # Equal-probability worlds span both factors before extending
                # one long lexical row. Mass order and coverage stay exact.
                heapq.heappush(heap, (-a[1]*b[1], i+j, i, j))

        push(0, 0)
        selected = []
        while heap and len(selected) < limit:
            negative, _, i, j = heapq.heappop(heap)
            role, _ = roles.get(i)
            choices, _ = culprits.get(j)
            world = replace(role, incidents=tuple((day, kind, public, cid)
                            for (day, kind, public, _), cid in zip(role.incidents, choices)))
            # Future coupled witness rules must not silently become a new
            # normalized subset of this independently counted model.
            if not FsbtxWitnessMatcher().matches(world, self.witnesses):
                raise PosteriorUnavailable("unclassified_cross_factor_constraint")
            selected.append(WeightedSetup(world, -negative))
            push(i+1, j)
            push(i, j+1)
        mass = sum(w.mass for w in selected)
        support = self.role_support*self.culprit_support
        if mass > 1 or (len(selected) == support and mass != 1):
            raise RuntimeError("joint posterior stream has inconsistent total mass")
        return PosteriorSelection(tuple(selected), mass, 1-mass, support, self.role_support,
                                  self.culprit_support, "complete" if len(selected) == support else "partial",
                                  self.roles.target.version, self.snapshot_key)


def _public_context(world, view):
    world.scenario.update(id=str(view.get("scenario_id", world.scenario["id"])),
                          title=str(view.get("title", world.scenario["title"])))
    world.script = ScriptDefinition.from_mapping(world.scenario)
    world.protagonist_knowledge = deepcopy(view.get("protagonist_knowledge", {}))
    world.known_roles = deepcopy(view.get("known_roles", {}))
    world.known_culprits = {int(d): cid for d, cid in view.get("known_culprits", {}).items()}
    world.known_plots = list(view.get("known_plots", ()))
    world.role_announcements = deepcopy(view.get("role_announcements", ()))


def _initial_root(hypothesis, evidence, view, own_commands):
    if (view.get("loop"), view.get("round")) != (1, 1):
        return None, "midgame_hidden_state_prior"
    scenario = hypothesis.materialize(evidence)
    scenario.update(id=str(view.get("scenario_id", scenario["id"])), title=str(view.get("title", scenario["title"])))
    world = Game(scenario)
    for _ in range(256):
        if world.state.phase == "mastermind":
            break
        actions = world.legal_actions(world.controller)
        if len(actions) != 1:
            return None, "nonunique_initialization"
        world = world.transition(actions[0]).game
    else:
        return None, "initialization_depth_limit"
    for placement in view.get("pending", ()):
        action = next((a for a in world.legal_actions("m") if a.get("target") == placement["target"]), None)
        if action is None:
            return None, "initial_target_unavailable"
        world = world.transition(action).game
    _public_context(world, view)
    if [c for c in world.history if c["actor"] != "m"] != list(own_commands):
        return None, "initial_own_history_mismatch"
    if PublicSnapshot.from_view(world.protagonist_team_view()) != PublicSnapshot.from_view(view):
        return None, "initial_snapshot_mismatch"
    return world, None


@dataclass(frozen=True)
class RootSelection:
    roots: tuple
    posterior: PosteriorSelection
    failed_mass: Fraction
    approximated_state_mass: Fraction
    failures: tuple

    def model(self, **options):
        if not self.roots:
            raise PosteriorUnavailable("no_reconstructible_worlds")
        complete = self.posterior.status == "complete" and not self.failed_mass and not self.approximated_state_mass
        result = bayesian_engine_game(self.roots, belief_domain_complete=bool(complete), **options)
        result.scope += "/" + self.posterior.probability_model
        if self.approximated_state_mass:
            result.scope += "/public-snapshot-hidden-state-prior"
        return result


def reconstruct_public_roots(selection, view, *, own_commands=(), allow_state_prior=True):
    _check_team_root(view)
    if view.get("module") != "FS":
        raise ValueError("requires an uncommitted FS team placement view")
    if type(allow_state_prior) is not bool:
        raise ValueError("allow_state_prior must be boolean")
    if selection.snapshot_key != PublicSnapshot.from_view(view).key:
        raise ValueError("posterior selection belongs to another public snapshot")
    if not isinstance(own_commands, (tuple, list)) or any(not isinstance(c, dict) or c.get("actor") not in {"a", "b", "c"}
           or not isinstance(c.get("action"), str) for c in own_commands):
        raise ValueError("own_commands may contain protagonist commands only")
    evidence, roots, failures = PublicEvidence.from_view(view), [], []
    failed = approximated = Fraction(0)
    determinizer = PublicStateDeterminizer()
    for index, item in enumerate(selection.worlds):
        label = f"h{index}"
        try:
            # Numeric ability/target menus may use engine insertion order.
            # Keep the observed order independently from the sorted tuple
            # used to identify/count a role hypothesis.
            cast = dict(item.hypothesis.roles)
            order = tuple(cid for cid in view["characters"] if cid in cast)
            order += tuple(cid for cid in cast if cid not in order)
            hypothesis = replace(item.hypothesis, roles=tuple((cid, cast[cid]) for cid in order))
            world, reason = _initial_root(hypothesis, evidence, view, own_commands)
            exact = world is not None
            if world is None and allow_state_prior:
                world = determinizer.determinize(hypothesis, evidence, view, rng=random.Random(0))
                if world is not None:
                    _public_context(world, view)
                    world.history = deepcopy(list(own_commands))
                    world.decisions = []
                    world._observation_checkpoints = []
            if world is None:
                raise PosteriorUnavailable(reason or "determinization_failed")
            if PublicSnapshot.from_view(world.protagonist_team_view()) != PublicSnapshot.from_view(view):
                raise PosteriorUnavailable("reconstructed_snapshot_mismatch")
            # Presentation text is not a rule field. Preserve the actually
            # received public text after the structured snapshot was checked.
            world.state.events = deepcopy(list(view.get("events", ())))
            roots.append((label, item.mass, world))
            if not exact:
                approximated += item.mass
        except (RuleError, PosteriorUnavailable) as error:
            failed += item.mass
            failures.append((label, item.mass, str(error)))
    return RootSelection(tuple(roots), selection, failed, approximated, tuple(failures))
