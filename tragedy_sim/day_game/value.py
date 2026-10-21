"""Independent continuation-value interface for day-boundary leaves.

T1 separates the boundary utility from the exact day game. The day solver
keeps owning rules, legal actions, information sets and search; an evaluator
only maps a boundary context to a bounded whole-game value estimate. A point
estimate is never treated as a proof: only ``certified`` values may close a
certificate, and uncertified estimates fall back to ``[0,1]`` unknown leaves.
"""

from dataclasses import dataclass
from fractions import Fraction as Q
import math
import random
from typing import Protocol

from .continuation import day_boundary_value


@dataclass(frozen=True)
class BoundaryContext:
    """What a continuation evaluator may see at a day boundary.

    ``world`` is the concrete rule state in the current diagnostic model. Fair
    use must pass an authorized context; this interface does not grant extra
    information by itself.
    """

    world: object
    position: tuple[int, int]
    remaining_loops: int
    remaining_days: int
    utility_version: str = "day-survival-v1"
    scope: str = "known-world"

    def __post_init__(self):
        if (not isinstance(self.position, tuple) or len(self.position) != 2
                or any(type(value) is not int or value < 1 for value in self.position)):
            raise ValueError("boundary position must be a positive (loop, day) pair")
        for name in ("remaining_loops", "remaining_days"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(name + " must be a nonnegative integer")
        for name in ("utility_version", "scope"):
            if type(getattr(self, name)) is not str or not getattr(self, name):
                raise ValueError(name + " must be a nonempty string")


@dataclass(frozen=True)
class ValueEstimate:
    lower: Q
    upper: Q
    certified: bool
    scope: str
    version: str

    def __post_init__(self):
        if type(self.lower) is not Q or type(self.upper) is not Q:
            raise ValueError("value estimates must use exact fractions")
        if not (Q(0) <= self.lower <= self.upper <= Q(1)):
            raise ValueError("value estimate must satisfy 0 <= lower <= upper <= 1")
        if type(self.certified) is not bool:
            raise ValueError("certified must be a bool")
        for name in ("scope", "version"):
            if type(getattr(self, name)) is not str or not getattr(self, name):
                raise ValueError(name + " must be a nonempty string")

    @property
    def exact(self):
        return self.lower == self.upper

    @property
    def constant(self):
        return self.lower if self.certified and self.exact else None


class ContinuationEvaluator(Protocol):
    version: str

    def evaluate(self, context: BoundaryContext) -> ValueEstimate:
        ...


def boundary_context(world, position, *, utility_version="day-survival-v1",
                     scope="known-world") -> BoundaryContext:
    """Build a context from the concrete game's script and current position."""
    if not isinstance(position, tuple) or len(position) != 2:
        raise ValueError("position must be a (loop, day) pair")
    scenario = getattr(world, "scenario", {})
    loops = int(scenario.get("loops", world.state.loop))
    days = int(scenario.get("days", world.state.round))
    return BoundaryContext(
        world=world,
        position=position,
        remaining_loops=max(0, loops - world.state.loop),
        remaining_days=max(0, days - world.state.round),
        utility_version=utility_version,
        scope=scope,
    )


class DaySurvivalEvaluator:
    """T0-compatible evaluator: exact day survival, no whole-game estimate."""

    version = "day-survival-v1"

    def evaluate(self, context: BoundaryContext) -> ValueEstimate:
        terminal = day_boundary_value(context.world, context.position)
        if terminal is None:
            raise ValueError("day-survival evaluator requires a day boundary")
        value = Q(int(terminal))
        return ValueEstimate(value, value, True, "known-world-day-survival", self.version)


class UnknownEvaluator:
    """Placeholder T1 evaluator: honest [0,1] unknown, never a proof."""

    version = "unknown-v1"

    def evaluate(self, context: BoundaryContext) -> ValueEstimate:
        return ValueEstimate(Q(0), Q(1), False, "unknown", self.version)


def _wilson(wins: int, total: int, z: float = 1.96):
    """Approximate 95% Wilson interval for a binomial win rate."""
    rate = wins / total
    denominator = 1 + z * z / total
    center = (rate + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def _fraction(value: float) -> Q:
    return Q(value).limit_denominator(100000)


class RandomRolloutEvaluator:
    """Uncalibrated known-world baseline: random legal playouts to game end.

    This is a diagnostic leaf value for T1 experiments. It is never certified,
    so it cannot close a day-game certificate. Fair/team use would leak hidden
    state through the concrete world and is rejected.
    """

    version = "random-rollout-v1"

    def __init__(self, *, rollouts=8, max_steps=4096, seed=0):
        for name, value in (("rollouts", rollouts), ("max_steps", max_steps)):
            if type(value) is not int or value < 1:
                raise ValueError(name + " must be a positive integer")
        if type(seed) is not int:
            raise ValueError("seed must be an integer")
        self.rollouts, self.max_steps, self.seed = rollouts, max_steps, seed

    def evaluate(self, context: BoundaryContext) -> ValueEstimate:
        if context.scope != "known-world":
            raise ValueError("random rollouts require an explicit known-world context")
        world = context.world
        winner = getattr(world, "winner", None)
        if winner is not None:
            value = Q(1 if winner == "protagonists" else 0)
            return ValueEstimate(value, value, True, "known-world-terminal", self.version)
        if not callable(getattr(world, "clone", None)):
            raise ValueError("random rollouts require an FS rule state")
        wins = unfinished = 0
        for index in range(self.rollouts):
            rng = random.Random(self.seed + index)
            game = world.clone()
            for _ in range(self.max_steps):
                if game.winner is not None:
                    break
                actor = game.controller
                actions = game.legal_actions(actor)
                if not actions:
                    break
                game = game.transition(rng.choice(actions)).game
            if game.winner == "protagonists":
                wins += 1
            elif game.winner is None:
                unfinished += 1
        if unfinished:
            return ValueEstimate(Q(0), Q(1), False, "known-world-random-rollout", self.version)
        lower, upper = _wilson(wins, self.rollouts)
        return ValueEstimate(_fraction(lower), _fraction(upper), False,
                             "known-world-random-rollout", self.version)
