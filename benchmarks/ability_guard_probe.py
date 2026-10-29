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
from tragedy_sim.day_game.threats import earliest_incident_lead
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.search import SearchBudget


class DefensePolicy:
    controls_protagonist_team = True
    uses_public_view = True

    def __init__(self, scenario, seed: int, setup_lead: int = 2):
        self.scenario = scenario
        self.setup_lead = setup_lead
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

    def _desired_card(self, game, view):
        rich = view.get("characters", {}).get("rich", {})
        forensic = view.get("characters", {}).get("forensic", {})
        if not rich.get("alive", True) or not forensic.get("alive", True):
            return None
        # Public schedule gating: only start the multi-day setup when an
        # incident is close.  Without this the policy burns cards on day 1
        # for a day-5 event and loses to earlier losses.
        lead = earliest_incident_lead(view)
        if lead is None or lead > self.setup_lead:
            return None
        plan = plan_counter_defense(self.scenario, view, target="rich", need=1)
        if plan.capability is None or plan.blocked_reason:
            return None
        threshold = int(plan.capability.threshold or 0)
        if int(forensic.get("goodwill", 0)) < threshold:
            return ("g2", "forensic") if threshold - int(forensic.get("goodwill", 0)) >= 2 else ("g1", "forensic")
        if forensic.get("location") != "school":
            return (("h", "v", "d"), "forensic")
        return None

    def _hard_threat_active(self, view) -> bool:
        lead = earliest_incident_lead(view)
        return lead is not None and lead <= 0

    def choose_game_action(self, *, participant, game, offers, public_view=None):
        view = public_view or game.protagonist_team_view()
        if game.state.phase == "protagonists":
            desired = self._desired_card(game, view)
            hard = self._hard_threat_active(view)
            if desired is not None and long_term_slots(hard_threat=hard) > 0:
                cards, target = desired
                cards = (cards,) if isinstance(cards, str) else cards
                matching = [offer for offer in offers
                            if offer.get("type") == "play"
                            and offer.get("parameters", {}).get("card") in cards
                            and offer.get("parameters", {}).get("target") == target]
                if matching:
                    candidates = [DefenseCandidate(
                        action=offer["id"], survival=0.8,
                        long_term=1.0 if offer in matching else 0.0,
                        information=0.0, final_guess=0.0, expected_loss=0.0)
                        for offer in offers]
                    selection = select_defense_action(candidates, ())
                    chosen_id = selection.chosen.action
                    self.planned += 1
                    return next(offer for offer in offers
                                if offer["id"] == chosen_id)
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
