"""Composable witness-component registry.

The registry contains no rule implementation.  It describes which small
compiler component is active for each ruleset, preserving a stable order for
replays and deterministic AI seeds.  A future ruleset can reuse a component by
including the same spec in its tuple instead of copying compiler logic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WitnessComponentSpec:
    """One independently testable witness-producing rule family."""

    component_id: str
    method: str
    sources: frozenset[str]


def _component(component_id: str, method: str, *sources: str
               ) -> WitnessComponentSpec:
    return WitnessComponentSpec(component_id, method, frozenset(sources))


FS_KEY_DEATH = _component(
    "fs.key_death", "_hard_fs_key_deaths", "immediate_fs_death_loss")
GOODWILL_FORBID = _component(
    "btx.goodwill_forbid", "_hard_ignored_goodwill_forbids",
    "public_goodwill_forbid_ignored")
INTRIGUE_FORBID = _component(
    "common.intrigue_forbid", "_hard_ignored_intrigue_forbids",
    "public_intrigue_forbid_ignored")
DAY_END_HERO_DEATH = _component(
    "common.day_end_hero_death", "_hard_day_end_hero_deaths",
    "public_day_end_hero_death")
BTX_IMMEDIATE_DEATH = _component(
    "btx.immediate_death_loss", "_hard_btx_immediate_death_losses",
    "public_btx_immediate_death_loss")
ACCEPTED_GOODWILL = _component(
    "common.accepted_goodwill", "_hard_accepted_goodwill",
    "public_refusable_goodwill_accepted")
SUICIDE_VICTIM = _component(
    "common.suicide_victim", "_hard_suicide_victims",
    "public_suicide_victim")
DIRECT_INCIDENT_CULPRIT = _component(
    "common.direct_incident_culprit", "_hard_direct_incident_culprits",
    "public_missing_moved_culprit")
INCIDENT_EFFECT_LOCATION = _component(
    "common.incident_effect_location", "_hard_incident_effect_locations",
    "public_incident_effect_location")
PUBLIC_REVEALS = _component(
    "common.public_reveals", "_public_reveals",
    "public_role_reveal", "public_culprit_reveal", "public_plot_reveal")
GOODWILL_REFUSAL = _component(
    "common.goodwill_refusal", "_goodwill_refusals",
    "public_goodwill_refusal")
INCIDENT_STATUS = _component(
    "common.incident_status", "_incident_status_witnesses",
    "public_incident_status")
DEATH_CLUES = _component(
    "common.death_clues", "_soft_death_witnesses",
    "fs_lone_companion_death", "public_death_and_location",
    "public_death_and_intrigue", "public_death_before_loop_loss")
LOOP_END_CLUES = _component(
    "common.loop_end_clues", "_soft_plot_pressure",
    "public_normal_loop_end_loss", "public_school_pressure_and_loss",
    "public_shrine_pressure_and_loss", "public_butterfly_and_loss",
    "public_character_intrigue_and_loss",
    "public_initial_board_pressure_and_loss",
    "public_initial_board_intrigue_and_loss",
    "public_final_day_low_goodwill_loss")


COMMON_COMPONENTS = (
    INTRIGUE_FORBID,
    DAY_END_HERO_DEATH,
    ACCEPTED_GOODWILL,
    SUICIDE_VICTIM,
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
        INTRIGUE_FORBID,
        DAY_END_HERO_DEATH,
        ACCEPTED_GOODWILL,
        SUICIDE_VICTIM,
        DIRECT_INCIDENT_CULPRIT,
        INCIDENT_EFFECT_LOCATION,
        PUBLIC_REVEALS,
        GOODWILL_REFUSAL,
        INCIDENT_STATUS,
        DEATH_CLUES,
        LOOP_END_CLUES,
    ),
    "BTX": (
        GOODWILL_FORBID,
        INTRIGUE_FORBID,
        DAY_END_HERO_DEATH,
        BTX_IMMEDIATE_DEATH,
        ACCEPTED_GOODWILL,
        SUICIDE_VICTIM,
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
