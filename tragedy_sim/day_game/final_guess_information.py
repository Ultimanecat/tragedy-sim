"""Authorized final-guess information estimate for T1 continuation values.

This reads only the protagonist team view. It answers "if the final guess were
now, how concentrated is the best complete cast?" It is not a whole-game win
probability and never certifies a day-game value.
"""

from dataclasses import dataclass

from ..belief import PublicEvidence
from ..final_guess_probability import JointGuessProbabilitySolver
from ..witness import FsbtxWitnessCompiler


@dataclass(frozen=True)
class FinalGuessInformation:
    status: str
    probability: float | None
    support_count: int | None
    best_guess: tuple | None
    node_limit: int
    scope: str = "team-public-evidence"
    version: str = "final-guess-information-v1"

    @property
    def exact(self):
        return self.status == "exact"


def estimate_final_guess_information(world, *, node_limit=100_000) -> FinalGuessInformation:
    """Estimate the current best complete-cast guess probability from public facts."""
    if not getattr(getattr(world, "ruleset", None), "final_guess", False):
        raise ValueError("final guess information requires a ruleset with final guess")
    if type(node_limit) is not int or node_limit < 1:
        raise ValueError("node_limit must be a positive integer")
    view = world.protagonist_team_view()
    evidence = PublicEvidence.from_view(view)
    witnesses = FsbtxWitnessCompiler().compile(view)
    result = JointGuessProbabilitySolver(node_limit=node_limit).solve(evidence, witnesses)
    return FinalGuessInformation(result.status, result.best_guess_probability, result.support_count,
                                 result.best_guess, node_limit)
