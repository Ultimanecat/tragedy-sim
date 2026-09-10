"""Explicit definitions; importing a ruleset never registers callbacks."""

from ..catalog import MODULES
from ..effect_resolver import MATCH_EFFECT_HANDLERS
from ..phases import PHASE_RESOLVERS
from .base import RulesetDefinition
from .legacy import roles, abilities, incidents, cycle, knowledge, projection, setup
from .common import roles as basic_roles, abilities as basic_abilities, incidents as basic_incidents
from .common import cycle as basic_cycle, knowledge as basic_knowledge, projection as basic_projection, setup as basic_setup


from .legacy.scenario import validate_scenario as _validate
from .common.scenario import validate_scenario as _validate_basic


_OPERATIONS = {}
for module in (roles, abilities, incidents, cycle, knowledge, projection):
    if _OPERATIONS.keys() & module.OPERATIONS.keys():
        raise ValueError('Duplicate ruleset operation')
    _OPERATIONS.update(module.OPERATIONS)

RULESETS = {
    key: RulesetDefinition(key, _OPERATIONS, setup.initialize,
                           MATCH_EFFECT_HANDLERS, PHASE_RESOLVERS, _validate)
    for key in MODULES
}

_BASIC = {}
for module in (basic_roles, basic_abilities, basic_incidents, basic_cycle, basic_knowledge, basic_projection):
    _BASIC.update(module.OPERATIONS)
for key in ('FS', 'BTX'):
    RULESETS[key] = RulesetDefinition(key, _BASIC, basic_setup.initialize,
                                    MATCH_EFFECT_HANDLERS, PHASE_RESOLVERS, _validate_basic)


def get_ruleset(key):
    return RULESETS[key]
