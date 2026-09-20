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
from tragedy_sim.witness import FsbtxWitnessCompiler, WitnessStrength
from tragedy_sim.ismcts import (IsmctsProtagonistAgent,
                                LegacyIsmctsProtagonistAgent,
                                SurvivalIsmctsProtagonistAgent)
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.search import SearchBudget


MASTERMIND_STRATEGIES = ("random", "fixed", "naive", "optimized", "strategic")
PROTAGONIST_STRATEGIES = ("random", "baseline", "defensive", "risk_aware",
                         "ismcts", "ismcts_legacy", "ismcts_survival")


@dataclass(frozen=True)
class LoopLossRecord:
    loop: int
    reasons: tuple[str, ...]
    deaths: tuple[str, ...]
    happened_incidents: tuple[tuple[int, str], ...]


@dataclass(frozen=True)
class FinalGuessRecord:
    character: str
    guessed_role: str
    actual_role: str
    correct: bool


@dataclass(frozen=True)
class ProtagonistPlayRecord:
    loop: int
    day: int
    actor: str
    card: str
    target: str
    reason: str | None = None
    belief_source: str | None = None


@dataclass(frozen=True)
class ProtagonistSearchRecord:
    loop: int
    day: int
    candidate_bundles: int
    visits: tuple[int, ...]
    belief_source: str
    belief_failure: str | None
    particles: int
    witnesses: int
    belief_roles: tuple[dict[str, Any], ...]
    selected_bundle: tuple[dict[str, Any], ...]
    candidates: tuple[dict[str, Any], ...]


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
    loop_losses: tuple[LoopLossRecord, ...] = ()
    final_guesses: tuple[FinalGuessRecord, ...] = ()
    known_roles_before_final: int = 0
    cast_size: int = 0
    final_soft_witnesses: tuple[str, ...] = ()
    final_public_deaths: tuple[tuple[int, int, str, str], ...] = ()
    final_belief_roles: tuple[dict[str, Any], ...] = ()
    protagonist_plays: tuple[ProtagonistPlayRecord, ...] = ()
    protagonist_searches: tuple[ProtagonistSearchRecord, ...] = ()
    protagonist_evidence_seconds: float = 0.0
    protagonist_search_seconds: float = 0.0


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
                          actions: Sequence[Any], *, policy_view=None
                          ) -> tuple[Any, dict[str, Any] | None]:
    offers = [_policy_offer(game, action) for action in actions]
    chosen = policy.choose_action(
        participant=participant,
        view=game.view(participant) if policy_view is None else policy_view,
        offers=offers)
    action = actions[next(index for index, offer in enumerate(offers)
                          if offer["id"] == chosen["id"])]
    arguments = chosen.get("arguments")
    return action, arguments if isinstance(arguments, dict) else None


def play(scenario_id: str, seed: int, nodes: int, depth: int,
         strategy: str, protagonist_strategy: str = "baseline", *,
         protagonist_nodes: int | None = None,
         protagonist_depth: int | None = None) -> MatchResult:
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
    protagonist_budget = SearchBudget(
        node_limit=protagonist_nodes or nodes,
        rollout_depth=protagonist_depth or depth, seed=seed)
    team_ismcts = ((LegacyIsmctsProtagonistAgent
                    if protagonist_strategy == "ismcts_legacy" else
                    SurvivalIsmctsProtagonistAgent
                    if protagonist_strategy == "ismcts_survival" else
                    IsmctsProtagonistAgent)(
        protagonist_budget,
        particle_count=max(4, min(64, (protagonist_nodes or nodes) // 4)),
        rng_seed=seed)
        if protagonist_strategy in {"ismcts", "ismcts_legacy", "ismcts_survival"}
        else None)
    protagonists = {
        seat: (team_ismcts if team_ismcts is not None else
               RiskAwareProtagonistAgent(random.Random(f"hero:{seed}:{seat}"))
               if protagonist_strategy == "risk_aware" else
               DefensiveProtagonistAgent(random.Random(f"hero:{seed}:{seat}"))
               if protagonist_strategy == "defensive" else
               BaselineProtagonistAgent(random.Random(f"hero:{seed}:{seat}"))
               if protagonist_strategy == "baseline"
               else random.Random(f"hero:{seed}:{seat}"))
        for seat in "abc"
    }
    decisions = mastermind_decisions = search_nodes = 0
    reason_cursor = 0
    loop_event_cursor = 0
    loop_losses: list[LoopLossRecord] = []
    final_guesses: list[FinalGuessRecord] = []
    known_roles_before_final = 0
    final_soft_witnesses: tuple[str, ...] = ()
    final_public_deaths: tuple[tuple[int, int, str, str], ...] = ()
    final_belief_roles: tuple[dict[str, Any], ...] = ()
    protagonist_plays: list[ProtagonistPlayRecord] = []
    protagonist_searches: list[ProtagonistSearchRecord] = []
    protagonist_evidence_ms = protagonist_search_ms = 0.0
    started = perf_counter()
    while game.winner is None and decisions < 1500:
        actions = game.action_offers(game.controller)
        if not actions:
            raise RuntimeError(f"no legal action at {game.phase_cursor}")
        arguments = None
        if game.controller == "m":
            mastermind_decisions += 1
            if strategy in {"naive", "optimized", "strategic"}:
                action = mastermind.search(game)
                search_nodes += mastermind.last_trace.nodes
            elif strategy == "fixed":
                action, arguments = _choose_policy_action(mastermind, "m", game, actions)
            else:
                action = mastermind.choice(actions)
        else:
            actor = game.controller
            policy = protagonists[actor]
            if protagonist_strategy in {"baseline", "defensive", "risk_aware",
                                        "ismcts", "ismcts_legacy",
                                        "ismcts_survival"}:
                team_policy = bool(getattr(
                    policy, "controls_protagonist_team", False))
                if hasattr(policy, "observe"):
                    policy.observe(
                        viewer="team" if team_policy else actor,
                        records=game.observation_records(
                            "team" if team_policy else actor))
                action, arguments = _choose_policy_action(
                    policy, "team" if team_policy else actor, game, actions,
                    policy_view=(game.protagonist_team_view()
                                 if team_policy else None))
            else:
                action = policy.choice(actions)
        command = {**action.command, **(arguments or {})}
        if command.get("action") == "play" and command.get("actor") != "m":
            trace = getattr(protagonists[command["actor"]], "last_trace", None)
            protagonist_evidence_ms += getattr(
                trace, "evidence_elapsed_ms", 0.0)
            protagonist_search_ms += getattr(trace, "search_elapsed_ms", 0.0)
            protagonist_plays.append(ProtagonistPlayRecord(
                game.state.loop, game.state.round, command["actor"],
                command["card"], command["target"],
                getattr(trace, "fallback", None),
                getattr(trace, "belief_source", None)))
            if (trace is not None and trace.root_actions
                    and trace.fallback != "joint_plan_followup"):
                protagonist_searches.append(ProtagonistSearchRecord(
                    game.state.loop, game.state.round,
                    len(trace.root_actions),
                    tuple(item["visits"] for item in trace.root_actions),
                    trace.belief_source, trace.belief_failure,
                    trace.particles, trace.witnesses, trace.belief_roles,
                    (dict(command), *trace.planned_commands),
                    trace.root_actions))
        # This is the real match trajectory, not a tree rollout.  Real dispatch
        # preserves the complete public journal and per-seat observation
        # checkpoints used by persistent protagonist beliefs.
        game.dispatch(
            command["actor"], command["action"],
            **{key: value for key, value in command.items()
               if key not in {"actor", "action"}})
        new_loop_events = game.state.events[loop_event_cursor:]
        loop_event_cursor = len(game.state.events)
        if any(event.get("kind") == "final_guess_started" for event in new_loop_events):
            known_roles_before_final = sum(
                fact.get("role") == scenario["cast"].get(cid)
                for cid, fact in game.known_roles.items()
                if isinstance(fact, dict))
            final_soft_witnesses = tuple(
                f"{item.kind}:{item.subject}:{item.value}"
                for item in FsbtxWitnessCompiler().compile(game.view(game.controller))
                if item.strength == WitnessStrength.SOFT)
            final_public_deaths = tuple(
                (int(event["loop"]), int(event["round"]),
                 str(event.get("timing", "")), str(event.get("target", "")))
                for event in game.view(game.controller)["events"]
                if event.get("kind") == "character_died")
        if command.get("action") == "guess_all":
            trace = getattr(protagonists[command["actor"]], "last_trace", None)
            if trace is not None:
                final_belief_roles = trace.belief_roles
            for cid, guessed in command["guesses"].items():
                final_guesses.append(FinalGuessRecord(
                    cid, guessed, scenario["cast"][cid],
                    guessed == scenario["cast"][cid]))
        lost = next((event for event in new_loop_events
                     if event.get("kind") == "loop_lost"), None)
        if lost is not None:
            reasons = tuple(game.loss_reasons[reason_cursor:])
            reason_cursor = len(game.loss_reasons)
            deaths = tuple(dict.fromkeys(
                str(event["target"]) for event in new_loop_events
                if event.get("kind") == "character_died" and "target" in event))
            incidents = tuple(
                (int(event["round"]), str(event["incident"]))
                for event in new_loop_events
                if event.get("kind") == "incident_status" and event.get("happened"))
            loop_losses.append(LoopLossRecord(
                int(lost["loop"]), reasons, deaths, incidents))
        decisions += 1
    if game.winner is None:
        raise RuntimeError("match exceeded 1500 decisions")
    return MatchResult(
        scenario_id=scenario_id, module=scenario["module"],
        mastermind_strategy=strategy, protagonist_strategy=protagonist_strategy,
        seed=seed, winner=game.winner, decisions=decisions,
        mastermind_decisions=mastermind_decisions, search_nodes=search_nodes,
        elapsed_seconds=perf_counter() - started,
        loop_losses=tuple(loop_losses), final_guesses=tuple(final_guesses),
        known_roles_before_final=known_roles_before_final,
        cast_size=len(scenario["cast"]),
        final_soft_witnesses=final_soft_witnesses,
        final_public_deaths=final_public_deaths,
        final_belief_roles=final_belief_roles,
        protagonist_plays=tuple(protagonist_plays),
        protagonist_searches=tuple(protagonist_searches),
        protagonist_evidence_seconds=protagonist_evidence_ms / 1000,
        protagonist_search_seconds=protagonist_search_ms / 1000)


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
    parser.add_argument("--protagonist-nodes", type=int)
    parser.add_argument("--protagonist-depth", type=int)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--strategy", choices=("all", *MASTERMIND_STRATEGIES),
                        default="all")
    parser.add_argument("--protagonists", choices=PROTAGONIST_STRATEGIES,
                        default="baseline")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--progress", action="store_true",
                        help="print one progress line after each completed match")
    args = parser.parse_args()
    if (args.games < 1 or args.nodes < 1 or args.depth < 1
            or args.protagonist_nodes is not None and args.protagonist_nodes < 1
            or args.protagonist_depth is not None and args.protagonist_depth < 1):
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
                              strategy, args.protagonists,
                              protagonist_nodes=args.protagonist_nodes,
                              protagonist_depth=args.protagonist_depth)
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
