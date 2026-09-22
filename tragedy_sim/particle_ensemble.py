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
from .ismcts import IsmctsProtagonistAgent, IsmctsTrace, _command, _key
from .oracle_protagonist import OracleProtagonistAgent
from .search import SearchBudget
from .witness import FsbtxWitnessCompiler


class ParticleEnsembleProtagonistAgent(IsmctsProtagonistAgent):
    """Propose Oracle-style bundles per hypothesis, cross-score on all worlds."""

    def __init__(self, budget: SearchBudget | None = None, *,
                 particle_count: int = 12, rng_seed: int = 0,
                 joint_witness: bool = True,
                 rollout_horizon: str = "day",
                 mastermind_policy_samples: int = 3):
        if rollout_horizon not in {"day", "loop"}:
            raise ValueError("particle rollout_horizon must be day or loop")
        if (type(mastermind_policy_samples) is not int
                or mastermind_policy_samples < 1):
            raise ValueError("mastermind_policy_samples must be positive")
        super().__init__(budget or SearchBudget(node_limit=24,
                                                rollout_depth=12,
                                                time_limit_ms=3000),
                         particle_count=particle_count, rng_seed=rng_seed,
                         survival_first=True)
        self.compiler = FsbtxWitnessCompiler(include_joint=joint_witness)
        self.rollout_horizon = rollout_horizon
        self.mastermind_policy_samples = mastermind_policy_samples
        self.oracle = OracleProtagonistAgent(
            reveal_cards=True, budget=self.budget, rng_seed=rng_seed,
            rollout_horizon=rollout_horizon, script_aware_rollout=False)

    @property
    def plan_name(self) -> str:
        return "public_fs_btx_particle_ensemble"

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
        deadline = (None if self.budget.time_limit_ms is None else
                    started + self.budget.time_limit_ms / 1000)
        evidence = PublicEvidence.from_view(view)
        witnesses = self.evidence_ledger.update(view, self.compiler)
        public_hash = hashlib.sha256(json.dumps(
            view, sort_keys=True, ensure_ascii=False, default=str
        ).encode("utf-8")).hexdigest()[:16]
        rng = random.Random(f"{self.budget.seed}:{self.rng_seed}:{public_hash}")
        sampled = self.factorized_belief.sample(
            evidence, witnesses, self.particle_count, rng=rng)
        worlds = tuple(world for index, hypothesis in enumerate(sampled.worlds)
                       if (world := self.determinizer.determinize(
                           hypothesis, evidence, view, rng=rng,
                           history_prior=True,
                           force_history=index % 5 == 0)) is not None)
        if not worlds:
            return self._fallback(participant, view, offers,
                                  sampled.reason or "no_particles",
                                  len(witnesses))
        roles, culprits, dark = self._counts(worlds, evidence)
        discarded = set(view.get("discarded", {}).get("m", ()))
        tendencies = DarkCardBelief.placement_tendencies(
            view.get("events", ()), day=position[1], loop=position[0],
            days=int(view.get("days", 4)),
            targets=[str(item["target"]) for item in view.get("pending", ())
                     if item.get("actor") == "m"],
            cards=[card for card in worlds[0]._deck("m")
                   if card not in discarded])
        evidence_ms = (perf_counter() - started) * 1000

        # The proposal phase may inspect each *sampled* script, but never the
        # true game. All resulting bundles face the same world batch below.
        proposals: dict[str, tuple[dict[str, Any], ...]] = {}
        limit = self.budget.node_limit
        proposal_deadline = (None if deadline is None else
                             started + 0.25 * self.budget.time_limit_ms / 1000)
        index_order = (0, 1, 10, 2, 11, 3, 12, 4, 13, 5, 14, 6,
                       15, 7, 16, 8, 17, 9, 18, 19, 20, 21, 22, 23)
        for round_index in range(max(12, limit)):
            for world_index, world in enumerate(worlds):
                if (proposal_deadline is not None
                        and perf_counter() >= proposal_deadline
                        and len(proposals) >= min(6, limit)):
                    break
                index = index_order[(round_index + world_index) % len(index_order)]
                bundle = self.oracle._bundle(world, view, index)
                if len(bundle) != 3 or _key(bundle[0]) not in offers_by_key:
                    continue
                proposals.setdefault(_key(bundle), bundle)
                if len(proposals) >= limit:
                    break
            if len(proposals) >= limit or (proposal_deadline is not None
                                           and perf_counter() >= proposal_deadline
                                           and len(proposals) >= min(6, limit)):
                break
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
            policy_rollouts = 0
            for world in worlds:
                successor = self._apply_bundle(world, bundle)
                if successor is None:
                    scores = []
                    break
                strategies = self._mastermind_strategies(world)
                policy_outcomes = []
                policy_day_scores = []
                for strategy in strategies:
                    outcome = self.oracle._rollout_score(
                        successor, position[0], position[1],
                        mastermind_strategy=strategy)
                    policy_outcomes.append(outcome[:2])
                    if self.rollout_horizon != "day":
                        policy_day_scores.append(self.oracle._day_score(
                            successor, position[0], position[1],
                            mastermind_strategy=strategy))
                    pairs += 1
                    policy_rollouts += 1
                # The script is uncertain to the protagonists, but the
                # mastermind knows it and may choose any applicable route.
                # Defend against the most dangerous sampled route per world.
                scores.append(min(policy_outcomes,
                                  key=lambda item: (item[1], item[0])))
                if policy_day_scores:
                    day_scores.append(min(
                        policy_day_scores, key=lambda item: (item[1], item[0])))
            if len(scores) != len(worlds):
                continue
            survival = sum(ok for _, ok in scores) / len(scores)
            values = sorted(value for value, _ in scores)
            tail = values[max(0, len(values) // 5 - 1)]
            scarce = sum(item["card"] in {"fm", "g2", "p-1"}
                         for item in bundle)
            mean = sum(values) / len(values) - 0.025 * scarce
            day_survival = (sum(ok for _, ok in day_scores) / len(day_scores)
                            if day_scores else survival)
            day_mean = (sum(value for value, _ in day_scores) / len(day_scores)
                        if day_scores else mean)
            evaluated.append((survival, tail, day_survival, day_mean,
                              mean, bundle, policy_rollouts))
        if not evaluated:
            return self._fallback(participant, view, offers,
                                  "no_common_legal_bundle", len(witnesses))
        best = max(evaluated, key=lambda row: row[:5])
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
                  for row in evaluated),
            roles, "factorized", self.evidence_ledger.updates,
            self.evidence_ledger.hard_count, self.evidence_ledger.soft_count,
            evidence_ms, (perf_counter() - started) * 1000 - evidence_ms,
            tuple(self._joint_plan), sampled.reason,
            sampled.role_candidates, sampled.culprit_options,
            belief_culprits=culprits, belief_dark_cards=dark,
            placement_tendencies=tendencies, evaluated_pairs=pairs,
            stop_reason=("time_limit" if deadline is not None
                         and perf_counter() >= deadline else "candidate_limit"),
            rollout_horizon=self.rollout_horizon,
            mastermind_policy_samples=self.mastermind_policy_samples,
            mastermind_policy_aggregation="per_world_worst")
        return chosen
