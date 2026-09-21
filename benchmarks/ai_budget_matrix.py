"""Paired, per-decision wall-clock comparisons for FS team planners.

Run serially on an otherwise idle machine. Parallel matches compete for CPU
and invalidate the wall-clock comparison. Ultra is opt-in and intentionally
not part of the default suite.
"""

from __future__ import annotations

import argparse
import json
from statistics import mean

from .ai_self_play import play


BUDGETS = {
    "small": (3000, 96),
    "large": (60000, 384),
    "ultra": (300000, 1024),
}
SCENARIOS = ("official-fs-01-first-script",
             "official-fs-02-prevailing-secrecy")
PLANNERS = ("ismcts_survival", "particle_ensemble")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budgets", nargs="+", choices=tuple(BUDGETS),
                        default=("small", "large"))
    parser.add_argument("--games", type=int, default=3,
                        help="paired seeds per scenario and planner")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--mastermind", choices=("joint", "strategic", "fixed"),
                        default="joint")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.games < 1:
        parser.error("games must be positive")
    results = []
    for budget_name in args.budgets:
        limit_ms, nodes = BUDGETS[budget_name]
        for scenario in SCENARIOS:
            for seed in range(args.seed, args.seed + args.games):
                order = PLANNERS if (seed - args.seed) % 2 == 0 else PLANNERS[::-1]
                for planner in order:
                    match = play(
                        scenario, seed, 24, 12, args.mastermind, planner,
                        protagonist_nodes=nodes, protagonist_depth=12,
                        time_limit_ms=3000,
                        protagonist_time_limit_ms=limit_ms)
                    searches = match.protagonist_searches
                    decision_times = [
                        (item.evidence_ms + item.search_ms) / 1000
                        for item in searches]
                    row = {
                        "budget": budget_name, "limit_ms": limit_ms,
                        "scenario": scenario, "seed": seed,
                        "planner": planner, "winner": match.winner,
                        "elapsed_seconds": round(match.elapsed_seconds, 3),
                        "searches": len(searches),
                        "mean_decision_seconds": (
                            round(mean(decision_times), 3)
                            if decision_times else 0.0),
                        "max_decision_seconds": (
                            round(max(decision_times), 3)
                            if decision_times else 0.0),
                        "mean_evaluated_pairs": (
                            round(mean(item.evaluated_pairs for item in searches), 1)
                            if searches else 0.0),
                    }
                    results.append(row)
                    if not args.json:
                        print(f"{budget_name} {scenario} seed={seed} "
                              f"{planner} {match.winner} "
                              f"game={row['elapsed_seconds']}s "
                              f"decision={row['mean_decision_seconds']}s", flush=True)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for budget_name in args.budgets:
            for planner in PLANNERS:
                selected = [item for item in results
                            if item["budget"] == budget_name
                            and item["planner"] == planner]
                wins = sum(item["winner"] == "protagonists" for item in selected)
                print(f"{budget_name} {planner}: protagonists {wins}/{len(selected)}, "
                      f"mean game {mean(item['elapsed_seconds'] for item in selected):.2f}s")


if __name__ == "__main__":
    main()
