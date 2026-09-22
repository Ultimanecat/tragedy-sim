"""Paired benchmark for official scenario loop-count difficulties.

All variants of one card use identical seeds and search settings.  Run this
serially on an otherwise idle machine when wall-clock limits are enabled.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from math import sqrt
from statistics import mean
from typing import Any, Sequence

from tragedy_sim.scenario_library import ScenarioLibrary

from .ai_self_play import (MASTERMIND_STRATEGIES, PROTAGONIST_STRATEGIES,
                           MatchResult, play)


DIFFICULTIES = ("standard", "easy", "very_easy")


@dataclass(frozen=True)
class DifficultyGroup:
    base_id: str
    variants: tuple[str, ...]


def difficulty_groups(library: ScenarioLibrary, module: str) -> tuple[DifficultyGroup, ...]:
    ids = {item["id"] for item in library.list(module)
           if item["source"] == "library"}
    groups = []
    for scenario_id in sorted(ids):
        if scenario_id.endswith(("-easy", "-very-easy")):
            continue
        variants = tuple(candidate for candidate in (
            scenario_id, scenario_id + "-easy", scenario_id + "-very-easy")
            if candidate in ids)
        if len(variants) > 1:
            groups.append(DifficultyGroup(scenario_id, variants))
    return tuple(groups)


def summarize(matches: Sequence[MatchResult]) -> dict[str, Any]:
    protagonist_wins = sum(item.winner == "protagonists" for item in matches)
    guesses = [guess for item in matches for guess in item.final_guesses]
    final_matches = [item for item in matches if item.final_guesses]
    low, high = wilson_interval(protagonist_wins, len(matches))
    return {
        "games": len(matches),
        "protagonist_wins": protagonist_wins,
        "protagonist_win_rate": protagonist_wins / len(matches),
        "protagonist_win_rate_95ci": [low, high],
        "mean_lost_loops": mean(len(item.loop_losses) for item in matches),
        "lost_loop_fraction": (
            sum(len(item.loop_losses) for item in matches)
            / sum(item.loops for item in matches)),
        "final_guess_games": sum(bool(item.final_guesses) for item in matches),
        "final_guess_correct": sum(guess.correct for guess in guesses),
        "final_guess_total": len(guesses),
        "final_guess_accuracy": (
            sum(guess.correct for guess in guesses) / len(guesses)
            if guesses else None),
        "true_setup_in_exact_space": sum(
            item.final_true_setup_in_exact_space is True
            for item in final_matches),
        "true_setup_hard_contradictions": sum(
            item.final_true_setup_hard_compatible is False
            for item in final_matches),
        "mean_final_role_candidates": (
            mean(item.final_role_candidates for item in final_matches)
            if final_matches else None),
        "mean_elapsed_seconds": mean(item.elapsed_seconds for item in matches),
    }


def wilson_interval(wins: int, games: int, z: float = 1.959963984540054
                    ) -> tuple[float, float]:
    if games < 1:
        raise ValueError("games must be positive")
    rate = wins / games
    denominator = 1 + z * z / games
    centre = (rate + z * z / (2 * games)) / denominator
    margin = (z / denominator
              * sqrt(rate * (1 - rate) / games + z * z / (4 * games * games)))
    return centre - margin, centre + margin


def paired_outcomes(matches: Sequence[MatchResult]) -> dict[str, int]:
    indexed = {(item.scenario_id.removesuffix("-easy"), item.seed,
                item.difficulty): item for item in matches
               if item.difficulty in {"standard", "easy"}}
    counts = {"both_win": 0, "easy_only_win": 0,
              "standard_only_win": 0, "both_lose": 0}
    bases = {(base, seed) for base, seed, difficulty in indexed
             if difficulty == "standard"
             and (base, seed, "easy") in indexed}
    for base, seed in bases:
        standard_win = indexed[(base, seed, "standard")].winner == "protagonists"
        easy_win = indexed[(base, seed, "easy")].winner == "protagonists"
        key = ("both_win" if standard_win and easy_win else
               "easy_only_win" if easy_win else
               "standard_only_win" if standard_win else "both_lose")
        counts[key] += 1
    counts["pairs"] = len(bases)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--module", choices=("FS", "BTX", "MZ", "MC"),
                        default="BTX")
    parser.add_argument("--scenario-base",
                        help="run one base scenario ID instead of every group")
    parser.add_argument("--games", type=int, default=1,
                        help="paired seeds per difficulty")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--nodes", type=int, default=4)
    parser.add_argument("--depth", type=int, default=6)
    parser.add_argument("--protagonist-nodes", type=int, default=4)
    parser.add_argument("--protagonist-depth", type=int, default=6)
    parser.add_argument("--time-limit-ms", type=int)
    parser.add_argument("--protagonist-time-limit-ms", type=int)
    parser.add_argument("--mastermind", choices=MASTERMIND_STRATEGIES,
                        default="fixed")
    parser.add_argument("--protagonists", choices=PROTAGONIST_STRATEGIES,
                        default="particle_ensemble")
    parser.add_argument("--protagonist-horizon", choices=("day", "loop"),
                        default="day")
    parser.add_argument("--mastermind-policy-samples", type=int, default=3)
    parser.add_argument("--information-reward-weight", type=float, default=0.01)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    positive = (args.games, args.nodes, args.depth, args.protagonist_nodes,
                args.protagonist_depth, args.mastermind_policy_samples)
    if (any(value < 1 for value in positive)
            or args.time_limit_ms is not None and args.time_limit_ms < 1
            or args.protagonist_time_limit_ms is not None
            and args.protagonist_time_limit_ms < 1
            or args.information_reward_weight < 0):
        parser.error("games, budgets and policy samples must be positive")

    library = ScenarioLibrary()
    groups = difficulty_groups(library, args.module)
    if args.scenario_base:
        groups = tuple(group for group in groups
                       if group.base_id == args.scenario_base)
        if not groups:
            parser.error("scenario base has no loop-count difficulty variants")

    matches: list[MatchResult] = []
    total = sum(len(group.variants) for group in groups) * args.games
    for group in groups:
        for game_index in range(args.games):
            seed = args.seed + game_index
            for scenario_id in group.variants:
                result = play(
                    scenario_id, seed, args.nodes, args.depth,
                    args.mastermind, args.protagonists,
                    protagonist_nodes=args.protagonist_nodes,
                    protagonist_depth=args.protagonist_depth,
                    time_limit_ms=args.time_limit_ms,
                    protagonist_time_limit_ms=args.protagonist_time_limit_ms,
                    oracle_horizon=args.protagonist_horizon,
                    mastermind_policy_samples=args.mastermind_policy_samples,
                    information_reward_weight=args.information_reward_weight)
                matches.append(result)
                if not args.json:
                    correct = sum(guess.correct for guess in result.final_guesses)
                    total_guesses = len(result.final_guesses)
                    guess_text = (f" guess={correct}/{total_guesses}"
                                  if total_guesses else "")
                    print(f"[{len(matches)}/{total}] {scenario_id} "
                          f"loops={result.loops} seed={seed} "
                          f"winner={result.winner} "
                          f"lost-loops={len(result.loop_losses)}{guess_text} "
                          f"elapsed={result.elapsed_seconds:.3f}s", flush=True)

    summaries = {
        difficulty: summarize([item for item in matches
                               if item.difficulty == difficulty])
        for difficulty in DIFFICULTIES
        if any(item.difficulty == difficulty for item in matches)
    }
    pairs = paired_outcomes(matches)
    if args.json:
        print(json.dumps({
            "config": vars(args),
            "groups": [asdict(group) for group in groups],
            "summaries": summaries,
            "standard_easy_pairs": pairs,
            "matches": [asdict(item) for item in matches],
        }, ensure_ascii=False, indent=2))
        return

    print("\ndifficulty | games | protagonist wins | win rate (95% CI) | "
          "mean lost loops | lost/available | final guess accuracy | mean elapsed")
    for difficulty in DIFFICULTIES:
        if difficulty not in summaries:
            continue
        item = summaries[difficulty]
        accuracy = (f"{item['final_guess_accuracy']:.1%}"
                    if item["final_guess_accuracy"] is not None else "n/a")
        print(f"{difficulty:10} | {item['games']:5} | "
              f"{item['protagonist_wins']:16} | "
              f"{item['protagonist_win_rate']:8.1%} "
              f"({item['protagonist_win_rate_95ci'][0]:.1%}-"
              f"{item['protagonist_win_rate_95ci'][1]:.1%}) | "
              f"{item['mean_lost_loops']:15.2f} | "
              f"{item['lost_loop_fraction']:14.1%} | {accuracy:20} | "
              f"{item['mean_elapsed_seconds']:.3f}s")
        if item["final_guess_games"]:
            print(f"  final exact MAP: true setup compatible "
                  f"{item['true_setup_in_exact_space']}/"
                  f"{item['final_guess_games']}, hard contradictions="
                  f"{item['true_setup_hard_contradictions']}, mean candidates="
                  f"{item['mean_final_role_candidates']:.1f}")
    print("\nstandard->easy paired outcomes: "
          f"easy-only wins={pairs['easy_only_win']}, "
          f"standard-only wins={pairs['standard_only_win']}, "
          f"both win={pairs['both_win']}, both lose={pairs['both_lose']} "
          f"(pairs={pairs['pairs']})")


if __name__ == "__main__":
    main()
