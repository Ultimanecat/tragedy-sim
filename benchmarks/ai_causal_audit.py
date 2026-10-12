"""Offline causal-evidence and same-root information-boundary comparisons.

Consumes a completed matrix report with replay_text. Private truth is used
only by diagnostic Oracles and validation, never by the fair planner.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from time import perf_counter

from tragedy_sim import Game
from tragedy_sim.belief import FactorizedBeliefState, HiddenWorldHypothesis, PublicEvidence
from tragedy_sim.belief_audit import BeliefAuditTrail
from tragedy_sim.belief_matrix import BeliefMatrixProjection, HardStatus
from tragedy_sim.ismcts import _command
from tragedy_sim.oracle_protagonist import OracleProtagonistAgent
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.replay import ReplayArchive
from tragedy_sim.search import SearchBudget
from tragedy_sim.witness import FsbtxWitnessCompiler, FsbtxWitnessMatcher, PublicEvidenceLedger

from .ai_calibration_matrix import source_digest, write_report
from .ai_self_play import _policy_offer


CAUSAL_SOURCES = frozenset({
    "public_suicide_victim", "public_suicide_prevented_target",
    "public_role_reveal", "immediate_fs_death_loss",
    "public_btx_immediate_death_loss", "public_normal_loop_end_loss",
})


def causal_evidence(view, truth=None):
    """Inspect public facts and culprit domains independently of search nodes."""
    witnesses = FsbtxWitnessCompiler().compile(view)
    evidence = PublicEvidence.from_view(view)
    matcher = FsbtxWitnessMatcher()
    projection = BeliefMatrixProjection.from_view(view, witnesses)
    return {
        "loop": view["loop"], "day": view["round"], "phase": view["phase"],
        "known_roles": view.get("known_roles", {}),
        "private_roles": view.get("protagonist_knowledge", {}).get("roles", {}),
        "hard_role_domains": {cid: [role for role, cell in column.items()
                                   if cell.hard_status != HardStatus.NEVER]
                              for cid, column in projection.roles.items()},
        "plot_candidates": projection.plot_candidates,
        "hard_witnesses": [asdict(w) for w in witnesses if w.strength == "hard"],
        "culprit_options": FactorizedBeliefState()._culprits(evidence, witnesses),
        "causal_witnesses": [asdict(w) for w in witnesses
                             if w.source in CAUSAL_SOURCES],
        "hard_true_setup_compatible": (None if truth is None else
                                      matcher.matches(truth, witnesses)),
    }


def compare_root(game, *, seed=2, nodes=8, worlds=12, time_limit_ms=1000,
                 recorded_bundle=()):
    """Compare plans from exactly the same real position and authorized view.

    Subsequent diagnostic continuations use the same public red policy and
    dynamic fixed black routes for every plan. These are not match win rates.
    """
    view = game.protagonist_team_view()
    offers = [_policy_offer(game, action) for action in game.action_offers(game.controller)]
    position = (game.state.loop, game.state.round)
    rows = []
    budget = SearchBudget(node_limit=nodes, rollout_depth=8,
                          time_limit_ms=time_limit_ms, seed=seed)
    evaluation = OracleProtagonistAgent(reveal_cards=True, budget=budget,
                                       rng_seed=seed, script_aware_rollout=False)
    plans = [("recorded_belief", "day", tuple(recorded_bundle), None)] if recorded_bundle else []
    for name in ("belief", "oracle_script", "oracle_cards"):
        for horizon in ("day", "loop"):
            started = perf_counter()
            if name == "belief":
                policy = ParticleEnsembleProtagonistAgent(
                    budget, particle_count=worlds, rng_seed=seed, rollout_horizon=horizon)
                chosen = policy.choose_action(participant="team", view=view, offers=offers)
                bundle = (_command(chosen), *policy.remaining_card_commands())
            else:
                policy = OracleProtagonistAgent(
                    reveal_cards=name == "oracle_cards", budget=budget,
                    scenario_count=worlds, rng_seed=seed, rollout_horizon=horizon,
                    script_aware_rollout=False)
                chosen = policy.choose_game_action(participant="team", game=game,
                                                  public_view=view, offers=offers)
                bundle = (_command(chosen), *policy.remaining_card_commands())
            plans.append((name, horizon, bundle, {
                "elapsed_ms": (perf_counter() - started) * 1000,
                "fallback": getattr(policy.last_trace, "fallback", None),
                "trace": asdict(policy.last_trace) if policy.last_trace is not None else None,
            }))
    for name, horizon, bundle, search in plans:
        successor = ParticleEnsembleProtagonistAgent._apply_bundle(game, bundle)
        outcomes = []
        if successor is not None:
            for strategy in evaluation._mastermind_strategy_options(game):
                score, survived = evaluation._day_score(
                    successor, *position, mastermind_strategy=strategy)
                evaluation.rollout_horizon = "loop"
                try:
                    loop_score, loop_survived, *_ = evaluation._rollout_score(
                        successor, *position, mastermind_strategy=strategy)
                    evaluation.script_aware_rollout = True
                    known_score, known_survived, *_ = evaluation._rollout_score(
                        successor, *position, mastermind_strategy=strategy)
                finally:
                    evaluation.rollout_horizon = "day"
                    evaluation.script_aware_rollout = False
                outcomes.append({"strategy": strategy, "survived_day": survived, "score": score,
                                 "survived_loop": loop_survived, "loop_score": loop_score})
                outcomes[-1].update(script_continuation_survived_loop=known_survived,
                                    script_continuation_score=known_score)
        rows.append({"policy": name, "horizon": horizon, "bundle": bundle,
                     "legal": successor is not None, "search": search,
                     "true_world_day_outcomes": outcomes})
    return {"loop": position[0], "day": position[1], "comparisons": rows,
            "fresh_belief_reservoir": True,
            "continuation": "same public red rollout and dynamic fixed black routes"}


def audit_row(row, *, compare=False, nodes=8, worlds=12, time_limit_ms=1000,
              belief_log=False, probe_days=None, probe_loops=None, all_days=False):
    archive = ReplayArchive.parse(row["replay_text"])
    game = Game(archive.scenario)
    if game.module not in {"FS", "BTX"}:
        raise ValueError("causal audit currently supports FS/BTX")
    trail = BeliefAuditTrail() if belief_log else None
    ledger = PublicEvidenceLedger(audit=trail)
    compiler = FsbtxWitnessCompiler()
    if trail is not None:
        ledger.update(game.protagonist_team_view(), compiler)
    truth = HiddenWorldHypothesis.from_scenario(archive.scenario)
    suicide_days = {item["day"] for item in archive.scenario["incidents"]
                    if item["kind"] == "suicide"}
    selected_days = (set(probe_days) if probe_days is not None else
                     suicide_days | {day - 1 for day in suicide_days if day > 1})
    selected_loops = None if probe_loops is None else set(probe_loops)
    searches = {(item["loop"], item["day"]): item
                for item in row.get("protagonist_searches", ())}
    losses, roots = [], []
    seen = set()
    for number, command in enumerate(archive.commands, 1):
        position = (game.state.loop, game.state.round)
        if (game.state.phase == "protagonists" and command["actor"] != "m"
                and position not in seen):
            seen.add(position)
            if trail is not None and position in searches:
                view = game.protagonist_team_view()
                sample = searches[position]
                options = causal_evidence(view)["culprit_options"]
                trail.record_samples(view, sample.get("belief_roles", ()), options,
                                     sample.get("particles", 0),
                                     culprit_counts=sample.get("belief_culprits", ()),
                                     witnesses=ledger.witnesses,
                                     dark_counts=sample.get("belief_dark_cards", ()),
                                     placement_tendencies=sample.get("placement_tendencies", ()))
            if ((all_days or game.state.round in selected_days)
                    and (selected_loops is None or game.state.loop in selected_loops)):
                root = {"command_number": number,
                        "evidence": causal_evidence(game.protagonist_team_view(), truth),
                        "public_board": {"characters": game.protagonist_team_view()["characters"],
                                         "locations": game.protagonist_team_view()["locations"]},
                        "recorded_search": searches.get(position)}
                if compare:
                    recorded = searches.get(position, {}).get("selected_bundle", ())
                    root["counterfactual"] = compare_root(
                        game, seed=row.get("seed", 2), nodes=nodes, worlds=worlds,
                        time_limit_ms=time_limit_ms, recorded_bundle=recorded)
                roots.append(root)
        cursor = len(game.state.events)
        game.dispatch(command["actor"], command["action"],
                      **{key: value for key, value in command.items()
                         if key not in {"actor", "action"}})
        if trail is not None:
            ledger.update(game.protagonist_team_view(), compiler)
        if any(event.get("kind") == "loop_lost" for event in game.state.events[cursor:]):
            losses.append({"command_number": number,
                           # A command may already reset the day/start another
                           # loop. Preserve the actual loss event's timepoint.
                           "loss_events": [dict(event) for event in game.state.events[cursor:]
                                           if event.get("kind") == "loop_lost"],
                           "evidence": causal_evidence(game.protagonist_team_view(), truth),
                           "event_tail": game.state.events[max(0, cursor - 6):]})
    return {"scenario": row.get("scenario", archive.scenario["id"]),
            "strategy": row.get("strategy"), "seed": row.get("seed"),
            "winner": game.winner, "losses": losses, "roots": roots,
            "belief_changes": trail.entries if trail is not None else [],
            "belief_text": trail.to_text() if trail is not None else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compare-roots", action="store_true")
    parser.add_argument("--belief-log", type=Path,
                        help="save developer-only Chinese evidence changes and sampled roles")
    parser.add_argument("--strategy", choices=("strategic", "joint"))
    parser.add_argument("--scenario", action="append", help="restrict report rows by scenario ID")
    parser.add_argument("--probe-day", action="append", type=int,
                        help="explicit root days; default: suicide day and preceding day")
    parser.add_argument("--probe-loop", action="append", type=int,
                        help="restrict selected roots to these loops")
    parser.add_argument("--all-days", action="store_true", help="select every daily placement root")
    parser.add_argument("--nodes", type=int, default=8)
    parser.add_argument("--worlds", type=int, default=12)
    parser.add_argument("--time-limit-ms", type=int, default=1000)
    args = parser.parse_args()
    if min(args.nodes, args.worlds, args.time_limit_ms) < 1:
        parser.error("budgets must be positive")
    if any(value < 1 for value in (*(args.probe_day or ()), *(args.probe_loop or ()))):
        parser.error("probe days and loops must be positive")
    if args.all_days and args.probe_day:
        parser.error("choose --all-days or --probe-day")
    raw = args.report.read_bytes()
    source = json.loads(raw)
    selected = [row for row in source["results"]
                if (not args.strategy or row["strategy"] == args.strategy)
                and (not args.scenario or row["scenario"] in args.scenario)]
    if not selected:
        parser.error("no report rows match the selectors")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {"sources": source_digest(), "input": str(args.report),
              "input_sha256": hashlib.sha256(raw).hexdigest(),
              "settings": {"nodes": args.nodes, "worlds": args.worlds,
                           "time_limit_ms": args.time_limit_ms,
                           "scenario": args.scenario, "strategy": args.strategy,
                           "probe_days": args.probe_day, "probe_loops": args.probe_loop,
                           "all_days": args.all_days, "compare_roots": args.compare_roots},
              "progress": {"completed": 0, "planned": len(selected), "complete": False},
              "results": []}
    write_report(args.output, report)
    for row in selected:
        report["results"].append(audit_row(
            row, compare=args.compare_roots, nodes=args.nodes, worlds=args.worlds,
            time_limit_ms=args.time_limit_ms, belief_log=args.belief_log is not None,
            probe_days=args.probe_day, probe_loops=args.probe_loop, all_days=args.all_days))
        report["progress"] = {"completed": len(report["results"]), "planned": len(selected),
                              "complete": len(report["results"]) == len(selected)}
        write_report(args.output, report)
        if args.belief_log:
            args.belief_log.parent.mkdir(parents=True, exist_ok=True)
            args.belief_log.write_text("\n".join(
                f"\n=== {item['scenario']} / {item['strategy']} seed {item['seed']} ===\n"
                + item["belief_text"] for item in report["results"]), encoding="utf-8")
        print(f"{row['strategy']}: {len(report['results'][-1]['losses'])} losses audited", flush=True)


if __name__ == "__main__":
    main()
