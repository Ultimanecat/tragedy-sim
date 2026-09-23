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
from tragedy_sim.joint_mastermind import JointPlanMastermindAgent
from tragedy_sim.information_value import INFORMATION_ABILITY_KINDS
from tragedy_sim.witness import FsbtxWitnessCompiler, WitnessStrength
from tragedy_sim.ismcts import (IsmctsProtagonistAgent,
                                LegacyIsmctsProtagonistAgent,
                                SurvivalIsmctsProtagonistAgent)
from tragedy_sim.oracle_protagonist import (FullCardOracleProtagonistAgent,
                                             HiddenCardOracleProtagonistAgent)
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.belief import HiddenWorldHypothesis, PublicEvidence
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.search import SearchBudget
from tragedy_sim.witness import FsbtxWitnessMatcher


MASTERMIND_STRATEGIES = ("random", "fixed", "naive", "optimized", "strategic", "joint")
PROTAGONIST_STRATEGIES = ("random", "baseline", "defensive", "risk_aware",
                         "ismcts", "ismcts_legacy", "ismcts_survival",
                         "oracle_cards", "oracle_script", "particle_ensemble")
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
    evidence_ms: float = 0.0
    search_ms: float = 0.0
    evaluated_pairs: int = 0


@dataclass(frozen=True)
class AbilityUsageRecord:
    source: str
    ability: str
    ability_kind: str
    information: bool
    requested: int
    accepted: int
    refused: int
    no_effect: int


@dataclass(frozen=True)
class MatchResult:
    scenario_id: str
    scenario_title: str
    module: str
    loops: int
    difficulty: str
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
    final_belief_setups: tuple[dict[str, Any], ...] = ()
    final_role_candidates: int = 0
    final_true_setup_in_exact_space: bool | None = None
    final_true_setup_hard_compatible: bool | None = None
    protagonist_plays: tuple[ProtagonistPlayRecord, ...] = ()
    protagonist_searches: tuple[ProtagonistSearchRecord, ...] = ()
    protagonist_evidence_seconds: float = 0.0
    protagonist_search_seconds: float = 0.0
    ability_usage: tuple[AbilityUsageRecord, ...] = ()
    protagonist_horizon: str = "day"


def _ability_usage(events: Sequence[dict[str, Any]]) -> tuple[AbilityUsageRecord, ...]:
    counters: dict[tuple[str, str, str], dict[str, int]] = {}
    event_fields = {
        "goodwill_requested": "requested",
        "goodwill_accepted": "accepted",
        "goodwill_refused": "refused",
        "ability_no_effect": "no_effect",
    }
    for event in events:
        field = event_fields.get(str(event.get("kind")))
        source = event.get("source")
        ability = event.get("ability")
        ability_kind = event.get("ability_kind")
        if (field is None or not isinstance(source, str)
                or not isinstance(ability, str)
                or not isinstance(ability_kind, str)):
            continue
        values = counters.setdefault(
            (source, ability, ability_kind),
            {name: 0 for name in event_fields.values()})
        values[field] += 1
    return tuple(
        AbilityUsageRecord(
            source, ability, ability_kind,
            ability_kind in INFORMATION_ABILITY_KINDS,
            values["requested"], values["accepted"], values["refused"],
            values["no_effect"])
        for (source, ability, ability_kind), values in sorted(counters.items())
    )


def _scenario_difficulty(scenario_id: str) -> str:
    if scenario_id.endswith("-very-easy"):
        return "very_easy"
    if scenario_id.endswith("-easy"):
        return "easy"
    return "standard"


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
        for source_field, ui_field in (
                ("key", "choice_key"), ("source", "source"),
                ("ability", "ability"), ("ability_kind", "ability_kind")):
            if isinstance(choice.get(source_field), str):
                ui[ui_field] = choice[source_field]
        for effect in choice.get("effects", ()):
            if not isinstance(effect, dict) or not isinstance(effect.get("kind"), str):
                continue
            ui["effect"] = effect["kind"]
            for field in ("target", "counter", "amount", "day", "excluded"):
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
    if hasattr(policy, "choose_game_action"):
        extra = ({"public_view": (game.protagonist_team_view()
                                 if policy_view is None else policy_view)}
                 if getattr(policy, "uses_public_view", False) else {})
        chosen = policy.choose_game_action(
            participant=participant, game=game.search_clone(), offers=offers,
            **extra)
    else:
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
         protagonist_depth: int | None = None,
         time_limit_ms: int | None = None,
         protagonist_time_limit_ms: int | None = None,
         joint_witness: bool = True,
         disabled_witness_sources: tuple[str, ...] = (),
         oracle_horizon: str = "day",
         mastermind_policy_samples: int = 3,
         information_reward_weight: float = 0.01,
         protagonist_particles: int | None = None) -> MatchResult:
    library = ScenarioLibrary()
    scenario = library.get(scenario_id)
    game = Game(scenario)
    budget = SearchBudget(node_limit=nodes, rollout_depth=depth,
                          time_limit_ms=time_limit_ms, seed=seed)
    mastermind: Any = (
        FullInformationMctsMastermindAgent(budget) if strategy == "naive" else
        OptimizedMctsMastermindAgent(budget) if strategy == "optimized" else
        StrategicMctsMastermindAgent(budget) if strategy == "strategic" else
        JointPlanMastermindAgent(budget) if strategy == "joint" else
        FixedStrategyMastermindAgent(random.Random(f"mastermind:{seed}"))
        if strategy == "fixed" else random.Random(f"mastermind:{seed}"))
    protagonist_budget = SearchBudget(
        node_limit=protagonist_nodes or nodes,
        rollout_depth=protagonist_depth or depth,
        time_limit_ms=protagonist_time_limit_ms, seed=seed)
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
    if protagonist_strategy == "oracle_cards":
        team_ismcts = FullCardOracleProtagonistAgent(protagonist_budget,
                                                    rng_seed=seed,
                                                    rollout_horizon=oracle_horizon)
    elif protagonist_strategy == "oracle_script":
        team_ismcts = HiddenCardOracleProtagonistAgent(protagonist_budget,
                                                      rng_seed=seed,
                                                      rollout_horizon=oracle_horizon)
    elif protagonist_strategy == "particle_ensemble":
        team_ismcts = ParticleEnsembleProtagonistAgent(
            protagonist_budget,
            particle_count=(protagonist_particles if protagonist_particles
                            is not None else max(4, min(24,
                                (protagonist_nodes or nodes) // 8))), rng_seed=seed,
            joint_witness=joint_witness, rollout_horizon=oracle_horizon,
            disabled_witness_sources=disabled_witness_sources,
            mastermind_policy_samples=mastermind_policy_samples,
            information_reward_weight=information_reward_weight)
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
    final_belief_setups: tuple[dict[str, Any], ...] = ()
    final_role_candidates = 0
    final_true_setup_in_exact_space = None
    final_true_setup_hard_compatible = None
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
            if strategy in {"naive", "optimized", "strategic", "joint"}:
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
                                        "ismcts_survival", "oracle_cards",
                                        "oracle_script", "particle_ensemble"}:
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
            if (trace is not None and getattr(trace, "root_actions", ())
                    and trace.fallback != "joint_plan_followup"):
                protagonist_searches.append(ProtagonistSearchRecord(
                    game.state.loop, game.state.round,
                    len(trace.root_actions),
                    tuple(item["visits"] for item in trace.root_actions),
                    trace.belief_source, trace.belief_failure,
                    trace.particles, trace.witnesses, trace.belief_roles,
                    (dict(command), *trace.planned_commands),
                    trace.root_actions,
                    trace.evidence_elapsed_ms, trace.search_elapsed_ms,
                    getattr(trace, "evaluated_pairs", 0)))
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
                final_belief_roles = getattr(trace, "belief_roles", ())
                final_belief_setups = getattr(trace, "belief_setups", ())
            policy = protagonists[command["actor"]]
            if (hasattr(policy, "factorized_belief")
                    and hasattr(policy, "evidence_ledger")
                    and hasattr(policy, "compiler")):
                public_view = game.protagonist_team_view()
                evidence = PublicEvidence.from_view(public_view)
                witnesses = policy.evidence_ledger.update(
                    public_view, policy.compiler)
                solved = policy.factorized_belief.exact_role_map(
                    evidence, witnesses)
                final_role_candidates = solved.compatible_count
                truth = HiddenWorldHypothesis.from_scenario(scenario)
                final_true_setup_hard_compatible = FsbtxWitnessMatcher().matches(
                    truth, witnesses)
                final_true_setup_in_exact_space = (
                    final_true_setup_hard_compatible)
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
        scenario_id=scenario_id, scenario_title=scenario["title"],
        module=scenario["module"], loops=scenario["loops"],
        difficulty=_scenario_difficulty(scenario_id),
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
        final_belief_setups=final_belief_setups,
        final_role_candidates=final_role_candidates,
        final_true_setup_in_exact_space=final_true_setup_in_exact_space,
        final_true_setup_hard_compatible=final_true_setup_hard_compatible,
        protagonist_plays=tuple(protagonist_plays),
        protagonist_searches=tuple(protagonist_searches),
        protagonist_evidence_seconds=protagonist_evidence_ms / 1000,
        protagonist_search_seconds=protagonist_search_ms / 1000,
        ability_usage=_ability_usage(game.state.events),
        protagonist_horizon=(oracle_horizon if protagonist_strategy in {
            "oracle_cards", "oracle_script", "particle_ensemble"} else "day"))


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
    usage = [record for result in results for record in result.ability_usage]
    if usage:
        print("\nability usage | requested | accepted | refused | no effect")
        print(f"all abilities | {sum(x.requested for x in usage):9} | "
              f"{sum(x.accepted for x in usage):8} | "
              f"{sum(x.refused for x in usage):7} | "
              f"{sum(x.no_effect for x in usage):9}")
        information = [item for item in usage if item.information]
        print(f"information   | {sum(x.requested for x in information):9} | "
              f"{sum(x.accepted for x in information):8} | "
              f"{sum(x.refused for x in information):7} | "
              f"{sum(x.no_effect for x in information):9}")


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
    parser.add_argument("--time-limit-ms", type=int,
                        help="mastermind wall-clock cap per search decision")
    parser.add_argument("--protagonist-time-limit-ms", type=int,
                        help="protagonist wall-clock cap per day search")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--strategy", choices=("all", *MASTERMIND_STRATEGIES),
                        default="all")
    parser.add_argument("--protagonists", choices=PROTAGONIST_STRATEGIES,
                        default="baseline")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--progress", action="store_true",
                        help="print one progress line after each completed match")
    parser.add_argument("--disable-joint-witness", action="store_true",
                        help="ablate BTX plot-role soft correlation witnesses")
    parser.add_argument("--disable-witness-source", action="append", default=[],
                        help="ablate one witness source (repeatable)")
    parser.add_argument("--mastermind-policy-samples", type=int, default=3,
                        help="mastermind routes tested per particle world")
    parser.add_argument("--information-reward-weight", type=float, default=0.01,
                        help="small public-belief information tiebreak weight")
    parser.add_argument("--protagonist-horizon", "--oracle-horizon",
                        dest="oracle_horizon",
                        choices=("day", "loop", "match"),
                        default="day",
                        help="stable rollout boundary (particle ensemble supports day/loop)")
    args = parser.parse_args()
    if (args.games < 1 or args.nodes < 1 or args.depth < 1
            or args.protagonist_nodes is not None and args.protagonist_nodes < 1
            or args.protagonist_depth is not None and args.protagonist_depth < 1
            or args.time_limit_ms is not None and args.time_limit_ms < 1
            or args.protagonist_time_limit_ms is not None
            and args.protagonist_time_limit_ms < 1
            or args.mastermind_policy_samples < 1
            or args.information_reward_weight < 0):
        parser.error("games, nodes and depth must be positive")
    if args.protagonists == "particle_ensemble" and args.oracle_horizon == "match":
        parser.error("particle ensemble supports day or loop horizon")
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
                              protagonist_depth=args.protagonist_depth,
                              time_limit_ms=args.time_limit_ms,
                              protagonist_time_limit_ms=args.protagonist_time_limit_ms,
                              joint_witness=not args.disable_joint_witness,
                              disabled_witness_sources=tuple(
                                  args.disable_witness_source),
                              oracle_horizon=args.oracle_horizon,
                              mastermind_policy_samples=
                              args.mastermind_policy_samples,
                              information_reward_weight=
                              args.information_reward_weight)
                results.append(result)
                if args.progress:
                    guess = (f" guess={sum(item.correct for item in result.final_guesses)}"
                             f"/{len(result.final_guesses)}"
                             if result.final_guesses else "")
                    print(f"[{len(results)}/{total}] {scenario} {strategy} "
                          f"seed={result.seed} winner={result.winner} "
                          f"loops={result.loops} difficulty={result.difficulty} "
                          f"decisions={result.decisions} "
                          f"loops_lost={len(result.loop_losses)}{guess} "
                          f"elapsed={result.elapsed_seconds:.3f}s",
                          flush=True)
    if args.json:
        print(json.dumps([asdict(item) for item in results], ensure_ascii=False,
                         indent=2))
    else:
        print(f"scenarios={len(scenarios)} games/strategy={len(scenarios) * args.games} "
              f"protagonists={args.protagonists} nodes={args.nodes} depth={args.depth} "
              f"horizon={args.oracle_horizon} "
              f"mastermind-policies={args.mastermind_policy_samples} "
              f"information-weight={args.information_reward_weight}")
        _print_summary(results)


if __name__ == "__main__":
    main()
