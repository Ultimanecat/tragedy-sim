"""Shared mechanics intentionally used by both introductory rulesets."""

from . import abilities, cycle, knowledge, projection, roles
from .. import characters


def operations(incident_module, plot_module):
    result = {}
    for module in (roles, abilities, cycle, knowledge, projection, characters,
                   incident_module, plot_module):
        collisions = result.keys() & module.OPERATIONS.keys()
        if collisions:
            raise ValueError("duplicate basic operation: " + ", ".join(sorted(collisions)))
        result.update(module.OPERATIONS)
    return result
