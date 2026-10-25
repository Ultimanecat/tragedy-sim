"""Composable protagonist agents: information policy + action policy.

The interfaces are intentionally small. An information policy may cheat in a
diagnostic agent, but an action policy only sees the resulting snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import random
from typing import Any, Mapping, Protocol, Sequence

from .belief import (ConstraintBeliefSampler, FactorizedBeliefState,
                     PersistentBeliefState, PublicEvidence)
from .belief_planner import PublicStateDeterminizer
from .game import Game
from .search import SearchBudget
from .witness import FsbtxWitnessCompiler, FsbtxWitnessMatcher, PublicEvidenceLedger


def _sampling_hash(view: Mapping[str, Any]) -> str:
    sampling_view = dict(view)
    for field in ("scenario_id", "title", "loops", "language",
                  "phase_name", "timepoint", "module_name", "labels"):
        sampling_view.pop(field, None)
    sampling_view["events"] = [
        {key: value for key, value in event.items()
         if key not in {"message", "timepoint", "remaining"}}
        for event in view.get("events", ())
    ]
    return hashlib.sha256(json.dumps(
        sampling_view, sort_keys=True, ensure_ascii=False, default=str
    ).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class BeliefSnapshot:
    """Frozen belief handed from an information policy to an action policy."""

    worlds: tuple[Game, ...]
    evidence: PublicEvidence
    witnesses: tuple[Any, ...] = ()
    known_roles: Mapping[str, str] = field(default_factory=dict)
    known_culprits: Mapping[int, str] = field(default_factory=dict)
    source: str = "public_particles"
    reason: str | None = None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


class InformationPolicy(Protocol):
    def build(self, *, game: Game | None, view: Mapping[str, Any],
              offers: Sequence[Mapping[str, Any]]) -> BeliefSnapshot | None:
        ...


class ActionPolicy(Protocol):
    def choose(self, *, snapshot: BeliefSnapshot, view: Mapping[str, Any],
               offers: Sequence[Mapping[str, Any]], participant: str) -> dict[str, Any]:
        ...


class ComposedProtagonistAgent:
    """Wire an information policy to an action policy."""

    controls_protagonist_team = True
    uses_public_view = True

    def __init__(self, information: InformationPolicy, action: ActionPolicy):
        self.information = information
        self.action = action

    def choose_action(self, *, participant: str, view: dict[str, Any],
                      offers: Sequence[dict[str, Any]]) -> dict[str, Any]:
        snapshot = self.information.build(game=None, view=view, offers=offers)
        if snapshot is None:
            raise RuntimeError("information policy produced no snapshot")
        return self.action.choose(snapshot=snapshot, view=view,
                                  offers=offers, participant=participant)


class ParticleInformationPolicy:
    """The existing public particle belief, extracted behind an interface."""

    def __init__(self, *, budget: SearchBudget | None = None, particle_count: int = 12,
                 rng_seed: int = 0, joint_witness: bool = True,
                 disabled_witness_sources: Sequence[str] = (),
                 matrix_proposals: bool = True,
                 matrix_variant_policy: str = "prior",
                 joint_culprits: bool = True,
                 role_sampling_policy: str = "importance",
                 role_partition_node_limit: int = 100_000,
                 action_role_sampling_policy: str = "iid",
                 information_policy: str = "public",
                 true_roles: Mapping[str, str] | None = None,
                 true_incidents: Mapping[int, str] | None = None):
        if type(information_policy) is not str or information_policy not in {"public", "oracle"}:
            raise ValueError("information_policy must be public or oracle")
        self.information_policy = information_policy
        self.true_roles = dict(true_roles or {})
        self.true_incidents = {int(day): str(cid)
                               for day, cid in (true_incidents or {}).items()}
        self.budget = budget or SearchBudget(node_limit=24, rollout_depth=12)
        self.particle_count = particle_count
        self.rng_seed = rng_seed
        self.sampler = ConstraintBeliefSampler()
        self.compiler = FsbtxWitnessCompiler(
            include_joint=joint_witness,
            disabled_sources=disabled_witness_sources)
        self.matcher = FsbtxWitnessMatcher()
        self.evidence_ledger = PublicEvidenceLedger()
        self.determinizer = PublicStateDeterminizer()
        self.belief = PersistentBeliefState(
            max_particles=particle_count, seed=rng_seed)
        self.factorized_belief = FactorizedBeliefState(
            capacity=max(192, particle_count * 8), seed=rng_seed)
        self.factorized_belief.matrix_proposals_enabled = matrix_proposals
        self.factorized_belief.matrix_variant_policy = matrix_variant_policy
        self.factorized_belief.role_sampling_policy = role_sampling_policy
        self.factorized_belief.role_partition_node_limit = role_partition_node_limit
        self.factorized_belief.joint_culprits_enabled = joint_culprits
        self.factorized_belief.action_role_sampling_policy = action_role_sampling_policy

    def build(self, *, game: Game | None, view: Mapping[str, Any],
              offers: Sequence[Mapping[str, Any]]) -> BeliefSnapshot | None:
        evidence = PublicEvidence.from_view(view)
        witnesses = self.evidence_ledger.update(view, self.compiler)
        public_hash = _sampling_hash(view)
        rng = random.Random(f"{self.budget.seed}:{self.rng_seed}:{public_hash}")
        sampled = self.factorized_belief.sample(
            evidence, witnesses, self.particle_count, rng=rng)
        worlds = tuple(
            world for index, hypothesis in enumerate(sampled.worlds)
            if (world := self.determinizer.determinize(
                hypothesis, evidence, view, rng=rng,
                history_prior=True, force_history=index % 5 == 0,
                coherent_history=True)) is not None)
        if not worlds:
            return BeliefSnapshot((), evidence, tuple(witnesses),
                                  source="public_particles",
                                  reason=sampled.reason or "no_particles")
        known_roles = {}
        known_culprits = {}
        if self.information_policy == "oracle":
            known_roles = dict(self.true_roles)
            known_culprits = dict(self.true_incidents)
            if known_roles:
                for world in worlds:
                    world.roles = dict(known_roles)
        return BeliefSnapshot(worlds, evidence, tuple(witnesses),
                              known_roles=known_roles,
                              known_culprits=known_culprits,
                              source=("oracle" if self.information_policy == "oracle"
                                      else "public_particles"),
                              diagnostics={"particles": len(worlds),
                                           "reason": sampled.reason,
                                           "role_candidates": sampled.role_candidates,
                                           "culprit_options": sampled.culprit_options})
