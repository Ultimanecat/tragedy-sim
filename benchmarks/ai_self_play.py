"""Reproducible mastermind-AI matches against protagonist baselines."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import random
from statistics import mean
from time import perf_counter
from typing import Any, Sequence

from tragedy_sim import Game
from tragedy_sim.ai import (BaselineProtagonistAgent, DefensiveProtagonistAgent,
                            RiskAwareProtagonistAgent,
                            FixedStrategyMastermindAgent)
from tragedy_sim.mcts import FullInformationMctsMastermindAgent
from tragedy_sim.optimized_mcts import OptimizedMctsMastermindAgent
from tragedy_sim.strategic_mcts import StrategicMctsMastermindAgent
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.search import SearchBudget


MASTERMIND_STRATEGIES = ("random", "fixed", "naive", "optimized", "strategic")
PROTAGONIST_STRATEGIES = ("random", "baseline", "defensive", "risk_aware")


@dataclass(frozen=True)
class MatchResult:
    scenario_id: str
    module: str
    mastermind_strategy: str
    protagonist_strategy: str
    seed: int
    winner: str
    decisions: int
    mastermind_decisions: int
    search_nodes: int
    elapsed_seconds: float


def _policy_offer(game: Game, action: Any) -> dict[str, Any]:
    """Adapt a typed engine offer to the public policy interface."""
    kind = action.kind.removeprefix("core.")
    offer = {
        "id": action.id, "actor": action.actor, "type": kind,
        "parameters": dict(action.parameters), "label": action.label,
    }
    if kind == "choose":
        try:
            choice = game.options(action.actor)[action.parameters["index"] - 1]
        except (IndexError, KeyError, TypeError):
            return offer
        ui: dict[str, Any] = {}
        if isinstance(choice.get("key"), str):
            ui["choice_key"] = choice["key"]
        for effect in choice.get("effects", ()):
            if not isinstance(effect, dict) or not isinstance(effect.get("kind"), str):
                continue
            ui["effect"] = effect["kind"]
            for field in ("target", "counter", "amount"):
                if isinstance(effect.get(field), (str, int)):
                    ui[field] = effect[field]
            break
        if ui:
            offer["ui"] = ui
    return offer


def _choose_policy_action(policy: Any, participant: str, game: Game,
                          actions: Sequence[Any]) -> Any:
    offers = [_policy_offer(game, action) for action in actions]
    chosen = policy.choose_action(
        participant=participant, view=game.view(participant), offers=offers)
    return actions[next(index for index, offer in enumerate(offers)
                        if offer["id"] == chosen["id"])]


def play(scenario_id: str, seed: int, nodes: int, depth: int,
         strategy: str, protagonist_strategy: str = "baseline") -> MatchResult:
    library = ScenarioLibrary()
    scenario = library.get(scenario_id)
    game = Game(scenario)
    budget = SearchBudget(node_limit=nodes, rollout_depth=depth, seed=seed)
    mastermind: Any = (
        FullInformationMctsMastermindAgent(budget) if strategy == "naive" else
        OptimizedMctsMastermindAgent(budget) if strategy == "optimized" else
        StrategicMctsMastermindAgent(budget) if strategy == "strategic" else
        FixedStrategyMastermindAgent(random.Random(f"mastermind:{seed}"))
        if strategy == "fixed" else random.Random(f"mastermind:{seed}"))
    protagonists = {
        seat: (RiskAwareProtagonistAgent(random.Random(f"hero:{seed}:{seat}"))
               if protagonist_strategy == "risk_aware" else
               DefensiveProtagonistAgent(random.Random(f"hero:{seed}:{seat}"))
               if protagonist_strategy == "defensive" else
               BaselineProtagonistAgent(random.Random(f"hero:{seed}:{seat}"))
               if protagonist_strategy == "baseline"
               else random.Random(f"hero:{seed}:{seat}"))
        for seat in "abc"
    }
    decisions = mastermind_decisions = search_nodes = 0
    started = perf_counter()
    while game.winner is None and decisions < 1500:
        actions = game.action_offers(game.controller)
        if not actions:
            raise RuntimeError(f"no legal action at {game.phase_cursor}")
        if game.controller == "m":
            mastermind_decisions += 1
            if strategy in {"naive", "optimized", "strategic"}:
                action = mastermind.search(game)
                search_nodes += mastermind.last_trace.nodes
            elif strategy == "fixed":
                action = _choose_policy_action(mastermind, "m", game, actions)
            else:
                action = mastermind.choice(actions)
        else:
            actor = game.controller
            policy = protagonists[actor]
            action = (_choose_policy_action(policy, actor, game, actions)
                      if protagonist_strategy in {"baseline", "defensive", "risk_aware"}
                      else policy.choice(actions))
        game = game.transition(action).game
        decisions += 1
    if game.winner is None:
        raise RuntimeError("match exceeded 1500 decisions")
    return MatchResult(
        scenario_id=scenario_id, module=scenario["module"],
        mastermind_strategy=strategy, protagonist_strategy=protagonist_strategy,
        seed=seed, winner=game.winner, decisions=decisions,
        mastermind_decisions=mastermind_decisions, search_nodes=search_nodes,
        elapsed_seconds=perf_counter() - started)


def _scenario_ids(args: argparse.Namespace, library: ScenarioLibrary) -> list[str]:
    if args.all_recorded:
        return [item["id"] for item in library.list()
                if item["source"] == "library" and item["module"] in {"FS", "BTX"}]
    if args.module:
        return [item["id"] for item in library.list(args.module)
                if item["source"] == "library"]
    return [args.scenario]


def _print_summary(results: list[MatchResult]) -> None:
    print("strategy | games | mastermind wins | win rate | mean decisions | "
          "mean search nodes | mean elapsed")
    for strategy in MASTERMIND_STRATEGIES:
        selected = [item for item in results if item.mastermind_strategy == strategy]
        if not selected:
            continue
        wins = sum(item.winner == "mastermind" for item in selected)
        print(f"{strategy:9} | {len(selected):5} | {wins:15} | "
              f"{wins / len(selected):8.1%} | {mean(x.decisions for x in selected):14.1f} | "
              f"{mean(x.search_nodes for x in selected):17.1f} | "
              f"{mean(x.elapsed_seconds for x in selected):.3f}s")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="official-fs-01-first-script")
    parser.add_argument("--module", choices=("FS", "BTX"))
    parser.add_argument("--all-recorded", action="store_true")
    parser.add_argument("--games", type=int, default=3)
    parser.add_argument("--nodes", type=int, default=12)
    parser.add_argument("--depth", type=int, default=12)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--strategy", choices=("all", *MASTERMIND_STRATEGIES),
                        default="all")
    parser.add_argument("--protagonists", choices=PROTAGONIST_STRATEGIES,
                        default="baseline")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--progress", action="store_true",
                        help="print one progress line after each completed match")
    args = parser.parse_args()
    if args.games < 1 or args.nodes < 1 or args.depth < 1:
        parser.error("games, nodes and depth must be positive")
    library = ScenarioLibrary()
    scenarios = _scenario_ids(args, library)
    strategies = MASTERMIND_STRATEGIES if args.strategy == "all" else (args.strategy,)
    results: list[MatchResult] = []
    total = len(scenarios) * len(strategies) * args.games
    for scenario in scenarios:
        for strategy in strategies:
            for game_index in range(args.games):
                result = play(scenario, args.seed + game_index, args.nodes, args.depth,
                              strategy, args.protagonists)
                results.append(result)
                if args.progress:
                    print(f"[{len(results)}/{total}] {scenario} {strategy} "
                          f"seed={result.seed} winner={result.winner} "
                          f"decisions={result.decisions} elapsed={result.elapsed_seconds:.3f}s",
                          flush=True)
    if args.json:
        print(json.dumps([asdict(item) for item in results], ensure_ascii=False,
                         indent=2))
    else:
        print(f"scenarios={len(scenarios)} games/strategy={len(scenarios) * args.games} "
              f"protagonists={args.protagonists} nodes={args.nodes} depth={args.depth}")
        _print_summary(results)


if __name__ == "__main__":
    main()
