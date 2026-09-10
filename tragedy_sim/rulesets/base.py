"""Definitions shared by every ruleset and simulation branch."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping


@dataclass(frozen=True)
class RulesetDefinition:
    id: str
    operations: Mapping[str, Callable]
    initialize: Callable
    effects: object
    phases: object
    validator: Callable
    final_guess: bool = False
    early_final_guess: bool = False

    def __post_init__(self):
        object.__setattr__(self, 'operations', MappingProxyType(dict(self.operations)))

    def __deepcopy__(self, memo):
        return self
