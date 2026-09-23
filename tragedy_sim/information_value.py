"""Public-belief information potential used as a small day-plan tiebreaker."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence


INFORMATION_ABILITY_KINDS = frozenset({
    "reveal", "culprit", "culprit_any", "plot", "copycat_identify",
    "part_timer_reveal",
})


def _entropy(values: Sequence[Any], world_count: int) -> float:
    """Entropy normalized by the largest distinction this particle set permits."""
    if world_count <= 1 or not values:
        return 0.0
    counts = Counter(values)
    if len(counts) <= 1:
        return 0.0
    total = len(values)
    bits = -sum((count / total) * math.log2(count / total)
                for count in counts.values())
    return min(1.0, bits / math.log2(world_count))


@dataclass(frozen=True)
class InformationValueBreakdown:
    future_potential: float = 0.0
    realized_information: float = 0.0
    refusal_witness: float = 0.0
    threads_carryover_risk: float = 0.0

    @property
    def total(self) -> float:
        return min(1.2, self.future_potential + self.realized_information
                   + self.refusal_witness)


class InformationOpportunityEvaluator:
    """Estimate information value only from the shared public belief ensemble."""

    def __init__(self, worlds: Sequence[Any], root_view: Mapping[str, Any], *,
                 discount: float = 0.75,
                 threads_confirmed: bool = False):
        if not worlds:
            raise ValueError("information evaluator requires at least one world")
        self.worlds = tuple(worlds)
        self.root_view = root_view
        self.discount = discount
        self.threads_confirmed = threads_confirmed
        self.world_count = len(worlds)
        self._root_potential = self.potential(root_view)

    def _threads_carryover_risk(self, final_view: Mapping[str, Any]) -> float:
        """Price newly exposed characters, not extra goodwill on old targets.

        Threads triggers only after a lost loop, so this remains a small,
        discounted tie-breaker.  Dead characters still count at loop reset.
        """
        root = self.root_view
        if (not self.threads_confirmed or root.get("module") != "BTX"
                or int(root.get("loop", 1)) >= int(root.get("loops", 1))
                or final_view.get("loop") != root.get("loop")):
            return 0.0
        before = root.get("characters", {})
        after = final_view.get("characters", {})
        newly_exposed = sum(
            int(character.get("present", True)
                and int(character.get("goodwill", 0)) > 0
                and int(before.get(cid, {}).get("goodwill", 0)) == 0)
            for cid, character in after.items())
        days_until_reset = max(0, int(root.get("days", 1))
                               - int(root.get("round", 1)))
        return min(0.008, 0.004 * newly_exposed
                   * self.discount ** days_until_reset)

    @staticmethod
    def _known_roles(view: Mapping[str, Any]) -> set[str]:
        known = set(view.get("known_roles", {}))
        private = view.get("protagonist_knowledge", {}).get("roles", {})
        if isinstance(private, Mapping):
            known.update(str(cid) for cid in private)
        return known

    def _role_entropy(self, character: str) -> float:
        return _entropy(tuple(world.roles.get(character) for world in self.worlds),
                        self.world_count)

    def _culprit_entropy(self, day: int) -> float:
        values = []
        for world in self.worlds:
            values.append(next((item.get("culprit")
                                for item in world.scenario.get("incidents", ())
                                if int(item.get("day", -1)) == day), None))
        return _entropy(tuple(values), self.world_count)

    def _plot_entropy(self, known: set[str]) -> float:
        values = tuple(tuple(sorted(set(world.scenario.get("subplots", ())) - known))
                       for world in self.worlds)
        return _entropy(values, self.world_count)

    def _copycat_entropy(self, source: str) -> float:
        values = []
        for world in self.worlds:
            role = world.roles.get(source)
            matches = tuple(sorted(cid for cid, assigned in world.roles.items()
                                   if assigned == role
                                   and world.state.characters.get(cid) is not None
                                   and world.state.characters[cid].present))
            values.append((role, matches))
        return _entropy(tuple(values), self.world_count)

    @staticmethod
    def _living_characters(view: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
        return {str(cid): character
                for cid, character in view.get("characters", {}).items()
                if character.get("alive", True) and character.get("present", True)}

    def _reveal_targets(self, source: str, ability: Mapping[str, Any],
                        view: Mapping[str, Any]) -> tuple[str, ...]:
        living = self._living_characters(view)
        character = living.get(source)
        if character is None:
            return ()
        scope = str(ability.get("scope", "same"))
        if scope == "self":
            return (source,)
        if scope == "any_corpse":
            return tuple(str(cid) for cid, item in view.get("characters", {}).items()
                         if item.get("present", True) and not item.get("alive", True))
        if scope == "territory_other":
            territory = character.get("territory")
            return tuple(cid for cid, item in living.items()
                         if cid != source and item.get("location") == territory)
        same = tuple(cid for cid, item in living.items()
                     if cid != source
                     and item.get("location") == character.get("location"))
        if scope == "student":
            return tuple(cid for cid in same
                         if "student" in living[cid].get("traits", ()))
        if scope == "panicked_other":
            return tuple(cid for cid in same
                         if int(living[cid].get("paranoia", 0))
                         >= int(living[cid].get("paranoia_limit", 99)))
        return same

    def information_gain(self, source: str, ability: Mapping[str, Any],
                         view: Mapping[str, Any]) -> float:
        kind = str(ability.get("kind", ""))
        known_roles = self._known_roles(view)
        if kind == "reveal":
            targets = (target for target in self._reveal_targets(source, ability, view)
                       if target not in known_roles)
            return max((self._role_entropy(target) for target in targets),
                       default=0.0)
        if kind in {"culprit", "culprit_any"}:
            known = {int(day) for day in view.get("known_culprits", {})}
            if kind == "culprit":
                days = {int(item["day"]) for item in view.get("incidents", ())
                        if item.get("happened") and "day" in item}
            else:
                days = {int(item["day"]) for item in view.get("schedule", ())
                        if "day" in item}
            return max((self._culprit_entropy(day) for day in days - known),
                       default=0.0)
        if kind == "plot":
            return self._plot_entropy(set(view.get("known_plots", ())))
        if kind == "copycat_identify":
            groups = view.get("protagonist_knowledge", {}).get(
                "same_role_groups", {})
            if isinstance(groups, Mapping) and source in groups:
                return 0.0
            return self._copycat_entropy(source)
        if kind == "part_timer_reveal":
            return 0.0 if source in known_roles else self._role_entropy(source)
        return 0.0

    @staticmethod
    def _minimum_days(view: Mapping[str, Any], remaining: int) -> int | None:
        if remaining <= 0:
            return 0
        hands = view.get("team_hands", {})
        g2 = sum("g2" in cards for cards in hands.values())
        days_left = max(0, int(view.get("days", 0)) - int(view.get("round", 0)) + 1)
        gained = 0
        for day in range(1, days_left + 1):
            gained += 2 if day <= g2 else 1
            if gained >= remaining:
                return day
        return None

    def potential(self, view: Mapping[str, Any]) -> float:
        loop = int(view.get("loop", 1))
        used = set(view.get("ability_loop_used", ()))
        values = []
        for source, character in self._living_characters(view).items():
            best = 0.0
            goodwill = int(character.get("goodwill", 0))
            for ability in character.get("abilities", ()):
                if ability.get("kind") not in INFORMATION_ABILITY_KINDS:
                    continue
                if loop < int(ability.get("min_loop", 1)):
                    continue
                key = f"goodwill:{source}:{ability.get('id')}"
                if ability.get("once") and key in used:
                    continue
                gain = self.information_gain(source, ability, view)
                if gain <= 0:
                    continue
                days = self._minimum_days(
                    view, max(0, int(ability.get("threshold", 0)) - goodwill))
                if days is None:
                    continue
                discount = self.discount ** max(0, days - 1)
                best = max(best, gain * discount)
            if best:
                values.append(best)
        # Only the best two projects matter to a three-card daily action. This
        # also prevents a crowded cast from accumulating an outsized bonus.
        return min(1.0, sum(sorted(values, reverse=True)[:2]))

    def investment_targets(self, view: Mapping[str, Any], amount: int,
                           *, limit: int = 3) -> tuple[str, ...]:
        """Public targets whose extra goodwill most improves reachable entropy."""
        baseline = self.potential(view)
        ranked = []
        for source in self._living_characters(view):
            changed = deepcopy(dict(view))
            changed["characters"] = deepcopy(dict(view.get("characters", {})))
            changed["characters"][source]["goodwill"] = (
                int(changed["characters"][source].get("goodwill", 0)) + amount)
            delta = self.potential(changed) - baseline
            if delta > 1e-9:
                ranked.append((delta, source))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return tuple(source for _, source in ranked[:limit])

    def realized_information(self, final_view: Mapping[str, Any]) -> float:
        root_roles = self._known_roles(self.root_view)
        final_roles = self._known_roles(final_view)
        role_value = sum(self._role_entropy(cid)
                         for cid in final_roles - root_roles)
        root_culprits = {int(day) for day in self.root_view.get("known_culprits", {})}
        final_culprits = {int(day) for day in final_view.get("known_culprits", {})}
        culprit_value = sum(self._culprit_entropy(day)
                            for day in final_culprits - root_culprits)
        root_plots = set(self.root_view.get("known_plots", ()))
        final_plots = set(final_view.get("known_plots", ()))
        plot_value = self._plot_entropy(root_plots) if final_plots - root_plots else 0.0
        root_groups = self.root_view.get("protagonist_knowledge", {}).get(
            "same_role_groups", {})
        final_groups = final_view.get("protagonist_knowledge", {}).get(
            "same_role_groups", {})
        group_value = sum(self._copycat_entropy(str(cid))
                          for cid in set(final_groups) - set(root_groups))
        return min(1.0, role_value + culprit_value + plot_value + group_value)

    def evaluate_cutoff(self, final_view: Mapping[str, Any],
                        new_events: Sequence[Mapping[str, Any]]
                        ) -> InformationValueBreakdown:
        realized = self.realized_information(final_view)
        refusal = 0.0
        for event in new_events:
            if (event.get("kind") == "goodwill_refused"
                    and event.get("ability_kind") in INFORMATION_ABILITY_KINDS):
                refusal += 0.15
        future_delta = max(0.0, self.potential(final_view) - self._root_potential)
        return InformationValueBreakdown(
            min(1.0, future_delta), realized, min(0.3, refusal),
            self._threads_carryover_risk(final_view))
