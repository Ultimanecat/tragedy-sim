"""Public-information, particle-ensemble day planner for FS/BTX protagonists.

This is a one-day belief-state planner, not a full information-set MCTS tree.
The real game's script is never an input: proposals come from sampled worlds
and every complete three-card plan is evaluated on the same world batch.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import random
from time import perf_counter
from typing import Any, Mapping, Sequence

from .belief import DarkCardBelief, PublicEvidence
from .belief_planner import PublicBeliefPlanner, IsmctsTrace, _command, _key
from .composition import ParticleInformationPolicy
from .defense import DefenseContext, DefenseModule
from .information_value import InformationOpportunityEvaluator
from .oracle_protagonist import OracleProtagonistAgent
from .search import SearchBudget
from .witness import FsbtxWitnessCompiler, WitnessStrength


class ParticleEnsembleProtagonistAgent(PublicBeliefPlanner):
    """Propose Oracle-style bundles per hypothesis, cross-score on all worlds."""

    def __init__(self, budget: SearchBudget | None = None, *,
                 particle_count: int = 12, rng_seed: int = 0,
                 joint_witness: bool = True,
                 disabled_witness_sources: Sequence[str] = (),
                 rollout_horizon: str = "day",
                 mastermind_policy_samples: int = 3,
                 information_reward_weight: float = 0.01,
                 matrix_proposals: bool = True, joint_culprits: bool = True,
                 matrix_variant_policy: str = "prior",
                 final_guess_policy: str = "latent_map",
                 final_guess_node_limit: int = 100_000,
                 role_sampling_policy: str = "importance", role_partition_node_limit: int = 100_000,
                 dark_card_policy: str = "sampled", dark_attack_limit: int = 8,
                 dark_guard_proposals: bool = True, candidate_policy: str = "legacy",
                 action_role_sampling_policy: str = "iid",
                 information_policy: str = "public",
                 true_roles: Mapping[str, str] | None = None,
                 true_incidents: Mapping[int, str] | None = None,
                 defense_module: DefenseModule | None = None,
                 defense_weight: float = 0.0,
                 defense_override: bool = False,
                 scenario: Mapping[str, Any] | None = None):
        if not isinstance(defense_weight, (int, float)) or defense_weight < 0:
            raise ValueError("defense_weight must be non-negative")
        self.defense_module = defense_module
        self.defense_weight = float(defense_weight)
        self.defense_override = bool(defense_override)
        self.scenario = scenario
        if type(information_policy) is not str or information_policy not in {"public", "oracle"}:
            raise ValueError("information_policy must be public or oracle")
        self.information_policy = information_policy
        self.true_roles = dict(true_roles or {})
        self.true_incidents = {int(day): str(cid)
                               for day, cid in (true_incidents or {}).items()}
        self._true_incidents: dict[int, str] = {}
        if type(action_role_sampling_policy) is not str or action_role_sampling_policy not in {"iid", "residual_small"}:
            raise ValueError("action_role_sampling_policy must be iid or residual_small")
        if type(candidate_policy) is not str or candidate_policy not in {"legacy", "joint_threat"}:
            raise ValueError("candidate_policy must be legacy or joint_threat")
        self.candidate_policy = candidate_policy
        if rollout_horizon not in {"day", "loop"}:
            raise ValueError("particle rollout_horizon must be day or loop")
        if (type(mastermind_policy_samples) is not int
                or mastermind_policy_samples < 1):
            raise ValueError("mastermind_policy_samples must be positive")
        if (not isinstance(information_reward_weight, (int, float))
                or information_reward_weight < 0):
            raise ValueError("information_reward_weight must be non-negative")
        if type(matrix_proposals) is not bool:
            raise ValueError("matrix_proposals must be boolean")
        if type(joint_culprits) is not bool:
            raise ValueError("joint_culprits must be boolean")
        if type(matrix_variant_policy) is not str or matrix_variant_policy not in {"uniform", "prior"}:
            raise ValueError("matrix_variant_policy must be uniform or prior")
        if type(final_guess_policy) is not str or final_guess_policy not in {"latent_map", "cast_map"}:
            raise ValueError("final_guess_policy must be latent_map or cast_map")
        if type(final_guess_node_limit) is not int or final_guess_node_limit < 1:
            raise ValueError("final_guess_node_limit must be a positive integer")
        from .belief_partition_sampler import validate_role_sampling_options
        validate_role_sampling_options(role_sampling_policy, role_partition_node_limit, matrix_proposals)
        if type(dark_card_policy) is not str or dark_card_policy not in {"sampled", "adversarial_guard", "marginal_guard"}:
            raise ValueError("dark_card_policy must be sampled, adversarial_guard or marginal_guard")
        if type(dark_attack_limit) is not int or dark_attack_limit < 1:
            raise ValueError("dark_attack_limit must be a positive integer")
        if type(dark_guard_proposals) is not bool:
            raise ValueError("dark_guard_proposals must be boolean")
        super().__init__(budget or SearchBudget(node_limit=24,
                                                rollout_depth=12,
                                                time_limit_ms=3000),
                         particle_count=particle_count, rng_seed=rng_seed,
                         survival_first=True)
        self.factorized_belief.matrix_proposals_enabled = matrix_proposals
        self.factorized_belief.matrix_variant_policy = matrix_variant_policy
        self.factorized_belief.role_sampling_policy = role_sampling_policy
        self.factorized_belief.role_partition_node_limit = role_partition_node_limit
        self.factorized_belief.joint_culprits_enabled = joint_culprits
        self.factorized_belief.action_role_sampling_policy = action_role_sampling_policy
        self.information = ParticleInformationPolicy(
            budget=self.budget, particle_count=particle_count, rng_seed=rng_seed,
            joint_witness=joint_witness, disabled_witness_sources=disabled_witness_sources,
            matrix_proposals=matrix_proposals, matrix_variant_policy=matrix_variant_policy,
            joint_culprits=joint_culprits, role_sampling_policy=role_sampling_policy,
            role_partition_node_limit=role_partition_node_limit,
            action_role_sampling_policy=action_role_sampling_policy,
            information_policy=information_policy, true_roles=true_roles,
            true_incidents=true_incidents)
        self.factorized_belief = self.information.factorized_belief
        self.evidence_ledger = self.information.evidence_ledger
        self.determinizer = self.information.determinizer
        self.compiler = self.information.compiler
        self.sampler = self.information.sampler
        self.belief = self.information.belief
        self.rollout_horizon = rollout_horizon
        self.mastermind_policy_samples = mastermind_policy_samples
        self.information_reward_weight = float(information_reward_weight)
        self.final_guess_policy = final_guess_policy
        self.final_guess_node_limit = final_guess_node_limit
        self.dark_card_policy = dark_card_policy
        self.dark_attack_limit = dark_attack_limit
        self.dark_guard_proposals = dark_guard_proposals
        self.oracle = OracleProtagonistAgent(
            reveal_cards=True, budget=self.budget, rng_seed=rng_seed,
            rollout_horizon=rollout_horizon, script_aware_rollout=False)

    @property
    def plan_name(self) -> str:
        return "public_fs_btx_particle_ensemble"

    @staticmethod
    def _evaluation_key(row: tuple[Any, ...]) -> tuple[Any, ...]:
        """Safety dimensions precede every bounded shaping contribution."""
        return row[0], row[2], row[1], row[3], row[4]

    @staticmethod
    def _prioritize_proposals(proposals: Mapping[str, Any],
                              priorities: Mapping[str, Any],
                              limit: int) -> dict[str, Any]:
        """Reserved candidates must run before a wall-clock cutoff."""
        selected = dict(list(priorities.items())[:limit])
        for signature, bundle in proposals.items():
            if len(selected) >= limit:
                break
            selected.setdefault(signature, bundle)
        return selected

    @staticmethod
    def _incident_anchor_order(bases: Sequence[Sequence[Mapping[str, Any]]]
                               ) -> list[tuple[Sequence[Mapping[str, Any]], int]]:
        """Keep existing board defense and movement when lowering paranoia."""
        anchors = [(base, slot) for base in bases for slot in range(len(base))]
        def rank(anchor: tuple[Sequence[Mapping[str, Any]], int]) -> tuple[int, int]:
            base, slot = anchor
            remaining = [item.get("card") for index, item in enumerate(base)
                         if index != slot]
            synergistic = ("fi" in remaining
                           and any(card in {"h", "v", "d"} for card in remaining))
            return (0 if synergistic else 1,
                    0 if base[slot].get("card") in {"g1", "g2"} else 1)
        return sorted(anchors, key=rank)

    @staticmethod
    def _location_guard_bonus(bundle: Sequence[Mapping[str, Any]],
                              view: Mapping[str, Any]) -> float:
        """Reward covering a publicly targeted board without reading its face.

        This is deliberately smaller than a failed-world difference and is
        only used after horizon and day survival.  It expresses the common
        defensive prior that a mastermind board placement is often intrigue.
        """
        boards = set(view.get("locations", {}))
        threatened = {
            str(item["target"]) for item in view.get("pending", ())
            if item.get("actor") == "m" and item.get("target") in boards
        }
        placements = (*view.get("pending", ()), *bundle)
        if sum(item.get("card") == "fi" for item in placements) != 1:
            return 0.0  # Multiple intrigue forbids all cancel each other.
        return (0.08 if any(item.get("card") == "fi"
                            and item.get("target") in threatened
                            for item in placements) else 0.0)

    @staticmethod
    def _incident_guard_targets(view: Mapping[str, Any],
                                evidence: PublicEvidence,
                                witnesses: Sequence[Any], *,
                                information_policy: str = "public",
                                true_incidents: Mapping[int, str] | None = None
                                ) -> tuple[str, ...]:
        """Publicly identified culprits whose imminent event needs defense."""
        day = int(view["round"])
        true_incidents = dict(true_incidents or {})
        if not any(scheduled == day for scheduled, _ in evidence.schedule):
            if not true_incidents:
                return ()
        pending = {str(item.get("target")) for item in view.get("pending", ())
                   if item.get("actor") == "m"}
        candidates = dict.fromkeys(str(witness.value) for witness in witnesses
                                   if witness.strength == WitnessStrength.HARD
                                   and witness.kind == "culprit_is"
                                   and witness.subject == str(day))
        from .belief_culprit_constraints import culprit_domains
        inferred = culprit_domains(evidence.characters, evidence.schedule,
                                   dict(evidence.known_culprits), witnesses).get(day, ())
        if len(inferred) == 1:
            # Snapshot thresholds can identify a culprit without an explicit
            # culprit_is event. Use the same hard domain as matrix/sampling.
            candidates.setdefault(inferred[0], None)
        if information_policy == "oracle":
            # Diagnostic information policy: the planner is told the true
            # upcoming incident culprits, but still uses the same action code.
            for incident_day, cid in true_incidents.items():
                if 0 <= incident_day - day <= 1:
                    candidates.setdefault(cid, None)
        targets = []
        for cid in candidates:
            character = view.get("characters", {}).get(cid, {})
            paranoia = character.get("paranoia")
            threshold = character.get("paranoia_limit")
            if (character.get("alive", False)
                    and character.get("present", False)
                    and type(paranoia) is int
                    and type(threshold) is int
                    and (paranoia >= threshold
                         or paranoia == threshold - 1 and cid in pending)):
                targets.append(cid)
        return tuple(targets)

    @staticmethod
    def _incident_escape_targets(view: Mapping[str, Any],
                                 evidence: PublicEvidence,
                                 witnesses: Sequence[Any]) -> tuple[str, ...]:
        """Known loss-critical people worth moving on a public Murder day.

        The culprit's paranoia can exceed what one -1 card can repair. Keep
        victim relocation in the finite proposal pool as a separate defense.
        This only proposes actions; the common-world simulation ranks them.
        """
        if (int(view["round"]), "murder") not in evidence.schedule:
            return ()
        roles = {cid: fact.get("role") if isinstance(fact, Mapping) else fact
                 for cid, fact in view.get("known_roles", {}).items()}
        roles.update({w.subject: w.value for w in witnesses
                      if w.strength == WitnessStrength.HARD
                      and w.kind == "role_is"})
        return tuple(cid for cid, character in view.get("characters", {}).items()
                     if roles.get(cid) in {"key", "friend"}
                     and character.get("alive", False)
                     and character.get("present", False)
                     and character.get("action_targetable", True))

    @staticmethod
    def _time_traveler_candidates(witnesses: Sequence[Any]) -> tuple[str, ...]:
        sets = []
        for witness in witnesses:
            if (getattr(witness, "kind", None) != "role_pressure"
                    or getattr(witness, "subject", None) != "time_traveler"
                    or getattr(witness, "strength", None) != "hard"
                    or not isinstance(getattr(witness, "value", None), Mapping)):
                continue
            candidates = witness.value.get("candidates")
            if isinstance(candidates, (list, tuple)):
                sets.append(set(str(cid) for cid in candidates))
        return tuple(sorted(set.intersection(*sets))) if sets else ()

    @staticmethod
    def _time_traveler_screening_bundle(
            base: Sequence[Mapping[str, Any]], view: Mapping[str, Any],
            candidates: Sequence[str], *, offset: int = 0
            ) -> tuple[dict[str, Any], ...] | None:
        """Build one public-information bundle that tests distinct candidates."""
        characters = view.get("characters", {})
        hands = view.get("team_hands", {})
        ranked = sorted(
            (cid for cid in candidates
             if cid in characters
             and characters[cid].get("alive", True)
             and int(characters[cid].get("goodwill", 0)) < 3),
            key=lambda cid: (-int(characters[cid].get("goodwill", 0)), cid))
        ranked = ranked[offset:offset + 3]
        if not ranked:
            return None
        result = [dict(command) for command in base]
        used: set[str] = set()
        changed = False
        for slot, command in enumerate(result):
            actor = str(command.get("actor", ""))
            hand = set(hands.get(actor, ()))
            target = next((cid for cid in ranked if cid not in used), None)
            if target is None:
                break
            goodwill = int(characters[target].get("goodwill", 0))
            card = ("g1" if goodwill == 2 and "g1" in hand else
                    "g2" if "g2" in hand else
                    "g1" if "g1" in hand else None)
            if card is None:
                continue
            result[slot] = {**command, "card": card, "target": target}
            used.add(target)
            changed = True
        return tuple(result) if changed else None

    @staticmethod
    def _time_traveler_screening_bonus(
            bundle: Sequence[Mapping[str, Any]], view: Mapping[str, Any],
            candidates: Sequence[str]) -> float:
        """Reward progress against a *publicly inferred* terminal-loss threat.

        A 0→2 investment needs a later card; the old threshold-only bonus
        discarded it, so the planner repeatedly failed to finish screening.
        No partial credit is given when there is no later day in this loop.
        """
        characters = view.get("characters", {})
        remaining_days = max(0, int(view.get("days", 1))
                             - int(view.get("round", 1)))
        progress: dict[str, int] = {}
        for command in bundle:
            target = str(command.get("target", ""))
            if target not in candidates or target not in characters:
                continue
            amount = {"g1": 1, "g2": 2}.get(command.get("card"), 0)
            progress[target] = progress.get(target, 0) + amount
        bonus = 0.0
        for target, amount in progress.items():
            before = int(characters[target].get("goodwill", 0))
            after = min(3, before + amount)
            if before >= 3 or after + 2 * remaining_days < 3:
                continue
            bonus += 0.016 * (after - before)
            if after == 3:
                bonus += 0.012
        return min(0.07, bonus)

    @staticmethod
    def _time_traveler_screening_offsets(
            candidates: Sequence[str]) -> tuple[int, ...]:
        """Reserve another proposal for unusually broad public candidate sets."""
        return (0, 3) if len(candidates) > 6 else (0,)

    @staticmethod
    def _threads_confirmed(view: Mapping[str, Any],
                           witnesses: Sequence[Any]) -> bool:
        return ("threads" in view.get("known_plots", ())
                or any(w.kind == "plot_present" and w.subject == "threads"
                       and w.strength == "hard" for w in witnesses))

    def _mastermind_strategies(self, world: Any) -> tuple[str | None, ...]:
        # One sample is the retained historical baseline: let the seeded
        # playbook choose one route.  Larger budgets cover the semantic route
        # list evenly instead of permanently favoring its first entries.
        if self.mastermind_policy_samples == 1:
            return (None,)
        options = self.oracle._mastermind_strategy_options(world)
        if len(options) <= self.mastermind_policy_samples:
            return options
        count = self.mastermind_policy_samples
        indexes = tuple(round(index * (len(options) - 1) / (count - 1))
                        for index in range(count))
        return tuple(options[index] for index in indexes)

    @staticmethod
    def _counts(worlds: Sequence[Any], evidence: PublicEvidence
                ) -> tuple[tuple[dict[str, Any], ...],
                           tuple[dict[str, Any], ...],
                           tuple[dict[str, Any], ...]]:
        roles = tuple({
            "character": cid,
            "counts": dict(sorted(Counter(world.roles.get(cid)
                                          for world in worlds).items())),
        } for cid in evidence.characters)
        culprits = tuple({
            "day": day,
            "counts": dict(sorted(Counter(
                next((item["culprit"] for item in world.scenario["incidents"]
                      if item["day"] == day), None)
                for world in worlds).items(), key=lambda pair: str(pair[0]))),
        } for day, _ in evidence.schedule)
        dark = tuple({
            "slot": slot, "target": placement.target,
            "counts": dict(sorted(Counter(
                [item for item in world.state.pending if item.actor == "m"][slot].card
                for world in worlds).items(), key=lambda pair: str(pair[0]))),
        } for slot, placement in enumerate(
            item for item in worlds[0].state.pending if item.actor == "m"))
        return roles, culprits, dark

    @staticmethod
    def _sampling_hash(view: Mapping[str, Any]) -> str:
        """Seed common random samples from decision state, not card difficulty.

        Standard/Easy variants share the same hidden setup.  Their total loop
        count and display metadata may affect planning, but must not reshuffle
        the sampled worlds before the extra loop is actually reached.  Keeping
        common random numbers makes paired self-play diagnose policy changes
        instead of seed noise.
        """
        sampling_view = dict(view)
        for field in ("scenario_id", "title", "loops", "language",
                      "phase_name", "timepoint", "module_name", "labels"):
            sampling_view.pop(field, None)
        sampling_view["events"] = [
            {key: value for key, value in event.items()
             if key not in {"message", "timepoint", "remaining"}}
            for event in view.get("events", ())
        ]
        return hashlib.sha256(json.dumps(
            sampling_view, sort_keys=True, ensure_ascii=False, default=str
        ).encode("utf-8")).hexdigest()[:16]

    def choose_action(self, *, participant: str, view: dict[str, Any],
                      offers: Sequence[dict[str, Any]]) -> dict[str, Any]:
        if participant == "m" or not offers:
            raise ValueError("particle ensemble requires protagonist offers")
        if (view.get("module") not in {"FS", "BTX"}
                or view.get("phase") != "protagonists"
                or not all(str(offer.get("type", offer.get("kind", "")))
                           .removeprefix("core.") == "play" for offer in offers)):
            return super().choose_action(participant=participant,
                                         view=view, offers=offers)
        position = (int(view["loop"]), int(view["round"]))
        offers_by_key = {_key(_command(offer)): offer for offer in offers}
        if self.defense_override and self.defense_module is not None:
            context = DefenseContext(view=view, scenario=self.scenario)
            obligations = tuple(
                item for item in self.defense_module.obligations(context)
                if item.need > 0 and item.lead_days >= 0)
            for obligation in sorted(
                    obligations,
                    key=lambda item: (0 if item.action == "move" else 1, item.lead_days)):
                wanted = (("h", "v", "d") if obligation.action == "move"
                          else ("fi",) if obligation.action == "block_intrigue"
                          else ("p-1",))
                for offer in offers:
                    command = _command(offer)
                    if (command.get("action") == "play"
                            and command.get("card") in wanted
                            and command.get("target") == obligation.target):
                        self.last_trace = IsmctsTrace(
                            self.plan_name, self.rng_seed, str(view["module"]), 0, 0, 0,
                            self.budget.rollout_depth, "defense_override",
                            offer["id"], (), planned_commands=(),
                            rollout_horizon=self.rollout_horizon)
                        return offer
        if self._joint_plan_position != position:
            self._joint_plan = []
            self._joint_plan_position = None
        if self._joint_plan:
            chosen = offers_by_key.get(_key(self._joint_plan[0]))
            if chosen is not None:
                self._joint_plan.pop(0)
                self.last_trace = IsmctsTrace(
                    self.plan_name, self.rng_seed, str(view["module"]), 0, 0, 0,
                    self.budget.rollout_depth, "joint_plan_followup",
                    chosen["id"], (), planned_commands=tuple(self._joint_plan),
                    rollout_horizon=self.rollout_horizon)
                return chosen
            self._joint_plan = []

        started = perf_counter()
        snapshot = self.information.build(game=None, view=view, offers=offers)
        if snapshot is None:
            return self._fallback(participant, view, offers,
                                  "no_particles", 0)
        defense_context = (DefenseContext(view=view, snapshot=snapshot,
                                          scenario=self.scenario)
                           if self.defense_module is not None and self.defense_weight > 0
                           else None)
        evidence = snapshot.evidence
        witnesses = snapshot.witnesses
        worlds = snapshot.worlds
        self._true_incidents = dict(snapshot.known_culprits)
        if not worlds:
            return self._fallback(participant, view, offers,
                                  snapshot.reason or "no_particles",
                                  len(witnesses))
        traveler_candidates = self._time_traveler_candidates(witnesses)
        threads_confirmed = self._threads_confirmed(view, witnesses)
        roles, culprits, dark = self._counts(worlds, evidence)
        information_model = InformationOpportunityEvaluator(
            worlds, view, threads_confirmed=threads_confirmed)
        discarded = set(view.get("discarded", {}).get("m", ()))
        tendencies = DarkCardBelief.placement_tendencies(
            view.get("events", ()), day=position[1], loop=position[0],
            days=int(view.get("days", 4)),
            targets=[str(item["target"]) for item in view.get("pending", ())
                     if item.get("actor") == "m"],
            cards=[card for card in worlds[0]._deck("m")
                   if card not in discarded])
        search_started = perf_counter()
        evidence_ms = (search_started - started) * 1000
        # Evidence maintenance/world construction is accounted separately.
        # Give proposals and their evaluation the full action-search budget.
        deadline = (None if self.budget.time_limit_ms is None else
                    search_started + self.budget.time_limit_ms / 1000)
        # These are adversarial evaluation branches, never posterior samples.
        # Proposal generation and belief telemetry keep the original worlds.
        if self.dark_card_policy == "marginal_guard":
            from .dark_attack_scenarios import marginal_guard_worlds
            evaluation_worlds = tuple(marginal_guard_worlds(world, view, limit=self.dark_attack_limit)
                                      for world in worlds)
        elif self.dark_card_policy == "adversarial_guard":
            from .dark_attack_scenarios import attack_dark_worlds
            evaluation_worlds = tuple((world, *attack_dark_worlds(world, view, limit=self.dark_attack_limit))
                                      for world in worlds)
        else:
            evaluation_worlds = tuple((world,) for world in worlds)
        dark_attack_probes = sum(len(variants) - 1 for variants in evaluation_worlds)

        # The proposal phase may inspect each *sampled* script, but never the
        # true game. All resulting bundles face the same world batch below.
        proposals: dict[str, tuple[dict[str, Any], ...]] = {}
        limit = self.budget.node_limit
        proposal_deadline = (None if deadline is None else
                             search_started + 0.25 * self.budget.time_limit_ms / 1000)
        # Duplicates do not consume evaluation nodes. Allow bounded extra
        # draws so a small/repeated world batch can reach progressive indices.
        for round_index in range(max(12, 4 * limit)):
            for world_index, world in enumerate(worlds):
                if (proposal_deadline is not None
                        and perf_counter() >= proposal_deadline
                        and len(proposals) >= min(6, limit)):
                    break
                index = self.oracle.proposal_index(round_index, world_index)
                bundle = self.oracle._bundle(world, view, index)
                if (len(bundle) != self.oracle.remaining_placements(view) or not bundle
                        or _key(bundle[0]) not in offers_by_key):
                    continue
                proposals.setdefault(_key(bundle), bundle)
                if len(proposals) >= limit:
                    break
            if len(proposals) >= limit or (proposal_deadline is not None
                                           and perf_counter() >= proposal_deadline
                                           and len(proposals) >= min(6, limit)):
                break
        # Public board targets deserve an explicit defensive candidate even
        # when the small particle batch happens not to contain a plot that
        # explains that target.  The card face remains hidden; this is a
        # proposal prior, not a hard inference that the placement is intrigue.
        bases = tuple(proposals.values())
        board_targets = tuple(dict.fromkeys(
            str(item["target"]) for item in view.get("pending", ())
            if item.get("actor") == "m"
            and item.get("target") in view.get("locations", {})))
        guard_proposals: dict[str, tuple[dict[str, Any], ...]] = {}
        for target in board_targets:
            for base in bases:
                slots = sorted(range(len(base)), key=lambda slot: base[slot].get("card") != "fi")
                for slot in slots:
                    anchored = [dict(item) for item in base]
                    anchored[slot] = {**anchored[slot], "card": "fi",
                                      "target": target}
                    bundle = tuple(anchored)
                    if sum(item.get("card") == "fi" for item in
                           (*view.get("pending", ()), *bundle)) != 1:
                        continue
                    if (_key(bundle[0]) not in offers_by_key
                            or self._apply_bundle(worlds[0], bundle) is None):
                        continue
                    signature = _key(bundle)
                    if signature not in proposals:
                        guard_proposals.setdefault(signature, bundle)
                    break
                if guard_proposals:
                    break
            if guard_proposals:
                break
        if guard_proposals:
            retained = list(proposals.items())[:
                max(0, limit - len(guard_proposals))]
            proposals = dict(retained)
            proposals.update(guard_proposals)
        # A publicly identified incident culprit at the paranoia threshold
        # deserves one explicit defense.  Oracle proposals from a small world
        # batch can otherwise omit this legal card entirely.
        incident_proposals: dict[str, tuple[dict[str, Any], ...]] = {}
        for cid in self._incident_guard_targets(
                view, evidence, witnesses,
                information_policy=self.information_policy,
                true_incidents=self._true_incidents):
            for base, slot in self._incident_anchor_order(tuple(proposals.values())):
                anchored = [dict(item) for item in base]
                anchored[slot] = {**anchored[slot], "card": "p-1", "target": cid}
                bundle = tuple(anchored)
                if (_key(bundle[0]) not in offers_by_key
                        or self._apply_bundle(worlds[0], bundle) is None):
                    continue
                signature = _key(bundle)
                if signature not in proposals:
                    incident_proposals.setdefault(signature, bundle)
                if len(incident_proposals) >= min(2, max(1, limit - 1)):
                    break
            if incident_proposals:
                break
        proposals.update(incident_proposals)
        if defense_context is not None:
            defense_proposals: dict[str, tuple[dict[str, Any], ...]] = {}
            obligations = self.defense_module.obligations(defense_context)
            for obligation in obligations:
                if obligation.need <= 0:
                    continue
                cid = obligation.target
                for base, slot in self._incident_anchor_order(tuple(proposals.values())):
                    anchored = [dict(item) for item in base]
                    anchored[slot] = {**anchored[slot], "card": "p-1", "target": cid}
                    bundle = tuple(anchored)
                    if (_key(bundle[0]) not in offers_by_key
                            or self._apply_bundle(worlds[0], bundle) is None):
                        continue
                    signature = _key(bundle)
                    if signature not in proposals:
                        defense_proposals.setdefault(signature, bundle)
                    break
                if len(defense_proposals) >= min(2, max(1, limit - 1)):
                    break
            proposals.update(defense_proposals)
        escape_proposals: dict[str, tuple[dict[str, Any], ...]] = {}
        for cid in (self._incident_escape_targets(view, evidence, witnesses)
                    if limit > 1 else ()):
            for card in ("h", "v", "d"):
                found = False
                for base in tuple(proposals.values()):
                    # Replace an existing placement on this character first;
                    # adding a second one would violate the daily target rule.
                    slots = sorted(range(len(base)), key=lambda slot:
                                   base[slot].get("target") != cid)
                    for slot in slots:
                        anchored = [dict(item) for item in base]
                        anchored[slot] = {**anchored[slot], "card": card,
                                          "target": cid}
                        bundle = tuple(anchored)
                        if (_key(bundle[0]) not in offers_by_key
                                or self._apply_bundle(worlds[0], bundle) is None):
                            continue
                        signature = _key(bundle)
                        if signature not in proposals:
                            escape_proposals.setdefault(signature, bundle)
                        found = True
                        break
                    if found:
                        break
                if len(escape_proposals) >= min(2, max(0, limit - 1)):
                    break
            if len(escape_proposals) >= min(2, max(0, limit - 1)):
                break
        screening_proposals: dict[str, tuple[dict[str, Any], ...]] = {}
        if proposals and traveler_candidates:
            # A second candidate group is warranted by a *large public
            # traveler set*, even before Threads itself can be confirmed.
            # Smaller sets can be rotated across days without displacing a
            # defensive Oracle proposal (BTX01 is a regression example).
            for offset in self._time_traveler_screening_offsets(
                    traveler_candidates):
                screening = self._time_traveler_screening_bundle(
                    next(iter(proposals.values())), view,
                    traveler_candidates, offset=offset)
                if (screening is not None
                        and _key(screening[0]) in offers_by_key
                        and self._apply_bundle(worlds[0], screening) is not None):
                    signature = _key(screening)
                    if signature not in proposals:
                        screening_proposals[signature] = screening
        # Reserve up to two slots for belief-valued information investments.
        # Generate them for both reward-on and reward-off runs so the weight
        # switch is a clean scoring ablation rather than a coverage change.
        bases = tuple(proposals.values())
        information_proposals: dict[str, tuple[dict[str, Any], ...]] = {}
        for card, amount in (("g1", 1), ("g2", 2)):
            for target in information_model.investment_targets(view, amount):
                for base in bases:
                    for slot, command in enumerate(base):
                        anchored = [dict(item) for item in base]
                        anchored[slot] = {**anchored[slot], "card": card,
                                          "target": target}
                        bundle = tuple(anchored)
                        if (_key(bundle[0]) not in offers_by_key
                                or self._apply_bundle(worlds[0], bundle) is None):
                            continue
                        signature = _key(bundle)
                        if signature not in proposals:
                            information_proposals.setdefault(signature, bundle)
                        break
                    if len(information_proposals) >= min(2, limit - 1):
                        break
                if len(information_proposals) >= min(2, limit - 1):
                    break
            if len(information_proposals) >= min(2, limit - 1):
                break
        if (guard_proposals or information_proposals or screening_proposals or incident_proposals
                or escape_proposals):
            priorities = dict(guard_proposals)
            priorities.update(incident_proposals)
            priorities.update(escape_proposals)
            priorities.update(screening_proposals)
            priorities.update(information_proposals)
            proposals = self._prioritize_proposals(proposals, priorities, limit)
        evacuation_count = 0
        if self.dark_card_policy != "sampled" and self.dark_guard_proposals and limit > 1:
            from .dark_attack_scenarios import evacuation_bundles
            attack_proposals = {}
            for world in worlds:
                for bundle in evacuation_bundles(world, view, tuple(proposals.values())):
                    signature = _key(bundle)
                    if (signature not in proposals and _key(bundle[0]) in offers_by_key
                            and self._apply_bundle(worlds[0], bundle) is not None):
                        attack_proposals[signature] = bundle
                        break
                if attack_proposals:
                    break
            # Reserve one candidate for a joint evacuation, with the ordinary
            # pool retained alongside it. This is an explicit proposal ablation.
            if attack_proposals:
                proposals = self._prioritize_proposals(proposals, attack_proposals, limit)
                evacuation_count = len(attack_proposals)
        joint_diagnostics = None
        if self.candidate_policy == "joint_threat":
            from .hypothesis_defense import HypothesisThreatRanker
            from .joint_action_space import JointActionSpace, UnsupportedJointSpace
            try:
                space = JointActionSpace(view, offers)
                ranker = HypothesisThreatRanker(evaluation_worlds, space)
                bundles, enumerated = space.ranked_bundles(
                    lambda _: 0, limit, joint_rank=ranker, distinct_effects=True)
                proposals = {_key(bundle): bundle for bundle in bundles}
                evacuation_count = 0  # Legacy reserved proposals were replaced.
                joint_diagnostics = {
                    "used": True, "posterior_groups": len(worlds),
                    "group_masses": ranker.weights,
                    "dark_scenarios": tuple(len(group) for group in evaluation_worlds),
                    "enumerated_bundles": enumerated, "projections": ranker.projections,
                }
            except UnsupportedJointSpace as error:
                joint_diagnostics = {"used": False, "fallback": str(error)}
        if not proposals:
            return self._fallback(participant, view, offers,
                                  "no_legal_bundle", len(witnesses))

        evaluated = []
        pairs = 0
        for bundle in proposals.values():
            # Never compare partial world rows: early stopping can otherwise
            # make an untested dangerous world look like a safe plan.
            if deadline is not None and perf_counter() >= deadline and evaluated:
                break
            scores: list[tuple[float, bool]] = []
            day_scores: list[tuple[float, bool]] = []
            information_values: list[float] = []
            information_futures: list[float] = []
            information_realized: list[float] = []
            information_refusals: list[float] = []
            threads_risks: list[float] = []
            policy_rollouts = 0
            for world, variants in zip(worlds, evaluation_worlds):
                strategies = self._mastermind_strategies(world)
                policy_outcomes = []
                policy_day_scores = []
                for variant in variants:
                    successor = self._apply_bundle(variant, bundle)
                    if successor is None:
                        policy_outcomes = []
                        break
                    for strategy in strategies:
                        outcome = self.oracle._rollout_score(
                            successor, position[0], position[1],
                            mastermind_strategy=strategy,
                            information_model=(information_model
                                               if self.rollout_horizon == "day"
                                               else None))
                        policy_outcomes.append((
                            outcome[0], outcome[1], *outcome[4:8], outcome[8]))
                        if self.rollout_horizon != "day":
                            policy_day_scores.append(self.oracle._day_score(
                                successor, position[0], position[1],
                                mastermind_strategy=strategy))
                        pairs += 1
                        policy_rollouts += 1
                if not policy_outcomes:
                    scores = []
                    break
                # The script is uncertain to the protagonists, but the
                # mastermind knows it and may choose any applicable route.
                # Defend against the most dangerous sampled route per world.
                selected_policy = min(
                    policy_outcomes,
                    key=lambda item: (item[1], item[0]
                                      + min(0.012,
                                            self.information_reward_weight
                                            * item[2]) - item[6]))
                scores.append(selected_policy[:2])
                information_values.append(selected_policy[2])
                information_futures.append(selected_policy[3])
                information_realized.append(selected_policy[4])
                information_refusals.append(selected_policy[5])
                threads_risks.append(selected_policy[6])
                if policy_day_scores:
                    day_scores.append(min(
                        policy_day_scores, key=lambda item: (item[1], item[0])))
            if len(scores) != len(worlds):
                continue
            survival = sum(ok for _, ok in scores) / len(scores)
            values = sorted(value for value, _ in scores)
            location_guard_bonus = self._location_guard_bonus(bundle, view)
            traveler_screening_bonus = self._time_traveler_screening_bonus(
                bundle, view, traveler_candidates)
            # The lower tail measures simulated risk. A location prior is
            # shaping, and must not mask a worse risk row (e.g. a board bluff
            # distracting from intrigue on a publicly established Key).
            tail = values[max(0, len(values) // 5 - 1)]
            scarce = sum(item["card"] in {"fm", "g2", "p-1"}
                         for item in bundle)
            information_value = (sum(information_values) /
                                 len(information_values))
            information_future = sum(information_futures) / len(information_futures)
            information_fact = sum(information_realized) / len(information_realized)
            information_refusal = sum(information_refusals) / len(information_refusals)
            threads_risk = sum(threads_risks) / len(threads_risks)
            information_bonus = min(
                0.012, self.information_reward_weight * information_value)
            defense_bonus = 0.0
            if defense_context is not None:
                assessment = self.defense_module.assess(defense_context, bundle)
                defense_bonus = self.defense_weight * assessment.score
            mean = (sum(values) / len(values) - 0.025 * scarce
                    + information_bonus + traveler_screening_bonus
                    + location_guard_bonus - threads_risk + defense_bonus)
            day_survival = (sum(ok for _, ok in day_scores) / len(day_scores)
                            if day_scores else survival)
            day_mean = ((sum(value for value, _ in day_scores) /
                         len(day_scores) + location_guard_bonus + defense_bonus)
                        if day_scores else mean)
            evaluated.append((survival, tail, day_survival, day_mean,
                              mean, bundle, policy_rollouts,
                              information_value, information_bonus,
                              information_future, information_fact,
                              information_refusal, location_guard_bonus,
                              traveler_screening_bonus, threads_risk))
        if not evaluated:
            return self._fallback(participant, view, offers,
                                  "no_common_legal_bundle", len(witnesses))
        best = max(evaluated, key=self._evaluation_key)
        bundle = best[5]
        self._joint_plan = [dict(command) for command in bundle[1:]]
        self._joint_plan_position = position
        chosen = offers_by_key[_key(bundle[0])]
        self.last_trace = IsmctsTrace(
            self.plan_name, self.rng_seed, evidence.module, len(worlds),
            len(witnesses), len(evaluated), self.budget.rollout_depth,
            None, chosen["id"],
            tuple({"bundle": [dict(item) for item in row[5]],
                   "visits": len(worlds), "availability": len(worlds),
                   "mean_value": row[4], "day_survivals": round(row[2] * len(worlds)),
                   "horizon_survivals": round(row[0] * len(worlds)),
                   "tail_value": row[1], "policy_rollouts": row[6]}
                  | {"dark_card_policy": self.dark_card_policy, "dark_attack_probes": dark_attack_probes}
                  | {"information_value": row[7],
                     "information_bonus": row[8],
                     "information_future": row[9],
                     "information_realized": row[10],
                     "information_refusal": row[11],
                     "location_guard_bonus": row[12],
                     "time_traveler_screening_bonus": row[13],
                     "threads_carryover_risk": row[14]}
                  for row in evaluated),
            roles, "factorized", self.evidence_ledger.updates,
            self.evidence_ledger.hard_count, self.evidence_ledger.soft_count,
            evidence_ms, (perf_counter() - started) * 1000 - evidence_ms,
            tuple(self._joint_plan), snapshot.diagnostics.get("reason"),
            snapshot.diagnostics.get("role_candidates", 0),
            snapshot.diagnostics.get("culprit_options", 0),
            belief_culprits=culprits, belief_dark_cards=dark,
            placement_tendencies=tendencies, evaluated_pairs=pairs,
            stop_reason=("time_limit" if deadline is not None
                         and perf_counter() >= deadline else "candidate_limit"),
            rollout_horizon=self.rollout_horizon,
            mastermind_policy_samples=self.mastermind_policy_samples,
            mastermind_policy_aggregation=("per_world_worst_routes_and_marginal_probes"
                                           if self.dark_card_policy == "marginal_guard" else "per_world_worst_routes_and_attack_probes"
                                           if self.dark_card_policy == "adversarial_guard" else "per_world_worst"),
            information_reward_weight=self.information_reward_weight,
            dark_card_policy=self.dark_card_policy, dark_attack_probes=dark_attack_probes,
            dark_guard_proposals=self.dark_card_policy != "sampled" and self.dark_guard_proposals,
            dark_evacuation_candidates=evacuation_count,
            candidate_policy=self.candidate_policy, joint_candidate_diagnostics=joint_diagnostics)
        if self.evidence_ledger.audit is not None:
            self.evidence_ledger.audit.record_samples(
                view, roles, self.factorized_belief._culprits(evidence, witnesses), len(worlds),
                culprit_counts=culprits, dark_counts=dark, placement_tendencies=tendencies,
                witnesses=witnesses, role_assignments=tuple(dict(world.roles) for world in worlds),
                sampled_setups=tuple({"main_plot": world.scenario["main_plot"],
                                      "subplots": tuple(world.scenario["subplots"])} for world in worlds))
        return chosen
