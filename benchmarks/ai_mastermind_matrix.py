"""Paired equal-wall-clock mastermind comparisons against one red planner.

Run serially on an otherwise idle machine. The cap is per search decision;
reported overruns expose searches whose indivisible evaluation exceeded it.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from statistics import mean

from .ai_self_play import play


DEFAULT_SCENARIOS = (
    "official-fs-01-first-script",
    "official-fs-02-prevailing-secrecy",
    "official-btx-02-traditional-ensemble-murder",
    "official-btx-09-those-with-antibodies",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", action="append", dest="scenarios")
    parser.add_argument("--games", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--mastermind-ms", type=int, default=1000)
    parser.add_argument("--mastermind-nodes", type=int, default=96)
    parser.add_argument("--protagonist-ms", type=int, default=1000)
    parser.add_argument("--protagonist-nodes", type=int, default=24)
    parser.add_argument("--depth", type=int, default=8)
    parser.add_argument("--protagonists", choices=("particle_ensemble", "oracle_script"),
                        default="particle_ensemble")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--trace", action="store_true",
                        help="include mastermind plays and loop-loss reasons")
    args = parser.parse_args()
    if min(args.games, args.mastermind_ms, args.mastermind_nodes,
           args.protagonist_ms, args.protagonist_nodes, args.depth) < 1:
        parser.error("games, budgets and depth must be positive")
    scenarios = args.scenarios or DEFAULT_SCENARIOS
    results = []
    for scenario in scenarios:
        for seed in range(args.seed, args.seed + args.games):
            # Alternating execution order reduces systematic warm-cache bias.
            strategies = (("strategic", "joint") if (seed - args.seed) % 2 == 0
                          else ("joint", "strategic"))
            for strategy in strategies:
                match = play(
                    scenario, seed, args.mastermind_nodes, args.depth,
                    strategy, args.protagonists,
                    protagonist_nodes=args.protagonist_nodes,
                    protagonist_depth=args.depth,
                    time_limit_ms=args.mastermind_ms,
                    protagonist_time_limit_ms=args.protagonist_ms)
                row = {
                    "scenario": scenario, "seed": seed,
                    "strategy": strategy, "winner": match.winner,
                    "loops": match.loops, "difficulty": match.difficulty,
                    "final_correct": sum(item.correct for item in match.final_guesses),
                    "final_total": len(match.final_guesses),
                    "loop_losses": len(match.loop_losses),
                    "search_nodes": match.search_nodes,
                    "mastermind_decisions": match.mastermind_decisions,
                    "mastermind_search_seconds": round(match.mastermind_search_seconds, 3),
                    "mastermind_max_decision_seconds": round(
                        match.mastermind_max_decision_seconds, 3),
                    "mastermind_time_overruns": match.mastermind_time_overruns,
                    "protagonist_search_seconds": round(
                        match.protagonist_search_seconds, 3),
                    "elapsed_seconds": round(match.elapsed_seconds, 3),
                }
                if args.trace:
                    row["mastermind_plays"] = [asdict(item)
                                               for item in match.mastermind_plays]
                    row["loop_losses_detail"] = [asdict(item)
                                                 for item in match.loop_losses]
                results.append(row)
                if not args.json:
                    print(f"{scenario} seed={seed} {strategy}: {match.winner}, "
                          f"guess={row['final_correct']}/{row['final_total']}, "
                          f"black={row['mastermind_search_seconds']:.3f}s, "
                          f"max_step={row['mastermind_max_decision_seconds']:.3f}s, "
                          f"overruns={row['mastermind_time_overruns']}, "
                          f"match={row['elapsed_seconds']:.3f}s", flush=True)
                    if args.trace:
                        print("  plays=" + json.dumps(row["mastermind_plays"],
                                                    ensure_ascii=False), flush=True)
                        print("  loop_losses=" + json.dumps(
                            row["loop_losses_detail"], ensure_ascii=False), flush=True)
    if args.json:
        print(json.dumps({"settings": vars(args), "results": results},
                         ensure_ascii=False, indent=2))
    else:
        for strategy in ("strategic", "joint"):
            selected = [row for row in results if row["strategy"] == strategy]
            wins = sum(row["winner"] == "mastermind" for row in selected)
            print(f"{strategy}: black wins {wins}/{len(selected)}, "
                  f"mean match {mean(row['elapsed_seconds'] for row in selected):.2f}s, "
                  f"overruns {sum(row['mastermind_time_overruns'] for row in selected)}")


if __name__ == "__main__":
    main()
