"""Execution decisions, separate from search traces and transport requests."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CardPlay:
    actor: str
    card: str
    target: str

    def payload(self) -> dict[str, str]:
        return {'actor': self.actor, 'card': self.card, 'target': self.target}


@dataclass(frozen=True)
class AiDecision:
    action: dict[str, Any]
    card_plan: tuple[CardPlay, ...] = ()


class JointCardDecisionProvider:
    """Adapt a selected action and its execution cache into a complete plan.

    The single-action API remains available to CLI and simulation callers.
    A plan is emitted only at its first card, never for a partial remainder.
    """

    def remaining_card_commands(self) -> tuple[dict[str, Any], ...]:
        raise NotImplementedError

    def clear_card_plan(self) -> None:
        raise NotImplementedError

    def decision_for_action(self, action: Mapping[str, Any]) -> AiDecision:
        copied = deepcopy(dict(action))
        if str(action.get('type', '')).removeprefix('core.') != 'play':
            return AiDecision(copied)
        remainder = self.remaining_card_commands()
        if len(remainder) != 2:
            return AiDecision(copied)
        commands = ({'actor': action['actor'], 'action': 'play',
                     **action['parameters']}, *remainder)
        if any(command.get('action') != 'play' for command in commands):
            raise ValueError('joint card plan contains a non-placement action')
        return AiDecision(copied, tuple(CardPlay(
            command['actor'], command['card'], command['target'])
            for command in commands))
