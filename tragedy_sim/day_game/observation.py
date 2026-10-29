"""Public observation snapshots for cross-day belief updates.

A branch is defined only by the protagonist team view. Hidden worlds that
produce the same public observation share the branch key and can be merged by
the search layer; witness and evidence state is rebuilt from the public view.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..belief import PublicEvidence
from ..witness import FsbtxWitnessCompiler, PublicEvidenceLedger
from .transition import DayTransitionResult, observation_branch_key


@dataclass(frozen=True)
class ObservationBranch:
    branch_key: str
    position: tuple[int, int]
    public_view: Mapping[str, Any]
    evidence: PublicEvidence
    witnesses: tuple[Any, ...]
    terminal: str

    def to_dict(self):
        return {
            "branch_key": self.branch_key,
            "position": list(self.position),
            "terminal": self.terminal,
            "witnesses": len(self.witnesses),
        }


def make_observation_branch(result: DayTransitionResult, *,
                            compiler: FsbtxWitnessCompiler | None = None,
                            ledger: PublicEvidenceLedger | None = None
                            ) -> ObservationBranch | None:
    """Build a fresh branch snapshot; callers should pass one ledger per branch."""
    view = result.public_view
    if view is None:
        return None
    compiler = compiler or FsbtxWitnessCompiler()
    ledger = ledger or PublicEvidenceLedger()
    evidence = PublicEvidence.from_view(view)
    witnesses = ledger.update(view, compiler)
    return ObservationBranch(
        branch_key=observation_branch_key(view) or "no_public_view",
        position=result.end_position,
        public_view=dict(view),
        evidence=evidence,
        witnesses=tuple(witnesses),
        terminal=result.terminal,
    )


def group_observation_snapshots(branches):
    """Merge branches with the same public observation; hidden worlds may differ."""
    grouped: dict[str, list[ObservationBranch]] = {}
    for branch in branches:
        grouped.setdefault(branch.branch_key, []).append(branch)
    return {key: tuple(items) for key, items in grouped.items()}


def resample_branch(branch: ObservationBranch, *,
                    information_policy=None,
                    particle_count: int | None = None,
                    rng_seed: int = 0,
                    budget=None):
    """Rebuild a particle snapshot from one public observation branch.

    ``information_policy`` must implement ``build``. The default is the
    public-particle policy; callers can substitute an oracle policy for
    diagnostics. ``particle_count=None`` keeps the production policy default
    so a branch snapshot does not silently use a different sample size.
    Hidden states are never read from the original transition.
    """
    if information_policy is None:
        from ..composition import ParticleInformationPolicy
        options = {"budget": budget, "rng_seed": rng_seed}
        if particle_count is not None:
            options["particle_count"] = particle_count
        information_policy = ParticleInformationPolicy(**options)
    return information_policy.build(game=None, view=branch.public_view, offers=())

