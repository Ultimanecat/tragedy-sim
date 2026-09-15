"""Reproducible C2 MCTS throughput and decision summary benchmark."""

from __future__ import annotations

import argparse
from time import perf_counter

from tragedy_sim import Game
from tragedy_sim.mcts import FullInformationMctsMastermindAgent
from tragedy_sim.scenario import example_scenario
from tragedy_sim.search import SearchBudget


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--module", default="BTX")
    parser.add_argument("--nodes", type=int, default=64)
    parser.add_argument("--depth", type=int, default=24)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    game = Game(example_scenario(args.module))
    agent = FullInformationMctsMastermindAgent(SearchBudget(
        node_limit=args.nodes, rollout_depth=args.depth, seed=args.seed))
    started = perf_counter()
    chosen = agent.search(game)
    elapsed = perf_counter() - started
    trace = agent.last_trace
    print(f"module: {args.module}")
    print(f"selected: {chosen.command}")
    print(f"nodes: {trace.nodes}; iterations: {trace.iterations}; max depth: {trace.max_depth}")
    print(f"elapsed: {elapsed:.3f}s; iterations/s: {trace.iterations / elapsed:.1f}")
    print(f"root unchanged: {game.state.loop == 1 and len(game.history) == 0}")


if __name__ == "__main__":
    main()
