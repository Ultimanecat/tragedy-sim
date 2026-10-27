"""State-returning day-boundary transition for cross-day planning.

The engine already returns successor states. This module packages the
"advance one day and keep the resulting state" step so a cross-day search can
branch on it instead of receiving only a scalar value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

from ..game import Game


@dataclass(frozen=True)
class DayTransitionResult:
    state: Game
    start_position: tuple[int, int]
    end_position: tuple[int, int]
    commands: tuple[dict[str, Any], ...]
    new_events: tuple[dict[str, Any], ...]
    terminal: str
    stop_reason: str | None
    elapsed_seconds: float
    policy_name: str = "caller"

    @property
    def next_day(self) -> bool:
        return self.terminal == "survived_day"

    @property
    def lost(self) -> bool:
        return self.terminal in {"loop_end", "loop_lost", "final_guess",
                                 "mastermind_win"}


Policy = Callable[[Game, Sequence[Mapping[str, Any]]], Mapping[str, Any] | None]


def _first_legal(game: Game, actions: Sequence[Mapping[str, Any]]):
    return actions[0] if actions else None


def _boundary_terminal(game: Game, start_loop: int, start_round: int) -> str | None:
    if game.winner == "protagonists":
        return "protagonist_win"
    if game.winner == "mastermind":
        return "mastermind_win"
    if game.state.phase == "final_guess":
        return "final_guess"
    if game.state.phase == "loop_end":
        return "loop_end"
    if game.state.loop != start_loop:
        return "loop_lost"
    if game.state.round != start_round:
        return "survived_day"
    return None


def advance_day_with_plans(world: Game, black_plan: Sequence[Mapping[str, Any]],
                           red_plan: Sequence[Mapping[str, Any]], *,
                           fallback: Policy | None = None,
                           max_commands: int = 2048) -> DayTransitionResult:
    """Advance one day while forcing the supplied card placements.

    This is the first cross-day building block: black and red day plans are
    explicit, and every other decision falls back to a caller policy. It is a
    known-world transition; information-set branching belongs to the search
    layer above it.
    """
    remaining_black = [dict(command) for command in black_plan]
    remaining_red = [dict(command) for command in red_plan]
    fallback = fallback or _first_legal

    def policy(game: Game, actions: Sequence[Mapping[str, Any]]):
        phase = game.state.phase
        queue = (remaining_black if phase == "mastermind"
                 else remaining_red if phase == "protagonists" else None)
        if queue:
            command = queue[0]
            if command not in actions:
                raise ValueError(f"day plan command is not legal in {phase}: {command}")
            queue.pop(0)
            return command
        return fallback(game, actions)

    return advance_to_day_boundary(world, policy, max_commands=max_commands,
                                   policy_name="day_plans")


@dataclass(frozen=True)
class TwoDayTransitionResult:
    first: DayTransitionResult
    second: DayTransitionResult | None
    survived_both: bool
    value: float
    value_source: str


def advance_two_days(world: Game,
                     first_black: Sequence[Mapping[str, Any]],
                     first_red: Sequence[Mapping[str, Any]],
                     second_black: Sequence[Mapping[str, Any]],
                     second_red: Sequence[Mapping[str, Any]], *,
                     fallback: Policy | None = None,
                     leaf_value: Callable[[Game], float] | None = None,
                     max_commands: int = 2048) -> TwoDayTransitionResult:
    """Run two day plans and return the intermediate and final states.

    ``leaf_value`` is the T1-style leaf function for the second boundary. If it
    is omitted, two-day survival is valued at 1 and any failed day at 0.
    """
    first = advance_day_with_plans(world, first_black, first_red,
                                   fallback=fallback, max_commands=max_commands)
    if not first.next_day:
        terminal = first.terminal
        value = 1.0 if terminal == "protagonist_win" else 0.0
        return TwoDayTransitionResult(first, None, False, value,
                                      f"first_day:{terminal}")
    second = advance_day_with_plans(first.state, second_black, second_red,
                                    fallback=fallback, max_commands=max_commands)
    if second.terminal == "protagonist_win":
        return TwoDayTransitionResult(first, second, True, 1.0, "protagonist_win")
    if second.terminal == "mastermind_win":
        return TwoDayTransitionResult(first, second, False, 0.0, "mastermind_win")
    if leaf_value is not None:
        return TwoDayTransitionResult(first, second, second.next_day,
                                      float(leaf_value(second.state)),
                                      "caller_leaf")
    return TwoDayTransitionResult(first, second, second.next_day,
                                  1.0 if second.next_day else 0.0,
                                  f"second_day:{second.terminal}")


def advance_to_day_boundary(world: Game, policy: Policy | None = None, *,
                            max_commands: int = 2048,
                            policy_name: str = "first_legal") -> DayTransitionResult:
    """Advance one day and return the next boundary state, not just a value.

    The caller owns information boundaries. This helper only follows legal
    engine transitions and reports the resulting concrete state.
    """
    if not isinstance(world, Game):
        raise ValueError("advance_to_day_boundary requires a Game")
    if type(max_commands) is not int or max_commands < 1:
        raise ValueError("max_commands must be a positive integer")
    policy = policy or _first_legal
    started = perf_counter()
    start_position = (world.state.loop, world.state.round)
    current = world
    commands: list[dict[str, Any]] = []
    new_events: list[dict[str, Any]] = []
    event_cursor = len(current.state.events)
    terminal = _boundary_terminal(current, *start_position)
    stop_reason = None
    while terminal is None:
        if len(commands) >= max_commands:
            stop_reason = "command_limit"
            break
        actor = current.controller
        actions = current.legal_actions(actor)
        if not actions:
            stop_reason = "no_legal_actions"
            break
        chosen = policy(current, actions)
        if chosen is None:
            stop_reason = "policy_stop"
            break
        command = dict(chosen)
        if command not in actions:
            stop_reason = "illegal_policy_action"
            break
        commands.append(command)
        previous_events = current.state.events
        current = current.transition(command).game
        events = current.state.events
        if len(events) >= event_cursor:
            new_events.extend(events[event_cursor:])
            event_cursor = len(events)
        else:
            # Search transitions may compact history; keep the transition's tail.
            new_events.extend(events)
            event_cursor = len(events)
        terminal = _boundary_terminal(current, *start_position)
    if terminal is None:
        terminal = "stopped"
    end_position = (current.state.loop, current.state.round)
    return DayTransitionResult(current, start_position, end_position,
                               tuple(commands), tuple(new_events), terminal,
                               stop_reason, perf_counter() - started, policy_name)
