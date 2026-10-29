"""Paired comparison: base particle planner vs long-horizon defense agent.

Primary metric is the rule-Y loop-loss count (how often the long accumulation
actually decides a loop), secondary is the match winner. Fixed node budget and
identical mastermind seeds for both arms.

Run from the repository root:

    python -m benchmarks.long_horizon_defense_compare --seeds 3
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from benchmarks.ai_self_play import _choose_policy_action
from tragedy_sim import Game
from tragedy_sim.ai import FixedStrategyMastermindAgent
from tragedy_sim.day_game.protagonist import TwoDayProtagonistAgent
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.search import SearchBudget

SCENARIOS = (
    "official-tragic-aiplay-fs-02g",            # avenger (primary target)
    "official-btx-05-lesser-of-two-evils",      # sealed (secondary target)
    "official-fs-02-prevailing-secrecy",        # protect (control)
)
RULE_Y_REASON = "规则 Y 失败条件"


def make_policy(arm: str, seed: int, node_limit: int, depth: int, scenario=None):
    budget = SearchBudget(node_limit=node_limit, rollout_depth=depth, seed=seed)
    base = ParticleEnsembleProtagonistAgent(budget, particle_count=8, rng_seed=seed)
    if arm == "base":
        return base
    if arm in ("long_horizon_oracle", "long_horizon_oracle_always"):
        return TwoDayProtagonistAgent(
            base=base, particle_count=8,
            oracle_plot=scenario["main_plot"], oracle_cast=scenario["cast"],
            oracle_always_cover=(arm == "long_horizon_oracle_always"))
    return TwoDayProtagonistAgent(base=base, particle_count=8)


def play_one(scenario, seed: int, arm: str, *, node_limit: int, depth: int):
    game = Game(scenario)
    policy = make_policy(arm, seed, node_limit, depth, scenario)
    black = FixedStrategyMastermindAgent(random.Random(f"black:{seed}"))
    while game.winner is None:
        actions = game.action_offers(game.controller)
        if not actions:
            break
        if game.controller == "m":
            action, arguments = _choose_policy_action(black, "m", game, actions)
        else:
            action, arguments = _choose_policy_action(
                policy, "team", game, actions,
                policy_view=game.protagonist_team_view())
        game = game.transition({**action.command, **(arguments or {})}).game
    reasons = list(game.loss_reasons)
    loops_lost = [event for event in game.state.events
                  if event.get("kind") == "loop_lost"]
    return {
        "winner": game.winner,
        "loops_lost": len(loops_lost),
        "rule_y_losses": reasons.count(RULE_Y_REASON),
        "loss_reasons": reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--node-limit", type=int, default=24)
    parser.add_argument("--depth", type=int, default=12)
    parser.add_argument("--arms", default="base,long_horizon,long_horizon_oracle")
    parser.add_argument("--scenarios", default=",".join(SCENARIOS))
    parser.add_argument("--out", default="references/long-horizon-defense-compare.json")
    args = parser.parse_args()
    library = ScenarioLibrary()
    arms = [item.strip() for item in args.arms.split(",") if item.strip()]
    rows = []
    for scenario_id in [item.strip() for item in args.scenarios.split(",") if item.strip()]:
        scenario = library.get(scenario_id)
        print(f"== {scenario_id}", flush=True)
        summaries = {}
        for arm in arms:
            wins = rule_y = loops = 0
            for seed in range(args.seeds):
                result = play_one(scenario, seed, arm,
                                  node_limit=args.node_limit, depth=args.depth)
                rows.append({"scenario": scenario_id, "arm": arm,
                             "seed": seed, **result})
                wins += result["winner"] == "protagonists"
                rule_y += result["rule_y_losses"]
                loops += result["loops_lost"]
                print(f"  {arm:12s} seed {seed} winner {result['winner']:13s}"
                      f" loops_lost {result['loops_lost']}"
                      f" rule_y {result['rule_y_losses']}"
                      f" reasons {result['loss_reasons']}", flush=True)
            summaries[arm] = {"wins": wins, "rule_y_losses": rule_y,
                              "loops_lost": loops}
            print(f"  -> {arm}: wins {wins}/{args.seeds}, "
                  f"rule-Y loop losses {rule_y}", flush=True)
        print(f"  summary {summaries}", flush=True)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print("wrote", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
