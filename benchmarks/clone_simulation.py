"""Small reproducible benchmark for the R3 search clone/transition boundary."""

from __future__ import annotations

import argparse
from copy import deepcopy
from time import perf_counter

from tragedy_sim import Game


def rate(operation, iterations):
    start = perf_counter()
    for _ in range(iterations):
        operation()
    elapsed = perf_counter() - start
    return iterations / elapsed, elapsed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=1000)
    args = parser.parse_args()
    game = Game()
    offer = game.action_offers("m")[0]
    clone_rate, clone_time = rate(game.clone, args.iterations)
    transition_rate, transition_time = rate(lambda: game.transition(offer), args.iterations)
    print(f"clone: {clone_rate:.1f}/s ({clone_time:.3f}s)")
    print(f"transition: {transition_rate:.1f}/s ({transition_time:.3f}s)")
    print(f"shared ruleset: {game.clone().ruleset is game.ruleset}")
    print(f"shared script: {game.clone().script is game.script}")


if __name__ == "__main__":
    main()
