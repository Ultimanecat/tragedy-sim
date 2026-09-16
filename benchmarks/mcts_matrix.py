"""Compare naive and optimized MCTS on one reproducible branch per ruleset."""

from __future__ import annotations

import argparse
from time import perf_counter
import tracemalloc

from tragedy_sim import Game
from tragedy_sim.mcts import FullInformationMctsMastermindAgent
from tragedy_sim.optimized_mcts import OptimizedMctsMastermindAgent
from tragedy_sim.scenario import example_scenario
from tragedy_sim.search import SearchBudget


MODULES = ("FS", "BTX", "MZ", "MC", "HSA", "WM", "AHR", "LL")


def branching_position(module: str) -> Game:
    game = Game(example_scenario(module))
    for _ in range(100):
        actions = game.search_actions(game.controller)
        if game.controller == "m" and len(actions) > 1:
            return game
        if len(actions) != 1:
            raise RuntimeError(f"{module}: reached a non-mastermind branch first")
        game = game.search_transition(actions[0])
    raise RuntimeError(f"{module}: no branching position found")


def measure(module: str, strategy: str, budget: SearchBudget) -> dict[str, object]:
    game = branching_position(module)
    agent_type = (FullInformationMctsMastermindAgent if strategy == "naive"
                  else OptimizedMctsMastermindAgent)
    agent = agent_type(budget)
    branch = len(game.search_actions("m"))
    tracemalloc.start()
    started = perf_counter()
    chosen = agent.search(game)
    elapsed = perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "module": module, "strategy": strategy, "branch": branch,
        "elapsed": elapsed, "peak_mib": peak / 1024 / 1024,
        "iterations": agent.last_trace.iterations,
        "action": chosen.command,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nodes", type=int, default=12)
    parser.add_argument("--depth", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--strategy", choices=("naive", "optimized", "both"),
                        default="both")
    args = parser.parse_args()
    strategies = ("naive", "optimized") if args.strategy == "both" else (args.strategy,)
    budget = SearchBudget(node_limit=args.nodes, rollout_depth=args.depth, seed=args.seed)
    print("module strategy  branch elapsed_ms peak_mib iter action")
    for module in MODULES:
        for strategy in strategies:
            item = measure(module, strategy, budget)
            print(f"{module:>4} {strategy:>9} {item['branch']:>7} "
                  f"{item['elapsed'] * 1000:>10.1f} {item['peak_mib']:>8.2f} "
                  f"{item['iterations']:>4} {item['action']}")


if __name__ == "__main__":
    main()
