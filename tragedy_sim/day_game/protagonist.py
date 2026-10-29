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
    max_covers_per_day: int = 2
    oracle_plot: str | None = None
    oracle_cast: Mapping[str, str] | None = None
    oracle_always_cover: bool = False
    posterior_cover: bool = False
    posterior_floor: float = 0.3
    diagnostics: dict[str, Any] = field(default_factory=dict)

    controls_protagonist_team = True
    uses_public_view = True

    def __post_init__(self):
        self._context_key = None
        self._covered_today: set[str] = set()
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
    def _candidate(self, offer_or_command, *, view, base_pick,
                   obligation) -> DefenseCandidate:
        covered = _cover_targets(offer_or_command)
        covered_targets = frozenset(covered)
        long_term = 0.0
        expected_loss = 0.0
        if obligation is not None:
            weight = obligation.weight * obligation.threat.confidence
            if obligation.threat.target in covered_targets:
                long_term = weight
            else:
                expected_loss = weight
        survival = 0.5
        if base_pick is not None and offer_or_command.get("id") == base_pick.get("id"):
            survival = 0.6
        return DefenseCandidate(
            action=offer_or_command.get("id"),
            survival=survival,
            long_term=long_term,
            information=information_value(self._snapshot, view),
            final_guess=final_guess_value(self._snapshot, view),
            expected_loss=expected_loss,
            covered_targets=covered_targets,
        )

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

        # 1. Cover the highest-risk obligation that this seat can forbid today.
        cover = self._cover_offer(offers, risks)
        if cover is not None:
            return cover

        # 2. No rule-Y cover available: fall back to the layered choice, which
        #    honors active hard threats.
        base_pick = self.base.choose_action(participant=participant,
                                            view=view, offers=offers)
        obligation = risks[0] if risks else None
        candidates = []
        by_id = {}
        for offer in offers:
            candidates.append(self._candidate(offer, view=view,
                                              base_pick=base_pick,
                                              obligation=obligation))
            by_id[offer["id"]] = offer
        base_candidate = self._candidate(base_pick, view=view,
                                         base_pick=base_pick,
                                         obligation=obligation)
        candidates.append(base_candidate)
        by_id[base_pick["id"]] = base_pick
        threats = tuple(item.threat for item in risks) + hard
        selection = select_defense_action(
            candidates, threats, weights=self.weights,
            survival_target=self.survival_target)
        chosen = selection.chosen
        self.diagnostics.update(
            reason=selection.reason,
            risks=[{"target": item.threat.target, "plot": item.threat.role,
                    "counter": item.counter,
                    "confidence": round(item.threat.confidence, 3)}
                   for item in risks],
            chosen=str(chosen.action) if chosen is not None else None)
        if chosen is None or chosen.action not in by_id:
            return base_pick
        return by_id[chosen.action]

    def _cover_offer(self, offers, risks):
        """Pick an intrigue-forbid offer covering the best pending risk target."""
        covered = getattr(self, "_covered_today", set())
        best = None
        for index, obligation in enumerate(risks):
            if obligation.threat.target in covered:
                continue
            if index >= self.max_covers_per_day:
                break
            score = obligation.weight * obligation.threat.confidence
            if score < self.cover_threshold:
                continue
            for offer in offers:
                covered_targets = _cover_targets(offer)
                if obligation.threat.target not in covered_targets:
                    continue
                if best is None or score > best[0]:
                    best = (score, offer, obligation)
                break
        if best is None:
            return None
        score, offer, obligation = best
        self._covered_today = covered | {obligation.threat.target}
        self.diagnostics.update(
            reason="plot_cover",
            risks=[{"target": item.threat.target, "plot": item.threat.role,
                    "counter": item.counter,
                    "confidence": round(item.threat.confidence, 3)}
                   for item in risks],
            covered_target=obligation.threat.target,
            cover_score=round(score, 3),
            chosen=str(offer.get("id")))
        return offer
