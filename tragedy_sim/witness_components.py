"""Composable witness-component registry.

The registry contains no rule implementation.  It describes which small
compiler component is active for each ruleset, preserving a stable order for
replays and deterministic AI seeds.  A future ruleset can reuse a component by
including the same spec in its tuple instead of copying compiler logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .witness_rules.btx_immediate_death import compile_immediate_death_losses
from .witness_rules.btx_love import compile_love_death_reactions
from .witness_rules.btx_threads import compile_threads_at_loop_start
from .witness_rules.btx_time_traveler import (
    compile_death_prevention, compile_ignored_goodwill_forbids)
from .witness_rules.btx_virus import compile_virus_reveal_thresholds
from .witness_rules.common_day_end import compile_hero_deaths
from .witness_rules.common_death_clues import compile_death_clues
from .witness_rules.common_incidents import (
    compile_direct_culprits, compile_effect_locations,
    compile_effective_incidents, compile_guru_incidents,
    compile_suicide_prevented_targets, compile_suicide_victims)
from .witness_rules.common_intrigue import compile_ignored_intrigue_forbids
from .witness_rules.common_loop_end import compile_loop_end_clues
from .witness_rules.common_mastermind_abilities import (
    compile_mastermind_counter_sources)
from .witness_rules.common_public import (compile_accepted_goodwill,
                                          compile_goodwill_refusals,
                                          compile_incident_status,
                                          compile_public_reveals)
from .witness_rules.fs_key_death import compile_key_deaths
from .witness_types import PublicWitness


WitnessCompiler = Callable[[Mapping[str, Any]], list[PublicWitness]]


@dataclass(frozen=True)
class WitnessComponentSpec:
    """One independently testable witness-producing rule family."""

    component_id: str
    compile: WitnessCompiler
    sources: frozenset[str]


def _component(component_id: str, compile: WitnessCompiler, *sources: str
               ) -> WitnessComponentSpec:
    return WitnessComponentSpec(component_id, compile, frozenset(sources))


FS_KEY_DEATH = _component(
    "fs.key_death", compile_key_deaths, "immediate_fs_death_loss")
GOODWILL_FORBID = _component(
    "btx.goodwill_forbid", compile_ignored_goodwill_forbids,
    "public_goodwill_forbid_ignored")
TIME_TRAVELER_DEATH_PREVENTION = _component(
    "btx.time_traveler_death_prevention",
    compile_death_prevention,
    "public_time_traveler_death_prevention")
VIRUS_REVEAL_THRESHOLDS = _component(
    "btx.virus_reveal_thresholds", compile_virus_reveal_thresholds,
    "public_virus_serial_without_threshold",
    "public_ordinary_after_virus_threshold")
THREADS_LOOP_START = _component(
    "btx.threads_loop_start", compile_threads_at_loop_start,
    "public_threads_loop_start_paranoia")
LOVE_DEATH_REACTION = _component(
    "btx.love_death_reaction", compile_love_death_reactions,
    "public_love_death_reaction")
MASTERMIND_COUNTER_SOURCES = _component(
    "common.mastermind_counter_sources", compile_mastermind_counter_sources,
    "public_mastermind_intrigue_source",
    "public_mastermind_paranoia_source")
INTRIGUE_FORBID = _component(
    "common.intrigue_forbid", compile_ignored_intrigue_forbids,
    "public_intrigue_forbid_ignored")
DAY_END_HERO_DEATH = _component(
    "common.day_end_hero_death", compile_hero_deaths,
    "public_day_end_hero_death")
BTX_IMMEDIATE_DEATH = _component(
    "btx.immediate_death_loss", compile_immediate_death_losses,
    "public_btx_immediate_death_loss")
ACCEPTED_GOODWILL = _component(
    "common.accepted_goodwill", compile_accepted_goodwill,
    "public_refusable_goodwill_accepted")
SUICIDE_VICTIM = _component(
    "common.suicide_victim", compile_suicide_victims,
    "public_suicide_victim")
SUICIDE_PREVENTED = _component(
    "common.suicide_prevented", compile_suicide_prevented_targets,
    "public_suicide_prevented_target")
GURU_INCIDENT = _component(
    "common.guru_incident", compile_guru_incidents,
    "public_guru_incident_doubled")
EFFECTIVE_INCIDENT = _component(
    "common.effective_incident", compile_effective_incidents,
    "public_effective_incident_excludes_black_cat")
DIRECT_INCIDENT_CULPRIT = _component(
    "common.direct_incident_culprit", compile_direct_culprits,
    "public_missing_moved_culprit")
INCIDENT_EFFECT_LOCATION = _component(
    "common.incident_effect_location", compile_effect_locations,
    "public_incident_effect_location")
PUBLIC_REVEALS = _component(
    "common.public_reveals", compile_public_reveals,
    "public_role_reveal", "public_culprit_reveal", "public_plot_reveal")
GOODWILL_REFUSAL = _component(
    "common.goodwill_refusal", compile_goodwill_refusals,
    "public_goodwill_refusal")
INCIDENT_STATUS = _component(
    "common.incident_status", compile_incident_status,
    "public_incident_status")
DEATH_CLUES = _component(
    "common.death_clues", compile_death_clues,
    "fs_lone_companion_death", "public_death_and_location",
    "public_death_and_intrigue", "public_death_before_loop_loss")
LOOP_END_CLUES = _component(
    "common.loop_end_clues", compile_loop_end_clues,
    "public_normal_loop_end_loss", "public_school_pressure_and_loss",
    "public_shrine_pressure_and_loss", "public_butterfly_and_loss",
    "public_character_intrigue_and_loss",
    "public_initial_board_pressure_and_loss",
    "public_initial_board_intrigue_and_loss",
    "public_final_day_low_goodwill_loss")


COMMON_COMPONENTS = (
    MASTERMIND_COUNTER_SOURCES,
    INTRIGUE_FORBID,
    DAY_END_HERO_DEATH,
    ACCEPTED_GOODWILL,
    SUICIDE_VICTIM,
    SUICIDE_PREVENTED,
    GURU_INCIDENT,
    EFFECTIVE_INCIDENT,
    DIRECT_INCIDENT_CULPRIT,
    INCIDENT_EFFECT_LOCATION,
    PUBLIC_REVEALS,
    GOODWILL_REFUSAL,
    INCIDENT_STATUS,
    DEATH_CLUES,
    LOOP_END_CLUES,
)

# Explicit tuples make activation auditable.  Their order matches the legacy
# monolithic compiler so componentization does not perturb deterministic runs.
RULESET_WITNESS_COMPONENTS = {
    "FS": (
        FS_KEY_DEATH,
        MASTERMIND_COUNTER_SOURCES,
        INTRIGUE_FORBID,
        DAY_END_HERO_DEATH,
        ACCEPTED_GOODWILL,
        SUICIDE_VICTIM,
        SUICIDE_PREVENTED,
        GURU_INCIDENT,
        EFFECTIVE_INCIDENT,
        DIRECT_INCIDENT_CULPRIT,
        INCIDENT_EFFECT_LOCATION,
        PUBLIC_REVEALS,
        GOODWILL_REFUSAL,
        INCIDENT_STATUS,
        DEATH_CLUES,
        LOOP_END_CLUES,
    ),
    "BTX": (
        MASTERMIND_COUNTER_SOURCES,
        GOODWILL_FORBID,
        TIME_TRAVELER_DEATH_PREVENTION,
        VIRUS_REVEAL_THRESHOLDS,
        THREADS_LOOP_START,
        LOVE_DEATH_REACTION,
        INTRIGUE_FORBID,
        DAY_END_HERO_DEATH,
        BTX_IMMEDIATE_DEATH,
        ACCEPTED_GOODWILL,
        SUICIDE_VICTIM,
        SUICIDE_PREVENTED,
        GURU_INCIDENT,
        EFFECTIVE_INCIDENT,
        DIRECT_INCIDENT_CULPRIT,
        INCIDENT_EFFECT_LOCATION,
        PUBLIC_REVEALS,
        GOODWILL_REFUSAL,
        INCIDENT_STATUS,
        DEATH_CLUES,
        LOOP_END_CLUES,
    ),
}


def components_for(module: str) -> tuple[WitnessComponentSpec, ...]:
    """Return the ordered witness components registered for a ruleset."""
    return RULESET_WITNESS_COMPONENTS.get(str(module), ())


def registered_sources(module: str) -> frozenset[str]:
    """Return every ablatable source declared by a ruleset's components."""
    return frozenset(source for component in components_for(module)
                     for source in component.sources)
