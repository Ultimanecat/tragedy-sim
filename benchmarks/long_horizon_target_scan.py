"""Scan candidate scenarios for a binding long-horizon defense target.

Plays the fair particle protagonist against a fixed mastermind and records how
each loop was lost, plus the counters that the plot's rule Y watches. Diagnostic
only: small seed counts, not a strength test.

Run from the repository root:

    python -m benchmarks.long_horizon_target_scan --seeds 2
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from benchmarks.ai_self_play import _choose_policy_action
from tragedy_sim import Game
from tragedy_sim.ai import FixedStrategyMastermindAgent
from tragedy_sim.catalog import MODULES, PLOTS
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.search import SearchBudget

CANDIDATES = (
    "official-fs-02-prevailing-secrecy",
    "official-tragic-aiplay-fs-02g",
    "official-tragic-aiplay-btx-01g",
    "official-btx-04-young-womens-battlefield",
    "official-btx-05-lesser-of-two-evils",
    "official-btx-11-neverending-happy-sad-story",
    "official-btx-01-machina-solar-cogwheel",
    "official-btx-02-traditional-ensemble-murder",
)


def watched_counters(scenario):
    """Public counters that rule Y compares at loop end, for reporting."""
    plot = scenario["main_plot"]
    names = PLOTS[plot][0]
    if plot == "protect":
        return [("location", "school")]
    if plot == "avenger":
        return [("location", "city")]
    if plot == "sealed":
        return [("location", "shrine")]
    if plot == "bomb":
        return [("location", "school")]
    if plot == "sign":
        return [("character", "intrigue")]
    return []


def play_one(scenario, seed: int, *, node_limit: int = 24, depth: int = 12):
    game = Game(scenario)
    policy = ParticleEnsembleProtagonistAgent(
        SearchBudget(node_limit=node_limit, rollout_depth=depth, seed=seed),
        particle_count=8, rng_seed=seed)
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

    loops = []
    for event in game.state.events:
        if event.get("kind") != "loop_lost":
            continue
        loops.append({"loop": event.get("loop"), "day": event.get("round")})
    reasons = [reason for reason in game.loss_reasons]
    final = game.protagonist_team_view()
    counters = {}
    for kind, key in watched_counters(scenario):
        if kind == "location":
            counters[key] = final["locations"].get(key)
        else:
            worst = max((c.get("intrigue", 0) for c in final["characters"].values()),
                        default=0)
            counters["max_character_intrigue"] = worst
    happened = [(event.get("round"), event.get("kind"))
                for event in game.state.events
                if event.get("kind") == "incident_status" and event.get("happened")]
    return {
        "winner": game.winner,
        "losses": loops,
        "loss_reasons": reasons,
        "loop": final.get("loop"),
        "day": final.get("round"),
        "counters": counters,
        "incidents_happened": happened,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=2)
    parser.add_argument("--node-limit", type=int, default=24)
    parser.add_argument("--depth", type=int, default=12)
    parser.add_argument("--out", default="references/long-horizon-target-scan.json")
    args = parser.parse_args()
    library = ScenarioLibrary()
    rows = []
    for scenario_id in CANDIDATES:
        scenario = library.get(scenario_id)
        print(f"== {scenario_id} [{MODULES[scenario['module']].name}] "
              f"Y={PLOTS[scenario['main_plot']][0]}", flush=True)
        for seed in range(args.seeds):
            result = play_one(scenario, seed, node_limit=args.node_limit,
                              depth=args.depth)
            row = {"scenario": scenario_id, "seed": seed, **result}
            rows.append(row)
            print("  seed", seed, "winner", result["winner"],
                  "losses", result["losses"],
                  "reasons", result["loss_reasons"],
                  "counters", result["counters"],
                  "incidents", result["incidents_happened"], flush=True)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print("wrote", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
