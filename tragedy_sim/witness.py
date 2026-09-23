"""Rule-scoped public witnesses used to reject impossible hidden worlds.

Witness compilation accepts only a player projection.  Matchers deliberately
return UNKNOWN when a public phenomenon has multiple legal explanations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .catalog import CHARACTERS, REFUSAL
from .witness_components import components_for
from .witness_types import (PublicWitness, WitnessEvaluation,
                            WitnessStrength, WitnessVerdict)


@dataclass
class PublicEvidenceLedger:
    """Seat-private evidence dimension, independent from search accounting."""

    module: str = ""
    witnesses: tuple[PublicWitness, ...] = ()
    updates: int = 0

    def update(self, view: Mapping[str, Any],
               compiler: "FsbtxWitnessCompiler") -> tuple[PublicWitness, ...]:
        compiled = compiler.compile(view)
        module = str(view.get("module", ""))
        module_changed = self.module != module
        if module_changed:
            self.module = module
            self.witnesses = ()
            self.updates = 0
        if module_changed or compiled != self.witnesses:
            self.witnesses = compiled
            self.updates += 1
        return self.witnesses

    @property
    def hard_count(self) -> int:
        return sum(item.strength == WitnessStrength.HARD
                   for item in self.witnesses)

    @property
    def soft_count(self) -> int:
        return sum(item.strength == WitnessStrength.SOFT
                   for item in self.witnesses)


class RulesetWitnessCompiler:
    """Compile witnesses from the components registered for a ruleset."""

    modules = frozenset({"FS", "BTX"})

    def __init__(self, *, include_joint: bool = True,
                 disabled_sources: Iterable[str] = (),
                 disabled_components: Iterable[str] = ()):
        self.include_joint = bool(include_joint)
        self.disabled_sources = frozenset(str(item) for item in disabled_sources)
        self.disabled_components = frozenset(
            str(item) for item in disabled_components)

    @staticmethod
    def _hard_accepted_goodwill(view: Mapping[str, Any]) -> list[PublicWitness]:
        """Accepting a refusable ability excludes mandatory refusers.

        Older journals did not record whether the printed ability was
        unrefusable.  Missing metadata therefore stays UNKNOWN rather than
        retroactively turning an old replay into a hard identity claim.
        """
        result = []
        mandatory = tuple(sorted(
            role for role in ("cultist", "witch")
            if REFUSAL.get(role) == "mandatory"))
        for event in view.get("events", ()):
            if (event.get("kind") != "goodwill_accepted"
                    or event.get("unrefusable") is not False):
                continue
            source = event.get("source")
            if not isinstance(source, str):
                continue
            result.append(PublicWitness(
                "role_not_in", source, mandatory,
                int(event.get("loop", view.get("loop", 1))),
                int(event.get("round", view.get("round", 1))),
                str(event.get("timing", "protagonist_ability")),
                "public_refusable_goodwill_accepted"))
        return result

    @staticmethod
    def _hard_suicide_victims(view: Mapping[str, Any]) -> list[PublicWitness]:
        """A character killed by a successful Suicide is its culprit.

        The public schedule identifies the incident as Suicide, while its
        mandatory effect kills the culprit itself.  A prevention effect may
        leave no death to observe; in that case this compiler deliberately
        emits no negative inference.
        """
        events = tuple(view.get("events", ()))
        result: list[PublicWitness] = []
        for index, event in enumerate(events):
            if (event.get("kind") != "incident_status"
                    or event.get("incident") != "suicide"
                    or not bool(event.get("happened", False))):
                continue
            victim = None
            for follow in events[index + 1:]:
                kind = follow.get("kind")
                if kind in {"incident_status", "day_ended"}:
                    break
                if kind == "character_died":
                    target = follow.get("target")
                    if isinstance(target, str):
                        victim = ("part_timer" if target == "part_timer_question"
                                  else target)
                    break
                if kind == "incident_ended":
                    break
            if victim is None:
                continue
            result.append(PublicWitness(
                "culprit_is", str(int(event.get(
                    "round", view.get("round", 1)))), victim,
                int(event.get("loop", view.get("loop", 1))),
                int(event.get("round", view.get("round", 1))),
                "incident", "public_suicide_victim"))
        return result

    @staticmethod
    def _hard_direct_incident_culprits(
            view: Mapping[str, Any]) -> list[PublicWitness]:
        """Compile incident effects whose public target is the culprit itself.

        Missing moves its culprit. Only a positive effect log is used: a
        blocked move provides no negative identity information.
        """
        rules = {
            "missing": ("character_moved", ("target", "character"),
                        "public_missing_moved_culprit"),
        }
        events = tuple(view.get("events", ()))
        result: list[PublicWitness] = []
        for index, event in enumerate(events):
            rule = rules.get(str(event.get("incident")))
            if (event.get("kind") != "incident_status"
                    or not bool(event.get("happened", False))
                    or rule is None):
                continue
            effect_kind, target_fields, source = rule
            culprit = None
            for follow in events[index + 1:]:
                kind = follow.get("kind")
                if kind in {"incident_status", "incident_ended", "day_ended"}:
                    break
                if kind != effect_kind:
                    continue
                target = next((follow.get(field) for field in target_fields
                               if isinstance(follow.get(field), str)), None)
                if isinstance(target, str):
                    culprit = ("part_timer" if target == "part_timer_question"
                               else target)
                break
            if culprit is None:
                continue
            incident_day = int(event.get("round", view.get("round", 1)))
            result.append(PublicWitness(
                "culprit_is", str(incident_day), culprit,
                int(event.get("loop", view.get("loop", 1))), incident_day,
                "incident", source))
        return result

    @staticmethod
    def _hard_incident_effect_locations(
            view: Mapping[str, Any]) -> list[PublicWitness]:
        """Restrict culprits using effects that must target their location."""
        effect_kinds = {
            "murder": frozenset({"character_died", "death_prevented",
                                  "guard_spent", "death_replaced"}),
            "butterfly": frozenset({"counter_changed"}),
        }
        events = tuple(view.get("events", ()))
        result: list[PublicWitness] = []
        for index, event in enumerate(events):
            incident = str(event.get("incident"))
            allowed_effects = effect_kinds.get(incident)
            characters = event.get("characters")
            if (event.get("kind") != "incident_status"
                    or not bool(event.get("happened", False))
                    or allowed_effects is None
                    or not isinstance(characters, Mapping)):
                continue
            target = None
            for follow in events[index + 1:]:
                kind = follow.get("kind")
                if kind in {"incident_status", "incident_ended", "day_ended"}:
                    break
                if kind not in allowed_effects:
                    continue
                if kind == "death_replaced":
                    protected = follow.get("protected", ())
                    candidate = (protected[0] if isinstance(protected, list)
                                 and protected else None)
                else:
                    candidate = follow.get("target")
                if isinstance(candidate, str) and candidate in characters:
                    target = candidate
                break
            target_state = characters.get(target) if target is not None else None
            target_location = (target_state.get("location")
                               if isinstance(target_state, Mapping) else None)
            if not isinstance(target_location, str):
                continue
            candidates = tuple(sorted(
                ("part_timer" if cid == "part_timer_question" else str(cid))
                for cid, state in characters.items()
                if isinstance(state, Mapping)
                and state.get("location") == target_location
                and bool(state.get("present", False))
                and bool(state.get("alive", False))
                and not (incident == "murder" and cid == target)))
            if not candidates:
                continue
            incident_day = int(event.get("round", view.get("round", 1)))
            result.append(PublicWitness(
                "culprit_in", str(incident_day), candidates,
                int(event.get("loop", view.get("loop", 1))), incident_day,
                "incident", "public_incident_effect_location"))
        return result

    @staticmethod
    def _hard_ignored_intrigue_forbids(
            view: Mapping[str, Any]) -> list[PublicWitness]:
        """One uncancelled FI that lets intrigue through proves a Cultist.

        The Cultist chooses a location after movements resolve, so candidates
        are reconstructed from the public positions at the counter change.
        Boss is retained conservatively because its public territory can
        extend its ability location beyond its current square.
        """
        characters = view.get("characters", {})
        initial = {
            str(cid): str(item.get("initial_location", item.get("location", "")))
            for cid, item in characters.items()
        }
        locations = dict(initial)
        alive = {str(cid): bool(item.get("present", True))
                 for cid, item in characters.items()}
        ignored_targets: set[str] = set()
        result: list[PublicWitness] = []
        for event in view.get("events", ()):
            kind = event.get("kind")
            if kind == "loop_started":
                locations = dict(initial)
                alive = {str(cid): bool(item.get("present", True))
                         for cid, item in characters.items()}
                ignored_targets = set()
                continue
            if kind in {"character_moved", "character_replaced"}:
                target = event.get("character", event.get("target"))
                location = event.get("location")
                if isinstance(target, str) and isinstance(location, str):
                    locations[target] = location
                    alive[target] = True
                continue
            if kind == "character_died":
                target = event.get("target")
                if isinstance(target, str):
                    alive[target] = False
                continue
            if kind == "revived":
                target = event.get("target")
                if isinstance(target, str):
                    alive[target] = True
                continue
            if kind == "character_left":
                target = event.get("character")
                if isinstance(target, str):
                    alive[target] = False
                continue
            if kind == "cards_revealed":
                cards = event.get("cards", ())
                forbids = [item for item in cards
                           if item.get("card") == "fi"]
                intrigue_targets = {
                    str(item.get("target")) for item in cards
                    if item.get("card") in {"i1", "i2"}}
                ignored_targets = ({str(forbids[0].get("target"))}
                                   & intrigue_targets
                                   if len(forbids) == 1 else set())
                continue
            if kind == "actions_resolved":
                ignored_targets = set()
                continue
            target = event.get("target")
            if (kind != "counter_changed" or target not in ignored_targets
                    or event.get("counter") != "intrigue"
                    or not isinstance(event.get("before"), int)
                    or not isinstance(event.get("after"), int)
                    or event["after"] <= event["before"]):
                continue
            protected_location = (locations.get(str(target))
                                  if target in characters else str(target))
            candidates = tuple(sorted(
                cid for cid in characters if alive.get(str(cid), False)
                and (locations.get(str(cid)) == protected_location
                     or cid == "boss")))
            if candidates:
                result.append(PublicWitness(
                    "role_pressure", "cultist", {"candidates": candidates},
                    int(event.get("loop", view.get("loop", 1))),
                    int(event.get("round", view.get("round", 1))),
                    str(event.get("timing", "action_resolution")),
                    "public_intrigue_forbid_ignored"))
        return result

    @staticmethod
    def _hard_day_end_hero_deaths(
            view: Mapping[str, Any]) -> list[PublicWitness]:
        """FS/BTX day-end hero death is Killer or Lover, with public gates."""
        characters = view.get("characters", {})
        intrigue = {str(cid): 0 for cid in characters}
        paranoia = {str(cid): 0 for cid in characters}
        alive = {str(cid): bool(item.get("present", True))
                 for cid, item in characters.items()}
        result: list[PublicWitness] = []
        for event in view.get("events", ()):
            kind = event.get("kind")
            if kind == "loop_started":
                intrigue = {str(cid): 0 for cid in characters}
                paranoia = {str(cid): 0 for cid in characters}
                alive = {str(cid): bool(item.get("present", True))
                         for cid, item in characters.items()}
                continue
            if kind == "counter_changed":
                target = event.get("target")
                after = event.get("after")
                if isinstance(target, str) and isinstance(after, int):
                    if event.get("counter") == "intrigue" and target in intrigue:
                        intrigue[target] = after
                    elif event.get("counter") == "paranoia" and target in paranoia:
                        paranoia[target] = after
                continue
            if kind == "character_died":
                target = event.get("target")
                if isinstance(target, str):
                    alive[target] = False
                continue
            if kind in {"revived", "character_replaced"}:
                target = event.get("target", event.get("character"))
                if isinstance(target, str):
                    alive[target] = True
                continue
            if kind == "character_left":
                target = event.get("character")
                if isinstance(target, str):
                    alive[target] = False
                continue
            if kind != "heroes_died" or event.get("timing") != "day_end":
                continue
            routes = {
                "killer": tuple(sorted(
                    cid for cid in characters
                    if alive.get(str(cid), False) and intrigue[str(cid)] >= 4)),
                "lover": tuple(sorted(
                    cid for cid in characters if alive.get(str(cid), False)
                    and paranoia[str(cid)] >= 3 and intrigue[str(cid)] >= 1)),
            }
            routes = {role: candidates for role, candidates in routes.items()
                      if candidates}
            if routes:
                result.append(PublicWitness(
                    "role_route_pressure", "day_end_hero_death", routes,
                    int(event.get("loop", view.get("loop", 1))),
                    int(event.get("round", view.get("round", 1))),
                    "day_end", "public_day_end_hero_death"))
        return result

    @staticmethod
    def _hard_btx_immediate_death_losses(
            view: Mapping[str, Any]) -> list[PublicWitness]:
        """A BTX loss immediately following deaths proves a Key ability."""
        if view.get("module") != "BTX":
            return []
        events = view.get("events", ())
        city_intrigue = 0
        result: list[PublicWitness] = []
        for index, event in enumerate(events):
            if event.get("kind") == "loop_started":
                city_intrigue = 0
                continue
            if (event.get("kind") == "counter_changed"
                    and event.get("target") == "city"
                    and event.get("counter") == "intrigue"
                    and isinstance(event.get("after"), int)):
                city_intrigue = event["after"]
                continue
            if event.get("kind") != "loop_lost":
                continue
            victims: list[str] = []
            cursor = index - 1
            while cursor >= 0:
                previous = events[cursor]
                if (previous.get("loop") != event.get("loop")
                        or previous.get("round") != event.get("round")):
                    break
                kind = previous.get("kind")
                if kind == "character_died":
                    target = previous.get("target")
                    if isinstance(target, str):
                        victims.append(target)
                elif kind not in {"incident_ended", "role_revealed"}:
                    break
                cursor -= 1
            if not victims:
                continue
            routes: dict[str, tuple[str, ...]] = {
                "key": tuple(sorted(set(victims))),
            }
            if city_intrigue >= 2:
                routes["factor"] = tuple(sorted(set(victims)))
            result.append(PublicWitness(
                "role_route_pressure", "immediate_death_loss", routes,
                int(event.get("loop", view.get("loop", 1))),
                int(event.get("round", view.get("round", 1))),
                str(event.get("timing", "loop_end")),
                "public_btx_immediate_death_loss"))
        return result

    @staticmethod
    def _soft_death_witnesses(view: Mapping[str, Any]) -> list[PublicWitness]:
        """Reconstruct death clues from the public journal.

        Ambiguous causes remain soft. FS lone-companion deaths with low
        intrigue have a unique day-end role explanation and can be hard.
        """
        characters = view.get("characters", {})
        initial = {
            str(cid): str(character.get("initial_location", character.get("location", "")))
            for cid, character in characters.items()
        }
        locations = dict(initial)
        intrigue = {str(cid): 0 for cid in characters}
        paranoia = {str(cid): 0 for cid in characters}
        virus_eligible: set[str] = set()
        city_intrigue = 0
        alive = {str(cid) for cid, character in characters.items()
                 if bool(character.get("present", True))}
        deaths_by_loop: dict[int, list[
            tuple[str, tuple[str, ...], int, bool]]] = {}
        result: list[PublicWitness] = []
        for event in view.get("events", ()):
            kind = event.get("kind")
            event_loop = int(event.get("loop", view.get("loop", 1)))
            event_day = int(event.get("round", view.get("round", 1)))
            if kind == "loop_started":
                locations = dict(initial)
                intrigue = {str(cid): 0 for cid in characters}
                paranoia = {str(cid): 0 for cid in characters}
                virus_eligible = set()
                city_intrigue = 0
                alive = {str(cid) for cid, character in characters.items()
                         if bool(character.get("present", True))}
                continue
            if kind == "counter_changed":
                target = event.get("target")
                counter = event.get("counter")
                after = event.get("after")
                if isinstance(target, str) and isinstance(after, int):
                    if counter == "intrigue" and target in intrigue:
                        intrigue[target] = after
                    elif counter == "intrigue" and target == "city":
                        city_intrigue = after
                    elif counter == "paranoia" and target in paranoia:
                        paranoia[target] = after
                        if after >= 3:
                            virus_eligible.add(target)
                continue
            if kind == "character_moved":
                target = event.get("character", event.get("target"))
                destination = event.get("location")
                if isinstance(target, str) and isinstance(destination, str):
                    locations[target] = destination
                continue
            if kind == "character_died":
                victim = event.get("target")
                if not isinstance(victim, str):
                    continue
                companions = tuple(sorted(
                    cid for cid in alive if cid != victim
                    and locations.get(cid) == locations.get(victim)))
                deaths_by_loop.setdefault(event_loop, []).append(
                    (victim, companions, event_day, city_intrigue >= 2))
                if event.get("timing") == "day_end":
                    if len(companions) == 1:
                        if (view.get("module") == "FS"
                                and victim != "part_timer"
                                and intrigue.get(victim, 0) < 2):
                            result.append(PublicWitness(
                                "role_is", companions[0], "serial",
                                event_loop, event_day, "day_end",
                                "fs_lone_companion_death"))
                        else:
                            result.append(PublicWitness(
                                "day_end_death_companion", victim, {
                                    "character": companions[0],
                                    "virus_eligible": companions[0] in virus_eligible,
                                },
                                event_loop, event_day, "day_end",
                                "public_death_and_location", WitnessStrength.SOFT))
                    if intrigue.get(victim, 0) >= 2:
                        for companion in companions:
                            result.append(PublicWitness(
                                "day_end_killer_candidate", victim, companion,
                                event_loop, event_day, "day_end",
                                "public_death_and_intrigue", WitnessStrength.SOFT))
                alive.discard(victim)
                continue
            if kind == "loop_lost":
                same_day = [(victim, companions, factor_key_possible)
                            for victim, companions, death_day, factor_key_possible
                            in deaths_by_loop.get(event_loop, ())
                            if death_day == event_day]
                for victim, companions, factor_key_possible in same_day:
                    result.append(PublicWitness(
                        "loss_after_death", victim,
                        {"companions": companions,
                         "factor_key_possible": factor_key_possible},
                        event_loop, event_day,
                        str(event.get("timing", "loop_end")),
                        "public_death_before_loop_loss", WitnessStrength.SOFT))
        return result

    @staticmethod
    def _soft_plot_pressure(view: Mapping[str, Any]) -> list[PublicWitness]:
        """Public loop-end conditions support, but cannot prove, a main plot."""
        module = view.get("module")
        if module not in {"FS", "BTX"}:
            return []
        school = 0
        shrine = 0
        butterfly_happened = False
        characters = view.get("characters", {})
        character_intrigue = {str(cid): 0 for cid in characters}
        character_goodwill = {str(cid): 0 for cid in characters}
        alive = {str(cid): bool(item.get("present", True))
                 for cid, item in characters.items()}
        initial_locations = {
            str(cid): str(item.get("initial_location", item.get("location", "")))
            for cid, item in characters.items()
        }
        location_intrigue = {location: 0 for location in
                             {"hospital", "shrine", "city", "school"}}
        events = view.get("events", ())
        result = []
        for index, event in enumerate(events):
            if event.get("kind") == "loop_started":
                school = 0
                shrine = 0
                butterfly_happened = False
                character_intrigue = {str(cid): 0 for cid in characters}
                character_goodwill = {str(cid): 0 for cid in characters}
                alive = {str(cid): bool(item.get("present", True))
                         for cid, item in characters.items()}
                location_intrigue = {location: 0 for location in
                                     location_intrigue}
            elif (event.get("kind") == "counter_changed"
                  and isinstance(event.get("after"), int)):
                target = str(event.get("target", ""))
                counter = event.get("counter")
                if counter == "intrigue":
                    if target in character_intrigue:
                        character_intrigue[target] = event["after"]
                    elif target in location_intrigue:
                        location_intrigue[target] = event["after"]
                    if target == "school":
                        school = event["after"]
                    elif target == "shrine":
                        shrine = event["after"]
                elif counter == "goodwill" and target in character_goodwill:
                    character_goodwill[target] = event["after"]
            elif event.get("kind") == "character_died":
                target = event.get("target")
                if isinstance(target, str):
                    alive[target] = False
            elif (event.get("kind") == "incident_status"
                  and event.get("incident") == "butterfly"
                  and event.get("happened")):
                butterfly_happened = True
            elif (event.get("kind") == "loop_lost" and index > 0
                  and ((events[index - 1].get("kind") == "day_ended"
                        and events[index - 1].get("loop") == event.get("loop"))
                       or any(
                           previous.get("kind") == "protagonists_lost"
                           and previous.get("loop") == event.get("loop")
                           and previous.get("round") == event.get("round")
                           and previous.get("timing") == "day_end"
                           for previous in events[:index]))):
                normal_loop_end = (
                    events[index - 1].get("kind") == "day_ended"
                    and events[index - 1].get("loop") == event.get("loop"))
                if normal_loop_end:
                    # No role_revealed event sits between day_ended and this
                    # loss, so a dead Friend did not cause this resolution.
                    # At least one main-plot loss predicate must therefore be
                    # true in every compatible hidden world.
                    result.append(PublicWitness(
                        "loop_end_plot_explanation", module, {
                            "location_intrigue": dict(location_intrigue),
                            "character_intrigue": dict(character_intrigue),
                            "initial_locations": dict(initial_locations),
                            "butterfly_happened": butterfly_happened,
                        }, int(event["loop"]), int(event["round"]),
                        "loop_end", "public_normal_loop_end_loss"))
                if module == "FS" and school >= 2:
                    result.append(PublicWitness(
                        "plot_pressure", "protect", True,
                        int(event["loop"]), int(event["round"]), "loop_end",
                        "public_school_pressure_and_loss", WitnessStrength.SOFT))
                if module == "BTX" and shrine >= 2:
                    result.append(PublicWitness(
                        "plot_pressure", "sealed", True,
                        int(event["loop"]), int(event["round"]), "loop_end",
                        "public_shrine_pressure_and_loss", WitnessStrength.SOFT))
                if module == "BTX" and butterfly_happened:
                    result.append(PublicWitness(
                        "plot_pressure", "change", True,
                        int(event["loop"]), int(event["round"]), "loop_end",
                        "public_butterfly_and_loss", WitnessStrength.SOFT))
                if module == "BTX":
                    sign_candidates = tuple(sorted(
                        cid for cid, value in character_intrigue.items()
                        if value >= 2))
                    if sign_candidates:
                        result.append(PublicWitness(
                            "joint_plot_role_pressure", "sign",
                            {"role": "key", "candidates": sign_candidates},
                            int(event["loop"]), int(event["round"]), "loop_end",
                            "public_character_intrigue_and_loss",
                            WitnessStrength.SOFT))
                    bomb_candidates = tuple(sorted(
                        cid for cid, location in initial_locations.items()
                        if location_intrigue.get(location, 0) >= 2))
                    if bomb_candidates:
                        # The board pressure itself supports Giant Time Bomb;
                        # the companion witness below preserves which initial
                        # characters could be its Witch.  Keep both soft: a
                        # different simultaneous route may have caused loss.
                        result.append(PublicWitness(
                            "plot_pressure", "bomb", True,
                            int(event["loop"]), int(event["round"]), "loop_end",
                            "public_initial_board_pressure_and_loss",
                            WitnessStrength.SOFT))
                        result.append(PublicWitness(
                            "joint_plot_role_pressure", "bomb",
                            {"role": "witch", "candidates": bomb_candidates},
                            int(event["loop"]), int(event["round"]), "loop_end",
                            "public_initial_board_intrigue_and_loss",
                            WitnessStrength.SOFT))
                    if int(event.get("round", 0)) == int(view.get("days", 0)):
                        declared_loss = any(
                            previous.get("kind") == "protagonists_lost"
                            and previous.get("loop") == event.get("loop")
                            and previous.get("round") == event.get("round")
                            and previous.get("timing") == "day_end"
                            for previous in events[:index])
                        traveler_candidates = tuple(sorted(
                            cid for cid, goodwill in character_goodwill.items()
                            if alive.get(cid, False) and goodwill < 3))
                        if traveler_candidates:
                            result.append(PublicWitness(
                                "role_pressure", "time_traveler",
                                {"candidates": traveler_candidates},
                                int(event["loop"]), int(event["round"]),
                                "loop_end", "public_final_day_low_goodwill_loss",
                                (WitnessStrength.HARD if declared_loss
                                 else WitnessStrength.SOFT)))
        return result

    def compile(self, view: Mapping[str, Any]) -> tuple[PublicWitness, ...]:
        module = str(view.get("module", ""))
        components = components_for(module)
        if not components:
            return ()
        result: list[PublicWitness] = []
        for component in components:
            if component.component_id in self.disabled_components:
                continue
            compile_component = (component.method if callable(component.method)
                                 else getattr(self, component.method))
            result.extend(compile_component(view))
        if not self.include_joint:
            result = [item for item in result
                      if item.kind != "joint_plot_role_pressure"
                      and not (item.kind == "role_pressure"
                               and item.strength == WitnessStrength.SOFT)]
        if self.disabled_sources:
            result = [item for item in result
                      if item.source not in self.disabled_sources]
        return tuple(result)


class FsbtxWitnessCompiler(RulesetWitnessCompiler):
    """Backward-compatible name for the original FS/BTX public API."""


class FsbtxWitnessMatcher:
    """Match an FS/BTX hidden setup without consulting the real game."""

    @staticmethod
    def _incident(hypothesis: Any, day: int) -> tuple[int, str, str, str] | None:
        return next((item for item in hypothesis.incidents if item[0] == day), None)

    def verdict(self, hypothesis: Any, witness: PublicWitness) -> WitnessVerdict:
        roles = dict(hypothesis.roles)
        if witness.kind == "role_is":
            subject = ("part_timer" if witness.subject == "part_timer_question"
                       else witness.subject)
            initial = roles.get(subject)
            plots = {hypothesis.main_plot, *hypothesis.subplots}
            compatible = initial == witness.value or (
                witness.value == "serial" and initial == "ordinary"
                and "virus" in plots)
            return (WitnessVerdict.SATISFIED if compatible
                    else WitnessVerdict.CONTRADICTED)
        if witness.kind == "role_in":
            subject = ("part_timer" if witness.subject == "part_timer_question"
                       else witness.subject)
            return (WitnessVerdict.SATISFIED
                    if roles.get(subject) in set(witness.value)
                    else WitnessVerdict.CONTRADICTED)
        if witness.kind == "role_not_in":
            subject = ("part_timer" if witness.subject == "part_timer_question"
                       else witness.subject)
            return (WitnessVerdict.CONTRADICTED
                    if roles.get(subject) in set(witness.value)
                    else WitnessVerdict.SATISFIED)
        if witness.kind == "culprit_is":
            incident = self._incident(hypothesis, int(witness.subject))
            if incident is None:
                return WitnessVerdict.CONTRADICTED
            return (WitnessVerdict.SATISFIED if incident[3] == witness.value
                    else WitnessVerdict.CONTRADICTED)
        if witness.kind == "culprit_in":
            incident = self._incident(hypothesis, int(witness.subject))
            if incident is None:
                return WitnessVerdict.CONTRADICTED
            return (WitnessVerdict.SATISFIED
                    if incident[3] in set(witness.value)
                    else WitnessVerdict.CONTRADICTED)
        if witness.kind == "plot_present":
            plots = {hypothesis.main_plot, *hypothesis.subplots}
            return (WitnessVerdict.SATISFIED if witness.subject in plots
                    else WitnessVerdict.CONTRADICTED)
        if witness.kind == "plot_not_present":
            plots = {hypothesis.main_plot, *hypothesis.subplots}
            return (WitnessVerdict.CONTRADICTED if witness.subject in plots
                    else WitnessVerdict.SATISFIED)
        if witness.kind == "plot_pressure":
            return (WitnessVerdict.SATISFIED
                    if hypothesis.main_plot == witness.subject
                    else WitnessVerdict.UNKNOWN)
        if witness.kind == "joint_plot_role_pressure":
            candidates = witness.value.get("candidates", ())
            role = witness.value.get("role")
            return (WitnessVerdict.SATISFIED
                    if hypothesis.main_plot == witness.subject
                    and any(roles.get(cid) == role for cid in candidates)
                    else WitnessVerdict.UNKNOWN)
        if witness.kind == "role_pressure":
            candidates = witness.value.get("candidates", ())
            return (WitnessVerdict.SATISFIED
                    if any(roles.get("part_timer" if cid == "part_timer_question"
                                     else cid) == witness.subject
                           for cid in candidates)
                    else (WitnessVerdict.CONTRADICTED
                          if witness.strength == WitnessStrength.HARD
                          else WitnessVerdict.UNKNOWN))
        if witness.kind == "role_route_pressure":
            for role, candidates in witness.value.items():
                if any(roles.get("part_timer" if cid == "part_timer_question"
                                 else cid) == role for cid in candidates):
                    return WitnessVerdict.SATISFIED
            return (WitnessVerdict.CONTRADICTED
                    if witness.strength == WitnessStrength.HARD
                    else WitnessVerdict.UNKNOWN)
        if witness.kind == "loop_end_plot_explanation":
            value = witness.value
            boards = value.get("location_intrigue", {})
            characters = value.get("character_intrigue", {})
            initial = value.get("initial_locations", {})

            def role_of(cid: str) -> str | None:
                return roles.get("part_timer" if cid == "part_timer_question"
                                 else cid)

            main = hypothesis.main_plot
            if witness.subject == "FS":
                explained = (
                    main == "protect" and boards.get("school", 0) >= 2
                    or main == "avenger" and any(
                        role_of(str(cid)) == "brain"
                        and boards.get(location, 0) >= 2
                        for cid, location in initial.items()))
            elif witness.subject == "BTX":
                explained = (
                    main == "sealed" and boards.get("shrine", 0) >= 2
                    or main == "sign" and any(
                        role_of(str(cid)) == "key" and intrigue >= 2
                        for cid, intrigue in characters.items())
                    or main == "change" and bool(
                        value.get("butterfly_happened"))
                    or main == "bomb" and any(
                        role_of(str(cid)) == "witch"
                        and boards.get(location, 0) >= 2
                        for cid, location in initial.items()))
            else:
                return WitnessVerdict.UNKNOWN
            return (WitnessVerdict.SATISFIED if explained
                    else WitnessVerdict.CONTRADICTED)
        if witness.kind == "incident_not_happened":
            # Absence has several explanations (dead/absent culprit and optional
            # prevention among them), so it is evidence but not a hard exclusion.
            incident = self._incident(hypothesis, int(witness.subject))
            characters = witness.value.get("characters")
            if incident is not None and characters:
                culprit = incident[3]
                observed = characters.get(culprit)
                definition = CHARACTERS.get(culprit)
                if (observed is not None and definition is not None
                        and observed.get("alive") and observed.get("present")):
                    score = observed["paranoia"]
                    if culprit == "ai":
                        score += (observed["goodwill"] + observed["intrigue"]
                                  + observed["guard"])
                    if score < definition.limit:
                        return WitnessVerdict.SATISFIED
            return WitnessVerdict.UNKNOWN
        if witness.kind == "incident_happened":
            incident = self._incident(hypothesis, int(witness.subject))
            if incident is None or incident[2] != witness.value["kind"]:
                return WitnessVerdict.CONTRADICTED
            characters = witness.value.get("characters")
            if not characters:
                return WitnessVerdict.UNKNOWN
            culprit = incident[3]
            if (culprit == "part_timer"
                    and not characters.get("part_timer", {}).get("alive", True)
                    and characters.get("part_timer_question", {}).get("present")):
                culprit = "part_timer_question"
            observed = characters.get(culprit)
            definition = CHARACTERS.get(culprit)
            if observed is None or definition is None:
                return WitnessVerdict.CONTRADICTED
            score = observed["paranoia"]
            if culprit == "ai":
                score = (observed["paranoia"] + observed["goodwill"]
                         + observed["intrigue"] + observed["guard"])
            return (WitnessVerdict.SATISFIED if score >= definition.limit
                    else WitnessVerdict.CONTRADICTED)
        if witness.kind == "day_end_death_companion":
            value = witness.value
            candidate = (str(value.get("character"))
                         if isinstance(value, Mapping) else str(value))
            virus_eligible = (bool(value.get("virus_eligible"))
                              if isinstance(value, Mapping) else False)
            plots = {hypothesis.main_plot, *hypothesis.subplots}
            return (WitnessVerdict.SATISFIED
                    if (roles.get(candidate) == "serial"
                        or (virus_eligible and roles.get(candidate) == "ordinary"
                            and "virus" in plots))
                    else WitnessVerdict.UNKNOWN)
        if witness.kind == "day_end_killer_candidate":
            return (WitnessVerdict.SATISFIED
                    if roles.get(witness.subject) == "key"
                    and roles.get(str(witness.value)) == "killer"
                    else WitnessVerdict.UNKNOWN)
        if witness.kind == "loss_after_death":
            return (WitnessVerdict.SATISFIED
                    if (roles.get(witness.subject) in {"key", "friend"}
                        or (roles.get(witness.subject) == "factor"
                            and witness.value.get("factor_key_possible", False)))
                    else WitnessVerdict.UNKNOWN)
        return WitnessVerdict.UNKNOWN

    def soft_score(self, hypothesis: Any,
                   witnesses: Sequence[PublicWitness]) -> float:
        weights = {"incident_not_happened": 0.75,
                   "plot_pressure": 3.0,
                   "joint_plot_role_pressure": 2.5,
                   "role_pressure": 1.5,
                   "day_end_death_companion": 4.0,
                   "day_end_killer_candidate": 1.5,
                   "loss_after_death": 2.0}
        by_kind: dict[str, float] = {}
        for witness in witnesses:
            if (witness.strength != WitnessStrength.SOFT
                    or self.verdict(hypothesis, witness) != WitnessVerdict.SATISFIED):
                continue
            by_kind[witness.kind] = by_kind.get(witness.kind, 0.0) \
                + weights.get(witness.kind, 0.5)
        # Repetition should increase confidence.  Causal day-end co-location
        # can become much stronger than the generic fact that a death preceded
        # a failed loop, while each channel remains bounded independently.
        caps = {"plot_pressure": 6.0,
                "day_end_death_companion": 8.0,
                "day_end_killer_candidate": 6.0,
                "loss_after_death": 4.0,
                "joint_plot_role_pressure": 6.0,
                "role_pressure": 4.0}
        return sum(min(caps.get(kind, 3.0), score)
                   for kind, score in by_kind.items())

    def evaluate(self, hypothesis: Any,
                 witnesses: Sequence[PublicWitness]) -> WitnessEvaluation:
        verdicts = tuple((witness, self.verdict(hypothesis, witness))
                         for witness in witnesses)
        compatible = not any(
            witness.strength == WitnessStrength.HARD
            and verdict == WitnessVerdict.CONTRADICTED
            for witness, verdict in verdicts)
        return WitnessEvaluation(compatible, verdicts)

    def matches(self, hypothesis: Any,
                witnesses: Sequence[PublicWitness]) -> bool:
        return self.evaluate(hypothesis, witnesses).compatible
