"""Explicit definitions; importing a ruleset never registers callbacks."""

from ..catalog import MODULES
from ..effect_resolver import MATCH_EFFECT_HANDLERS
from ..phases import PHASE_RESOLVERS
from .base import RulesetDefinition
from .legacy import roles, abilities, incidents, cycle, knowledge, projection, setup
from .fs import DEFINITION as FS_DEFINITION
from .btx import DEFINITION as BTX_DEFINITION


from .legacy.scenario import validate_scenario as _validate


_OPERATIONS = {}
for module in (roles, abilities, incidents, cycle, knowledge, projection):
    if _OPERATIONS.keys() & module.OPERATIONS.keys():
        raise ValueError('Duplicate ruleset operation')
    _OPERATIONS.update(module.OPERATIONS)

RULESETS = {
    key: RulesetDefinition(key, _OPERATIONS, setup.initialize,
                           MATCH_EFFECT_HANDLERS, PHASE_RESOLVERS, _validate,
                           final_guess=MODULES[key].final_guess,
                           early_final_guess=MODULES[key].early_final_guess)
    for key in MODULES
}

RULESETS["FS"] = FS_DEFINITION
RULESETS["BTX"] = BTX_DEFINITION


def get_ruleset(key):
    return RULESETS[key]
