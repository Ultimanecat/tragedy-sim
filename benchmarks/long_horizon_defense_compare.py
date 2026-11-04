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
from tragedy_sim.joint_mastermind import JointPlanMastermindAgent
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.search import SearchBudget

SCENARIOS = (
    "official-tragic-aiplay-fs-02g",            # avenger (primary target)
    "official-btx-05-lesser-of-two-evils",      # sealed (secondary target)
    "official-fs-02-prevailing-secrecy",        # protect (control)
)
RULE_Y_REASON = "规则 Y 失败条件"


def make_policy(arm: str, seed: int, node_limit: int, depth: int, scenario=None,
                *, particles: int = 8, agent_particles: int = 8):
    budget = SearchBudget(node_limit=node_limit, rollout_depth=depth, seed=seed)
    base = ParticleEnsembleProtagonistAgent(budget, particle_count=particles,
                                            rng_seed=seed)
    if arm == "base":
        return base
    if arm == "long_horizon_posterior":
        return TwoDayProtagonistAgent(base=base,
                                      particle_count=agent_particles,
                                      posterior_cover=True)
    if arm == "long_horizon_probe_only":
        return TwoDayProtagonistAgent(base=base,
                                      particle_count=agent_particles,
                                      posterior_cover=True,
                                      resync_joint_plan=False)
    if arm == "long_horizon_resync_only":
        return TwoDayProtagonistAgent(base=base,
                                      particle_count=agent_particles,
                                      posterior_cover=True,
                                      probe_information=False)
    if arm == "long_horizon_gate":
        return TwoDayProtagonistAgent(base=base,
                                      particle_count=agent_particles,
                                      posterior_cover=True,
                                      sim_adversary=True,
                                      override_gate_score=0.8)
    if arm == "long_horizon_advsim":
        return TwoDayProtagonistAgent(base=base,
                                      particle_count=agent_particles,
                                      posterior_cover=True,
                                      sim_adversary=True)
    if arm == "long_horizon_strict":
        return TwoDayProtagonistAgent(base=base,
                                      particle_count=agent_particles,
                                      posterior_cover=True,
                                      posterior_floor=0.5,
                                      cover_threshold=0.5,
                                      max_covers_per_day=2)
    if arm == "long_horizon_covers2":
        return TwoDayProtagonistAgent(base=base,
                                      particle_count=agent_particles,
                                      posterior_cover=True,
                                      max_covers_per_day=2)
    if arm == "long_horizon_info":
        return TwoDayProtagonistAgent(base=base,
                                      particle_count=agent_particles,
                                      posterior_cover=True,
                                      info_actions=True)
    if arm == "long_horizon_portfolio":
        return TwoDayProtagonistAgent(base=base,
                                      particle_count=agent_particles,
                                      posterior_cover=True,
                                      portfolio_cover=True)
    if arm == "long_horizon_no_probe":
        return TwoDayProtagonistAgent(base=base,
                                      particle_count=agent_particles,
                                      posterior_cover=True,
                                      probe_information=False)
    if arm == "long_horizon_urgent":
        return TwoDayProtagonistAgent(base=base,
                                      particle_count=agent_particles,
                                      posterior_cover=True,
                                      urgent_cover_only=True)
    if arm == "long_horizon_fast":
        return TwoDayProtagonistAgent(base=base,
                                      particle_count=agent_particles,
                                      posterior_cover=True,
                                      day_plan_value=False)
    if arm == "long_horizon_budget":
        return TwoDayProtagonistAgent(base=base,
                                      particle_count=agent_particles,
                                      posterior_cover=True,
                                      adaptive_budget=True)
    if arm == "long_horizon_mz":
        return TwoDayProtagonistAgent(base=base,
                                      particle_count=agent_particles,
                                      posterior_cover=True,
                                      posterior_floor=0.15,
                                      confidence_floor=0.15)
    if arm == "long_horizon_hygiene":
        return TwoDayProtagonistAgent(base=base,
                                      particle_count=agent_particles,
                                      posterior_cover=False,
                                      max_covers_per_day=2)
    if arm in ("long_horizon_oracle", "long_horizon_oracle_always"):
        return TwoDayProtagonistAgent(
            base=base, particle_count=agent_particles,
            oracle_plot=scenario["main_plot"], oracle_cast=scenario["cast"],
            oracle_always_cover=(arm == "long_horizon_oracle_always"))
    return TwoDayProtagonistAgent(base=base, particle_count=agent_particles)


def make_mastermind(kind: str, seed: int, nodes: int, depth: int):
    if kind == "joint":
        return JointPlanMastermindAgent(
            SearchBudget(node_limit=nodes, rollout_depth=depth, seed=seed))
    return FixedStrategyMastermindAgent(random.Random(f"black:{seed}"))


def play_one(scenario, seed: int, arm: str, *, node_limit: int, depth: int,
             particles: int = 8, agent_particles: int = 8,
             mastermind: str = "fixed", black_nodes: int = 8):
    game = Game(scenario)
    policy = make_policy(arm, seed, node_limit, depth, scenario,
                         particles=particles,
                         agent_particles=agent_particles)
    black = make_mastermind(mastermind, seed, black_nodes, depth)
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
    parser.add_argument("--seed-start", type=int, default=0,
                        help="first seed; seeds run from start to start+count-1")
    parser.add_argument("--node-limit", type=int, default=24)
    parser.add_argument("--depth", type=int, default=12)
    parser.add_argument("--arms", default="base,long_horizon,long_horizon_oracle")
    parser.add_argument("--scenarios", default=",".join(SCENARIOS))
    parser.add_argument("--mastermind", choices=("fixed", "joint"), default="fixed")
    parser.add_argument("--black-nodes", type=int, default=8)
    parser.add_argument("--particles", type=int, default=8,
                        help="particle count for the base planner")
    parser.add_argument("--agent-particles", type=int, default=8,
                        help="particle count for the long-horizon agent belief")
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
            for seed in range(args.seed_start, args.seed_start + args.seeds):
                result = play_one(scenario, seed, arm,
                                  node_limit=args.node_limit, depth=args.depth,
                                  particles=args.particles,
                                  agent_particles=args.agent_particles,
                                  mastermind=args.mastermind,
                                  black_nodes=args.black_nodes)
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
