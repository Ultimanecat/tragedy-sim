"""Complete, inspectable First Steps composition."""

from ...effect_resolver import BASIC_EFFECT_HANDLERS
from ...phases import PHASE_RESOLVERS
from ..base import RulesetDefinition
from ..common.definition import operations
from ..common.setup import initialize
from . import incidents, plots, scenario


DEFINITION = RulesetDefinition(
    "FS", operations(incidents, plots), initialize, BASIC_EFFECT_HANDLERS,
    PHASE_RESOLVERS, scenario.validate_scenario,
    final_guess=plots.FINAL_GUESS, early_final_guess=plots.EARLY_FINAL_GUESS,
)
