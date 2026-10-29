"""Diagnostic full-game ability defense on BTX01.

Not a strength certificate: the ability guard is a diagnostic wrapper around the
fair particle protagonist. Run from the repository root:

    python -m benchmarks.ability_guard_probe 8
"""
from __future__ import annotations

import random
import sys
import time

from benchmarks.ai_self_play import _choose_policy_action
from tragedy_sim import Game
from tragedy_sim.ai import FixedStrategyMastermindAgent
from tragedy_sim.day_game.defense_capabilities import (
    build_real_day_plan, find_ability_option, plan_counter_defense,
    schedule_ability_steps)
from tragedy_sim.day_game.defense_value import (
    DefenseCandidate, long_term_slots, select_defense_action)
from tragedy_sim.day_game.threats import public_incidents
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.search import SearchBudget


class DefensePolicy:
    controls_protagonist_team = True
    uses_public_view = True

    def __init__(self, scenario, seed: int, setup_lead: int = 2,
                 target_incident: str = "suicide"):
        self.scenario = scenario
        self.setup_lead = setup_lead
        self.target_incident = target_incident
        self.base = ParticleEnsembleProtagonistAgent(
            SearchBudget(node_limit=24, rollout_depth=12, time_limit_ms=None, seed=seed),
            particle_count=8, rng_seed=seed)
        self.queue = []
        self.pending_transfer = False
        self.planned = 0
        self.fallback = 0

    def _option_offer(self, offers, option):
        for offer in offers:
            params = offer.get("parameters", {})
            if (offer.get("type") == "choose"
                    and params.get("index") == option["index"]
                    and offer.get("actor") == option["actor"]):
                return offer
        return None

    def _setup_steps(self, game, view):
        """Card setup steps for today, or () when nothing is due."""
        rich = view.get("characters", {}).get("rich", {})
        forensic = view.get("characters", {}).get("forensic", {})
        if not rich.get("alive", True) or not forensic.get("alive", True):
            return ()
        # Target selection from the public schedule: the chain exists for the
        # rich character's suicide incident, so prepare only when that kind of
        # incident is close. Other incidents are left to the particle planner.
        target_lead = None
        for incident in public_incidents(view):
            if incident.lead >= 0 and incident.kind == self.target_incident:
                target_lead = incident.lead
                break
        if target_lead is None or target_lead > self.setup_lead:
            return ()
        plan = plan_counter_defense(self.scenario, view, target="rich", need=1)
        if plan.capability is None or plan.blocked_reason:
            return ()
        scheduled = schedule_ability_steps(plan)
        if scheduled.blocked_reason or not scheduled.days:
            return ()
        threshold = int(plan.capability.threshold or 0)
        if int(forensic.get("goodwill", 0)) < threshold:
            return scheduled.days[0]
        if forensic.get("location") != "school":
            return scheduled.days[1] if len(scheduled.days) > 1 else scheduled.days[0]
        return ()

    def _build_queue(self, game, view):
        steps = self._setup_steps(game, view)
        if not steps:
            return []
        built = build_real_day_plan(game, steps,
                                    avoid_targets=("rich", "class_rep"))
        if built.blocked_reason:
            return []
        return [dict(action) for action in built.card_plan]

    def _match_command(self, offers, command):
        for offer in offers:
            params = offer.get("parameters", {})
            if (offer.get("type") == command.get("action")
                    and offer.get("actor") == command.get("actor")
                    and params.get("card") == command.get("card")
                    and params.get("target") == command.get("target")):
                return offer
        return None

    def _hard_threat_active(self, view) -> bool:
        """Whether today's card slots must all go to the modelled hard loss.

        This diagnostic only models the scheduled suicide threat, so setup is
        allowed whenever that threat is not itself today. Other incidents are
        left to the particle planner instead of pre-empting the setup budget.
        """
        for incident in public_incidents(view):
            if incident.kind == self.target_incident:
                return incident.lead <= 0
        return False

    def choose_game_action(self, *, participant, game, offers, public_view=None):
        view = public_view or game.protagonist_team_view()
        if game.state.phase == "protagonists":
            if not self.queue:
                if long_term_slots(hard_threat=self._hard_threat_active(view)) > 0:
                    self.queue = self._build_queue(game, view)
            while self.queue:
                offer = self._match_command(offers, self.queue[0])
                if offer is not None:
                    self.queue.pop(0)
                    self.planned += 1
                    return offer
                self.queue = []
                break
            self.fallback += 1
            return self.base.choose_action(participant="team", view=view, offers=offers)
        if game.state.phase in {"goodwill", "refusal"}:
            rich = view.get("characters", {}).get("rich", {})
            if int(rich.get("paranoia", 0)) > 0:
                option = find_ability_option(
                    game, effect_kind="transfer", source="rich", sink="class_rep")
                if option is not None:
                    offer = self._option_offer(offers, option)
                    if offer is not None:
                        self.pending_transfer = game.state.phase == "goodwill"
                        return offer
        return self.base.choose_action(participant="team", view=view, offers=offers)


def play_one(scenario, seed: int, *, defense: bool, max_decisions: int = 1500,
             decision_limit_ms: int | None = None, setup_lead: int = 2):
    game = Game(scenario)
    if not defense:
        policy = ParticleEnsembleProtagonistAgent(
            SearchBudget(node_limit=24, rollout_depth=12, time_limit_ms=decision_limit_ms,
                         seed=seed),
            particle_count=8, rng_seed=seed)
    else:
        policy = DefensePolicy(scenario, seed, setup_lead=setup_lead)
    black = FixedStrategyMastermindAgent(random.Random(f"black:{seed}"))
    decisions = 0
    slow_decisions = 0
    max_decision_ms = 0.0
    while game.winner is None and decisions < max_decisions:
        actions = game.action_offers(game.controller)
        if not actions:
            break
        started = time.perf_counter()
        if game.controller == "m":
            action, arguments = _choose_policy_action(black, "m", game, actions)
        else:
            action, arguments = _choose_policy_action(
                policy, "team", game, actions,
                policy_view=game.protagonist_team_view())
        elapsed_ms = (time.perf_counter() - started) * 1000
        max_decision_ms = max(max_decision_ms, elapsed_ms)
        if decision_limit_ms is not None and elapsed_ms > decision_limit_ms:
            slow_decisions += 1
        game = game.transition({**action.command, **(arguments or {})}).game
        decisions += 1
    losses = []
    transfers = 0
    rich_deaths = 0
    loss_details = []
    for event in game.state.events:
        if event.get("kind") == "loop_lost":
            losses.append(event)
            loss_details.append((event.get("loop"), event.get("reasons"),
                                 event.get("deaths")))
            if "rich" in (event.get("deaths") or ()):
                rich_deaths += 1
        if event.get("kind") == "goodwill_requested" and event.get("ability_kind") == "transfer":
            transfers += 1
    planned = getattr(policy, "planned", 0)
    fallback = getattr(policy, "fallback", 0)
    planned = planned if isinstance(planned, int) else 0
    fallback = fallback if isinstance(fallback, int) else 0
    return (game.winner, decisions, transfers, rich_deaths,
            tuple(game.loss_reasons), tuple(loss_details),
            planned, fallback, round(max_decision_ms, 1), slow_decisions)


def main():
    scenario = ScenarioLibrary().get("official-btx-01-machina-solar-cogwheel")
    seeds = range(int(sys.argv[1]) if len(sys.argv) > 1 else 10)
    for defense in (False, True):
        wins = 0
        for seed in seeds:
            result = play_one(scenario, seed, defense=defense)
            (winner, decisions, transfers, rich_deaths, loss_reasons, loops,
             planned, fallback, max_ms, slow) = result
            wins += winner == "protagonists"
            print("defense", defense, "seed", seed, "winner", winner,
                  "decisions", decisions, "transfers", transfers,
                  "rich_deaths", rich_deaths, "loops", loops,
                  "loss_reasons", loss_reasons,
                  "planned", planned, "fallback", fallback,
                  "max_decision_ms", max_ms, "slow", slow, flush=True)
        print("SUMMARY defense", defense, "wins", wins, "/", len(seeds), flush=True)


if __name__ == "__main__":
    sys.exit(main())
