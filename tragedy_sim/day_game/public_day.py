"""Public-input end-to-end diagnostic; evidence work precedes action budget."""

from dataclasses import dataclass
from functools import reduce
from math import lcm
from time import perf_counter

from .bayesian import BayesianDoubleOracle
from .continuation import WorkLimit
from .engine_game import red_commands
from .posterior import PosteriorUnavailable, PublicWorldPosterior, reconstruct_public_roots
from .matrix import rational
from .zero_sum import SearchBudget


@dataclass(frozen=True)
class PublicDaySolve:
    posterior: object
    reconstruction: object
    model: object
    result: object
    evidence_elapsed_seconds: float
    action_elapsed_seconds: float
    stop_reason: str

    def sample_card_plan(self, rng):
        """Exact rational private draw, independent of every hidden world."""
        if self.result is None:
            return ()
        support = self.result.red
        denominator = reduce(lcm, (p.denominator for _, p in support), 1)
        draw = rng.randrange(denominator)
        for plan, probability in support:
            draw -= probability.numerator*(denominator//probability.denominator)
            if draw < 0:
                return red_commands(plan)
        raise RuntimeError("red policy does not have unit probability mass")


def solve_public_day(view, *, own_commands=(), world_limit=12, posterior_node_limit=100000,
                     allow_state_prior=False, backend="reference", max_depth=256, cache_capacity=100000,
                     node_limit=100000, time_limit_ms=10000, payoff_limit=100000,
                     epsilon="1/100", max_iterations=64, pivot_limit=100000, seed_plans=()):
    """No true Game/script input; returned models/traces remain server-private.

    Midgame snapshot reconstruction needs explicit allow_state_prior. It is
    then a declared prior model, never certified full hidden-state coverage.
    """
    for limit in (world_limit, posterior_node_limit, max_depth, cache_capacity,
                  node_limit, time_limit_ms, payoff_limit, max_iterations, pivot_limit):
        if type(limit) is not int or limit < 1:
            raise ValueError("all public-day budgets must be positive integers")
    if rational(epsilon) < 0 or type(allow_state_prior) is not bool or backend not in {"reference", "cached", "compiled"}:
        raise ValueError("invalid epsilon, reconstruction mode or backend")
    started = perf_counter()
    selection = reconstruction = model = None
    try:
        posterior = PublicWorldPosterior(view, node_limit=posterior_node_limit)
        selection = posterior.select(world_limit)
        reconstruction = reconstruct_public_roots(selection, view, own_commands=own_commands,
                                                   allow_state_prior=allow_state_prior)
        model = reconstruction.model(backend=backend, max_depth=max_depth, cache_capacity=cache_capacity)
    except PosteriorUnavailable as error:
        return PublicDaySolve(selection, reconstruction, None, None, perf_counter()-started, 0, str(error))
    oracle = BayesianDoubleOracle(model, seed_rows=tuple(model.blocks[0].game.plan(plan) for plan in seed_plans),
                                  payoff_cache_capacity=cache_capacity)
    evidence_elapsed = perf_counter()-started
    work = WorkLimit(node_limit=node_limit, time_limit_ms=time_limit_ms)
    result = oracle.solve(budget=SearchBudget(work=work, payoff_limit=payoff_limit), epsilon=epsilon,
                          max_iterations=max_iterations, pivot_limit=pivot_limit)
    return PublicDaySolve(selection, reconstruction, model, result, evidence_elapsed,
                          perf_counter()-work.started, result.stop_reason)
