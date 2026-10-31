"""Long-horizon defense protagonist (v1).

Wraps the fair particle planner and only overrides a card choice when a poster-
ior rule-Y obligation or an active hard threat justifies it. Information comes
from the public view plus a particle belief snapshot; hidden plots and roles are
never read from the true world.

V1 is a one-step greedy policy: it scores the legal offers plus the base
planner's own pick with the layered value from ``defense_value``. Multi-day
search (T2) is a later step and is not required here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .defense_value import (DefenseCandidate, DefenseValueWeights,
                            information_value, final_guess_value,
                            select_defense_action)
from .threats import (BOARD_PLOT_THRESHOLD, ThreatAssessment, classify_threats,
                      classify_plot_threats)

# Rule-Y loss routes whose watched board only grows while a hidden role holder
# stays on it: the holder's mastermind ability adds intrigue to its current
# board, so moving the holder away stops the accumulation (cards still need fi).
ROLE_BOARD_PLOTS = {"avenger": "brain", "bomb": "witch", "wm_bomb": "witch",
                    "ll_bomb_z": "witch"}
MOVE_CARDS = frozenset({"h", "v"})

# Every supported rule-Y plot compares a counter against 2 at loop end.
PLOT_THRESHOLDS = {
    "protect": 2, "sealed": 2, "avenger": 2, "bomb": 2, "sign": 2,
    "mz_battle": 2, "mc_dark_school": 2, "wm_gospel": 2, "wm_bomb": 2,
    "ahr_illusory_world": 2, "ll_sealed_end": 2, "ll_treacherous_world": 2,
    "ll_bomb_z": 2,
}

INTRIGUE_CARDS = frozenset({"fi"})


def _counter_for(threat: ThreatAssessment, view: Mapping[str, Any]) -> int:
    """Current watched counter for one threat, from public state only."""
    target = threat.target
    if target in (view.get("characters") or {}):
        state = view["characters"][target]
        if threat.role in ("sign", "ll_treacherous_world", "mz_battle"):
            return int(state.get("intrigue", 0))
        return int(state.get("paranoia", 0))
    from .threats import _board_intrigue
    locations = view.get("locations") or {}
    return _board_intrigue(locations, target)


@dataclass(frozen=True)
class DefenseObligation:
    threat: ThreatAssessment
    counter: int
    threshold: int
    days_left: int
    forced: bool = False

    @property
    def need(self) -> int:
        return max(0, self.threshold - self.counter)

    @property
    def margin_zero(self) -> bool:
        """One more increment reaches the threshold."""
        return self.need == 1

    @property
    def urgent(self) -> bool:
        return self.counter >= self.threshold or self.margin_zero \
            or (self.days_left <= 1 and self.counter >= 1)

    @property
    def weight(self) -> float:
        """Risk that the hidden rule-Y route decides the loop.

        One intrigue card can jump a board from 0 to 2, so waiting until the
        margin reaches zero is too late. Weight rises as the loop deadline
        approaches; already-satisfied counters are dead weight.
        """
        if self.counter >= self.threshold:
            return 0.0
        if self.forced:
            return 0.9
        if self.margin_zero:
            return 1.0
        # Hygiene defense: only act once the watched counter has appeared.
        # Rule Y is hidden, so covering a 0-count board is a blind guess and
        # proved counter-productive in the FS protect comparison.
        if self.counter >= 1:
            if self.days_left <= 1:
                return 0.9
            if self.days_left <= 2:
                return 0.7
            return 0.5
        return 0.0


def _world_value(world: Any, name: str) -> str:
    value = getattr(world, name, None)
    if value:
        return str(value)
    scenario = getattr(world, "scenario", None)
    if isinstance(scenario, Mapping):
        return str(scenario.get(name, "") or "")
    return ""


def _world_roles(world: Any) -> Mapping[str, str]:
    roles = getattr(world, "roles", None)
    if isinstance(roles, Mapping) and roles:
        return roles
    scenario = getattr(world, "scenario", None)
    if isinstance(scenario, Mapping):
        return scenario.get("cast", {}) or {}
    return {}


def _role_board_joint(snapshot, plot: str, holder_role: str,
                      character_id: str) -> float:
    """Joint P(world main plot is ``plot`` and ``character_id`` holds the role)."""
    worlds = tuple(getattr(snapshot, "worlds", ()) or ())
    if not worlds:
        return 0.0
    hits = sum(1 for world in worlds
               if _world_value(world, "main_plot") == plot
               and _world_roles(world).get(character_id) == holder_role)
    return hits / len(worlds)


def _cover_targets(offer: Mapping[str, Any]) -> frozenset[str]:
    """Targets whose intrigue accumulation this play can block today.

    Only 禁止密谋 (fi) blocks intrigue; paranoia and goodwill cards do not
    protect a board or character from the rule-Y accumulations tracked here.
    """
    if str(offer.get("type") or offer.get("kind")) != "play":
        return frozenset()
    params = offer.get("parameters") or {}
    card = params.get("card")
    target = params.get("target")
    if card in INTRIGUE_CARDS and target:
        return frozenset({str(target)})
    return frozenset()


@dataclass
class TwoDayProtagonistAgent:
    """Fair protagonist that defends long-horizon rule-Y obligations."""

    base: Any
    particle_count: int = 12
    weights: DefenseValueWeights = DefenseValueWeights()
    survival_target: float = 0.8
    confidence_floor: float = 0.5
    cover_threshold: float = 0.3
    max_covers_per_day: int = 3
    oracle_plot: str | None = None
    oracle_cast: Mapping[str, str] | None = None
    oracle_always_cover: bool = False
    posterior_cover: bool = False
    posterior_floor: float = 0.3
    probe_information: bool = True
    resync_joint_plan: bool = True
    day_plan_value: bool = True
    diagnostics: dict[str, Any] = field(default_factory=dict)

    controls_protagonist_team = True
    uses_public_view = True

    def __post_init__(self):
        self._context_key = None
        self._covered_today: set[str] = set()
        self._residual: dict[tuple[str, str], float] = {}
        self._covers_today = 0
        self._day_plan: list[dict[str, Any]] = []
        self._plan_day_key = None
        self._plan_evaluated = False
        self._obligations: tuple[DefenseObligation, ...] = ()
        self._snapshot = None
        self._threats: tuple[ThreatAssessment, ...] = ()

    # -- belief and obligations -------------------------------------------------
    def _refresh(self, view: Mapping[str, Any], offers: Sequence[Mapping[str, Any]]):
        key = (int(view.get("loop", 0)), int(view.get("round", 0)))
        if key == self._context_key:
            return
        self._context_key = key
        self._covered_today = set()
        self._residual = {}
        self._covers_today = 0
        budget = getattr(self.base, "budget", None)
        if budget is not None:
            from ..search import SearchBudget
            budget = SearchBudget(node_limit=max(8, budget.node_limit // 3),
                                  rollout_depth=budget.rollout_depth,
                                  seed=budget.seed)
        from ..composition import ParticleInformationPolicy
        policy = ParticleInformationPolicy(
            budget=budget, particle_count=self.particle_count,
            rng_seed=getattr(self.base, "rng_seed", 0))
        self._snapshot = policy.build(game=None, view=view, offers=tuple(offers))
        threats = list(classify_threats(view=view, snapshot=self._snapshot))
        threats.extend(classify_plot_threats(view=view, snapshot=self._snapshot))
        if self.oracle_plot:
            threats.extend(self._oracle_threats(view))
        self._threats = tuple(threats)
        current_day = int(view.get("round", 1))
        days_left = max(0, int(view.get("days", current_day)) - current_day)
        obligations = []
        for threat in threats:
            if threat.failure_kind != "plot_loss":
                continue
            threshold = PLOT_THRESHOLDS.get(str(threat.role),
                                            BOARD_PLOT_THRESHOLD)
            forced = ((self.oracle_always_cover
                       and threat.source == "oracle_plot")
                      or (self.posterior_cover
                          and threat.confidence >= self.posterior_floor))
            obligations.append(DefenseObligation(
                threat=threat, counter=_counter_for(threat, view),
                threshold=threshold, days_left=days_left, forced=forced))
        self._obligations = tuple(sorted(
            obligations, key=lambda item: (-item.weight, -item.threat.confidence)))

    def _oracle_threats(self, view: Mapping[str, Any]) -> tuple[ThreatAssessment, ...]:
        """Diagnostic-only: treat the true rule Y as public knowledge.

        This is an ablation used to check whether covering the watched board
        actually prevents the accumulated loss. It never runs in matches.
        """
        from .threats import PLOT_LOSS_TARGETS
        spec = PLOT_LOSS_TARGETS.get(self.oracle_plot or "")
        if spec is None:
            return ()
        mode, value = spec
        target = value
        if mode in ("role_board", "role"):
            cast = self.oracle_cast or {}
            holder = next((cid for cid, role in cast.items() if role == value), None)
            if holder is None:
                return ()
            if mode == "role":
                target = holder
            else:
                target = str((view.get("characters") or {}).get(holder, {})
                             .get("initial_location") or "")
                if not target:
                    return ()
        current_day = int(view.get("round", 1))
        deadline = int(view.get("days", current_day))
        return (ThreatAssessment(
            target=target, failure_kind="plot_loss", role=self.oracle_plot,
            confidence=1.0, severity=1.0, deadline=deadline,
            active_now=False, source="oracle_plot", hard=False),)

    def _risks(self) -> tuple[DefenseObligation, ...]:
        return tuple(obligation for obligation in self._obligations
                     if obligation.weight > 0
                     and obligation.threat.confidence >= self.confidence_floor)

    # -- scoring ----------------------------------------------------------------
    def _defense_cover(self, offer: Mapping[str, Any],
                       obligation: DefenseObligation,
                       view: Mapping[str, Any]
                       ) -> tuple[str, str, float] | None:
        """(watched target, long-term score) this offer defends for one risk.

        Two channels:
        - 禁止密谋 (fi) blocks card-driven intrigue on the watched target;
        - moving the suspected role holder off the watched board stops its
          mastermind ability from adding intrigue there (avenger/bomb).
        """
        target = obligation.threat.target
        params = offer.get("parameters") or {}
        card = params.get("card")
        chosen_target = str(params.get("target") or "")
        plot = str(obligation.threat.role or "")
        base_score = obligation.weight * obligation.threat.confidence
        if card in INTRIGUE_CARDS and chosen_target == target:
            return target, "card", base_score
        holder_role = ROLE_BOARD_PLOTS.get(plot)
        if holder_role and card in MOVE_CARDS and chosen_target:
            characters = view.get("characters") or {}
            if str((characters.get(chosen_target) or {}).get("location")) != target:
                return None
            joint = _role_board_joint(self._snapshot, plot, holder_role,
                                      chosen_target)
            if joint <= 0:
                return None
            future = min(1.0, max(0.3, obligation.days_left / 3.0))
            return target, "ability", base_score * joint * future
        return None

    def _channel_risks(self, obligation: DefenseObligation,
                       view: Mapping[str, Any]) -> dict[str, float]:
        """Split one watched-board risk into card and ability sources.

        Cards (i1/i2) and the holder's mastermind ability add intrigue through
        different mechanisms: ``fi`` blocks cards, moving the holder off the
        board blocks the ability. Keeping them as separate channels lets two
        seats cover both in the same day instead of treating one as full cover.
        """
        target = obligation.threat.target
        full = obligation.weight * obligation.threat.confidence
        holder_role = ROLE_BOARD_PLOTS.get(str(obligation.threat.role or ""))
        ability = 0.0
        if holder_role:
            characters = view.get("characters") or {}
            for cid, state in characters.items():
                if str((state or {}).get("location")) != target:
                    continue
                joint = _role_board_joint(self._snapshot,
                                          str(obligation.threat.role),
                                          holder_role, cid)
                ability += joint * full
        return {"card": full, "ability": min(full, ability)}

    def _remaining_channel(self, target: str, channel: str,
                           obligation: DefenseObligation,
                           view: Mapping[str, Any]) -> float:
        key = (target, channel)
        if key in self._residual:
            return self._residual[key]
        risks = self._channel_risks(obligation, view)
        return risks.get(channel, 0.0)

    def _best_cover(self, offer: Mapping[str, Any],
                    risks: tuple[DefenseObligation, ...],
                    view: Mapping[str, Any]) -> tuple[str, str, float] | None:
        if self._covers_today >= self.max_covers_per_day:
            return None
        best = None
        for obligation in risks:
            result = self._defense_cover(offer, obligation, view)
            if result is None:
                continue
            target, channel, raw = result
            remaining = self._remaining_channel(target, channel,
                                                obligation, view)
            if remaining <= 1e-9:
                continue
            value = min(remaining, raw)
            if best is None or value > best[2]:
                best = (target, channel, value)
        return best

    def _probe_information(self, offer: Mapping[str, Any],
                           risks: tuple[DefenseObligation, ...],
                           view: Mapping[str, Any]) -> float:
        """Expected brain-identity entropy drop from testing a suspect by moving it.

        Moving one of two candidates is an experiment: if the watched board
        stops growing next ability phase the moved character is the holder;
        if it keeps growing the other candidate is. Both outcomes identify the
        brain, which is valuable even when the move prevents nothing today.
        """
        if self._snapshot is None:
            return 0.0
        params = offer.get("parameters") or {}
        if params.get("card") not in MOVE_CARDS:
            return 0.0
        moved = str(params.get("target") or "")
        worlds = tuple(getattr(self._snapshot, "worlds", ()) or ())
        if not worlds:
            return 0.0
        characters = view.get("characters") or {}
        best = 0.0
        for obligation in risks:
            plot = str(obligation.threat.role or "")
            holder_role = ROLE_BOARD_PLOTS.get(plot)
            if holder_role is None:
                continue
            board = obligation.threat.target
            identities = []
            stops = 0
            for world in worlds:
                if _world_value(world, "main_plot") != plot:
                    continue
                roles = _world_roles(world)
                holder = next((cid for cid, role in roles.items()
                               if role == holder_role), None)
                if holder is None:
                    continue
                identities.append(holder)
                if (holder == moved
                        and str((characters.get(moved) or {}).get("location")) == board):
                    stops += 1
            total = len(identities)
            if total < 2 or stops == 0 or stops == total:
                continue
            from math import log2
            def entropy(values):
                counts = {}
                for value in values:
                    counts[value] = counts.get(value, 0) + 1
                return -sum((n / len(values)) * log2(n / len(values))
                            for n in counts.values())
            before = entropy(identities)
            if before <= 1e-9:
                continue
            continued = [identity for identity in identities
                         if not (identity == moved)]
            after = (stops / total) * 0.0 + (len(continued) / total) * entropy(continued)
            gain = (before - after) / before
            # The ability is optional, so a quiet board is noisy evidence.
            best = max(best, gain * 0.8)
        return best

    def _candidate(self, offer_or_command, *, view, base_pick,
                   risks, hard) -> DefenseCandidate:
        cover = self._best_cover(offer_or_command, risks, view)
        covered_targets = set(_cover_targets(offer_or_command))
        # The cover benefit is realized through the expected-loss reduction
        # below; adding it to long_term as well would double-count it and make
        # the agent overspend every seat on defense.
        long_term = 0.0
        cover_value = cover[2] if cover is not None else 0.0
        if cover is not None:
            covered_targets.add(cover[0])
        for threat in hard:
            if str((offer_or_command.get("parameters") or {}).get("target")) == threat.target:
                covered_targets.add(threat.target)
        total_risk = 0.0
        for item in risks:
            for channel in ("card", "ability"):
                total_risk += self._remaining_channel(
                    item.threat.target, channel, item, view)
        # A cover only removes the risk it can actually prevent: fi prevents
        # card intrigue fully, moving a suspected holder prevents a share
        # proportional to the joint posterior. Residual risk stays available
        # for the next seat, so both disjuncts can be covered on the same day.
        expected_loss = max(0.0, total_risk - cover_value)
        survival = 0.5
        if base_pick is not None and offer_or_command.get("id") == base_pick.get("id"):
            survival = 0.6
        return DefenseCandidate(
            action=offer_or_command.get("id"),
            survival=survival,
            long_term=long_term,
            information=(max(information_value(self._snapshot, view),
                             self._probe_information(offer_or_command, risks, view))
                         if self.probe_information else
                         information_value(self._snapshot, view)),
            final_guess=final_guess_value(self._snapshot, view),
            expected_loss=max(0.0, expected_loss),
            covered_targets=frozenset(covered_targets),
        )

    # -- three-card day-plan evaluation -----------------------------------------
    @staticmethod
    def _command(offer: Mapping[str, Any]) -> dict[str, Any]:
        params = offer.get("parameters") or {}
        return {"actor": offer.get("actor"), "action": "play",
                "card": params.get("card"), "target": params.get("target")}

    def _score_plan(self, commands, view, risks,
                    worlds: Sequence[Any]) -> float | None:
        """Average public outcome of one day plan over sampled worlds."""
        if len(commands) < 3 or not worlds:
            return None
        scores = []
        for world in list(worlds)[:6]:
            try:
                sim = world.clone()
                for command in commands:
                    sim = sim.transition(command).game
                start = (sim.state.loop, sim.state.round)
                before = len(sim.loss_reasons)
                steps = 0
                # Drive the rest of the loop with the first legal action for
                # both sides; the compared plans differ only in today's card,
                # so the shared passive future keeps the comparison honest
                # while still exposing multi-day accumulation.
                while (sim.winner is None
                       and (sim.state.loop, sim.state.round)[0] == start[0]
                       and steps < 200):
                    offers = sim.action_offers(sim.controller)
                    if not offers:
                        break
                    if sim.controller == "m":
                        pick = next((item for item in offers
                                     if item.kind == "core.play"), None)
                        if pick is None:
                            pick = next((item for item in offers
                                         if item.kind in ("core.next", "next",
                                                          "core.choose", "choose")),
                                        offers[0])
                    else:
                        pick = next((item for item in offers
                                     if item.kind in ("core.next", "next",
                                                      "core.choose", "choose")),
                                    offers[0])
                    sim = sim.transition(pick.command).game
                    steps += 1
                new_reasons = list(sim.loss_reasons[before:])
                loop_lost = bool(new_reasons) or sim.winner == "mastermind"
                rule_y_lost = any("规则 Y" in str(reason)
                                  for reason in new_reasons)
                if rule_y_lost:
                    rule_safe, survival = 0.0, 0.0
                elif loop_lost:
                    rule_safe, survival = 0.5, 0.0
                else:
                    exec_safe = 1.0
                    for obligation in risks:
                        target = obligation.threat.target
                        counter = int(sim.protagonist_team_view()[
                            "locations"].get(target, 0))
                        if counter >= obligation.threshold:
                            exec_safe = 0.0
                    rule_safe, survival = exec_safe, 1.0
                scores.append(0.6 * rule_safe + 0.4 * survival)
            except Exception:
                continue
        if len(scores) < 2:
            return None
        return sum(scores) / len(scores)

    def _evaluate_day_plan(self, view, base_pick, offers, risks, worlds):
        """Anchor on the base joint plan, try replacing one card, simulate."""
        if not worlds:
            return None
        base_plan = list(getattr(self.base, "_joint_plan", ()) or ())
        anchor = [self._command(base_pick), *base_plan]
        if len(anchor) < 3:
            return None
        anchor_score = self._score_plan(anchor, view, risks, worlds)
        if anchor_score is None:
            return None
        best = (anchor_score + 0.02, None, None)
        for offer in offers:
            if offer.get("id") == base_pick.get("id"):
                continue
            defensive = self._best_cover(offer, risks, view) is not None
            probe = (self.probe_information
                     and self._probe_information(offer, risks, view) > 0.15)
            if not defensive and not probe:
                continue
            plan = [self._command(offer), *base_plan]
            score = self._score_plan(plan, view, risks, worlds)
            if score is None or score <= best[0]:
                continue
            best = (score, offer, plan[1:])
        score, offer, follow = best
        if offer is None:
            return {"first": base_pick, "follow": [], "score": anchor_score,
                    "anchor_score": anchor_score, "variant": False}
        if hasattr(self.base, "_joint_plan"):
            self.base._joint_plan = []
            self.base._joint_plan_position = None
        return {"first": offer, "follow": follow, "score": score,
                "anchor_score": anchor_score, "variant": True}

    def _follow_day_plan(self, view, offers):
        if not self._day_plan:
            return None
        by_key = {}
        for offer in offers:
            params = offer.get("parameters") or {}
            key = (offer.get("actor"), params.get("card"), params.get("target"))
            by_key[key] = offer
        command = self._day_plan[0]
        key = (command.get("actor"), command.get("card"), command.get("target"))
        offer = by_key.get(key)
        if offer is None:
            self._day_plan = []
            self._plan_variant = False
            return None
        self._day_plan.pop(0)
        return offer

    def choose_action(self, *, participant: str, view: dict[str, Any],
                      offers: Sequence[dict[str, Any]]) -> dict[str, Any]:
        if (view.get("module") not in ("FS", "BTX")
                or view.get("phase") != "protagonists"
                or not offers
                or not all(str(offer.get("type", offer.get("kind", "")))
                           .removeprefix("core.") == "play" for offer in offers)):
            return self.base.choose_action(participant=participant,
                                           view=view, offers=offers)
        self._refresh(view, offers)
        risks = self._risks()
        hard = tuple(threat for threat in self._threats
                     if threat.hard and threat.active_now)
        if not risks and not hard:
            return self.base.choose_action(participant=participant,
                                           view=view, offers=offers)
        position = (int(view.get("loop", 0)), int(view.get("round", 0)))
        if self._plan_day_key != position:
            self._plan_day_key = position
            self._day_plan = []
            self._plan_evaluated = False
        follow = self._follow_day_plan(view, offers)
        if follow is not None:
            self.diagnostics.update(reason="day_plan_follow",
                                    chosen=str(follow.get("id")))
            return follow
        base_pick = self.base.choose_action(participant=participant,
                                            view=view, offers=offers)
        if (self.day_plan_value and not self._plan_evaluated
                and self._snapshot is not None
                and getattr(self._snapshot, "worlds", ())):
            self._plan_evaluated = True
            plan = self._evaluate_day_plan(
                view, base_pick, offers, risks, self._snapshot.worlds)
            if plan is not None:
                if not plan["variant"]:
                    # The evaluated three-card anchor is best; trust it and let
                    # the base planner execute its own joint follow-ups.
                    self.diagnostics.update(
                        reason="day_plan_anchor",
                        planscore=round(plan["score"], 3),
                        anchorscore=round(plan["anchor_score"], 3),
                        chosen=str(plan["first"].get("id")))
                    return plan["first"]
                self._day_plan = list(plan["follow"])
                self.diagnostics.update(
                    reason="day_plan_variant",
                    planscore=round(plan["score"], 3),
                    anchorscore=round(plan["anchor_score"], 3),
                    chosen=str(plan["first"].get("id")))
                return plan["first"]
        return self._per_seat_choice(view, base_pick, offers, risks, hard)

    def _per_seat_choice(self, view, base_pick, offers, risks, hard):
        candidates = []
        by_id = {}
        for offer in offers:
            candidates.append(self._candidate(offer, view=view,
                                              base_pick=base_pick,
                                              risks=risks, hard=hard))
            by_id[offer["id"]] = offer
        candidates.append(self._candidate(base_pick, view=view,
                                          base_pick=base_pick,
                                          risks=risks, hard=hard))
        by_id[base_pick["id"]] = base_pick
        threats = tuple(item.threat for item in risks) + hard
        selection = select_defense_action(
            candidates, threats, weights=self.weights,
            survival_target=self.survival_target)
        chosen = selection.chosen
        if chosen is None or chosen.action not in by_id:
            return base_pick
        picked = by_id[chosen.action]
        if chosen.action != base_pick.get("id") and self.resync_joint_plan:
            # The base planner keeps a joint 3-card day plan; overriding one
            # seat invalidates it, so drop it to avoid replaying stale cards.
            if hasattr(self.base, "_joint_plan"):
                self.base._joint_plan = []
                self.base._joint_plan_position = None
        cover = self._best_cover(picked, risks, view)
        if cover is not None:
            target, channel, value = cover
            obligation = next((item for item in risks
                               if item.threat.target == target), None)
            if obligation is not None:
                remaining = self._remaining_channel(target, channel,
                                                    obligation, view)
                self._residual[(target, channel)] = max(
                    0.0, remaining - value)
            self._covered_today = getattr(self, "_covered_today", set()) | {target}
            self._covers_today += 1
        self.diagnostics.update(
            reason=selection.reason,
            risks=[{"target": item.threat.target, "plot": item.threat.role,
                    "counter": item.counter,
                    "confidence": round(item.threat.confidence, 3)}
                   for item in risks],
            chosen=str(chosen.action),
            chosen_long_term=round(chosen.long_term, 3))
        return picked
