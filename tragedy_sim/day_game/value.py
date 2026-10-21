"""Independent continuation-value interface for day-boundary leaves.

T1 separates the boundary utility from the exact day game. The day solver
keeps owning rules, legal actions, information sets and search; an evaluator
only maps a boundary context to a bounded whole-game value estimate. A point
estimate is never treated as a proof: only ``certified`` values may close a
certificate, and uncertified estimates fall back to ``[0,1]`` unknown leaves.
"""

from dataclasses import dataclass
from fractions import Fraction as Q
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
