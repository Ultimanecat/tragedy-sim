"""Run fixed-script MCTS-vs-random matches and report reproducible results."""

from __future__ import annotations

import argparse
import random
from statistics import mean
from time import perf_counter

from tragedy_sim import Game
from tragedy_sim.mcts import FullInformationMctsMastermindAgent
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.search import SearchBudget


def play(scenario_id: str, seed: int, nodes: int, depth: int) -> tuple[str, int, float]:
    game = Game(ScenarioLibrary().get(scenario_id))
    mastermind = FullInformationMctsMastermindAgent(SearchBudget(
        node_limit=nodes, rollout_depth=depth, seed=seed))
    protagonists = random.Random(seed)
    decisions = 0
    started = perf_counter()
    while game.winner is None and decisions < 1000:
        offers = game.action_offers(game.controller)
        if not offers:
            raise RuntimeError(f"no legal action at {game.phase_cursor}")
        action = mastermind.search(game) if game.controller == "m" else protagonists.choice(offers)
        game = game.transition(action).game
        decisions += 1
    if game.winner is None:
        raise RuntimeError("match exceeded 1000 decisions")
    return game.winner, decisions, perf_counter() - started


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="official-fs-01-first-script")
    parser.add_argument("--games", type=int, default=3)
    parser.add_argument("--nodes", type=int, default=12)
    parser.add_argument("--depth", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    results = [play(args.scenario, args.seed + index, args.nodes, args.depth)
               for index in range(args.games)]
    mastermind_wins = sum(winner == "mastermind" for winner, _, _ in results)
    print(f"scenario: {args.scenario}; games: {args.games}")
    print(f"mastermind wins: {mastermind_wins}/{args.games} ({mastermind_wins / args.games:.1%})")
    print(f"mean decisions: {mean(item[1] for item in results):.1f}")
    print(f"mean elapsed: {mean(item[2] for item in results):.3f}s")
    for index, result in enumerate(results, 1):
        print(f"{index}: winner={result[0]} decisions={result[1]} elapsed={result[2]:.3f}s")


if __name__ == "__main__":
    main()
