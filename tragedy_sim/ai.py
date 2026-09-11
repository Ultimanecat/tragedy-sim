"""Pluggable participant policies built on public service contracts."""

from __future__ import annotations

import random
from typing import Any, Protocol, Sequence


class AgentPolicy(Protocol):
    """Choose one server-provided action from a participant's observation."""

    def choose_action(self, *, participant: str, view: dict[str, Any],
                      offers: Sequence[dict[str, Any]]) -> dict[str, Any]: ...


class RandomAgent:
    """Baseline agent that samples uniformly from currently legal actions."""

    def __init__(self, rng: random.Random | random.SystemRandom | None = None):
        self._rng = rng or random.SystemRandom()

    def choose_action(self, *, participant: str, view: dict[str, Any],
                      offers: Sequence[dict[str, Any]]) -> dict[str, Any]:
        del participant, view
        if not offers:
            raise ValueError("cannot choose from an empty action list")
        return self._rng.choice(offers)
