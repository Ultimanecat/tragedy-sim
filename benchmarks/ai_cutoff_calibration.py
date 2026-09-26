"""Audit whether BTX day-cutoff scores predict eventual match wins.

Every completed nonfinal day contributes one snapshot. Match-weighted metrics
keep long games from dominating; this is diagnostic data, not a fitted value
function. Use paired seeds and varied opponents before tuning search weights.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

from tragedy_sim.belief import FactorizedBeliefState, PublicEvidence
from tragedy_sim.joint_mastermind import _PublicReplyEvaluator
from tragedy_sim.search import SearchBudget
from tragedy_sim.witness import FsbtxWitnessCompiler

from .ai_self_play import play


DEFAULT_SCENARIOS = (
    "official-btx-02-traditional-ensemble-murder",
    "official-btx-09-those-with-antibodies",
)


def weighted_auc(rows: list[dict[str, Any]], field: str, *,
                 label: str = "red_win") -> float | None:
    """Pairwise ranking, with each match carrying equal total weight."""
    positive = [row for row in rows if row[label]]
    negative = [row for row in rows if not row[label]]
    if not positive or not negative:
        return None
    wins = mass = 0.0
    for red in positive:
        for black in negative:
            pair_weight = red["weight"] * black["weight"]
            mass += pair_weight
            wins += pair_weight * (1.0 if red[field] > black[field]
                                   else 0.5 if red[field] == black[field]
                                   else 0.0)
    return wins / mass


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"snapshots": 0, "matches": 0}
    grouped = {(row["scenario"], row["strategy"],
                row.get("protagonist_strategy", "particle_ensemble"), row["seed"])
               for row in rows}
    ordered = sorted(rows, key=lambda row: row["hero_score"])
    exact = [row for row in rows if "exact_correct" in row]
    exact_guess = [row for row in exact
                   if row["outcome_mode"].startswith("final_guess_")]
    bins = []
    for index in range(3):
        selected = ordered[len(ordered) * index // 3:
                           len(ordered) * (index + 1) // 3]
        mass = sum(row["weight"] for row in selected)
        bins.append({
            "score_range": ([round(selected[0]["hero_score"], 3),
                             round(selected[-1]["hero_score"], 3)]
                            if selected else []),
            "red_win_rate": (sum(row["weight"] * row["red_win"]
                                 for row in selected) / mass if mass else None),
            "snapshots": len(selected),
        })
    return {
        "snapshots": len(rows), "matches": len(grouped),
        "hero_score_auc": weighted_auc(rows, "hero_score"),
        "negative_entropy_auc": weighted_auc(rows, "negative_entropy"),
        "score_minus_entropy_auc": weighted_auc(rows, "score_minus_entropy"),
        "hero_score_direct_win_auc": weighted_auc(
            rows, "hero_score", label="direct_red_win"),
        "mean_hero_score": mean(row["hero_score"] for row in rows),
        "exact_snapshots": len(exact),
        "exact_correct_auc": (weighted_auc(exact, "exact_correct_fraction")
                              if exact else None),
        "exact_correct_given_guess_auc": (
            weighted_auc(exact_guess, "exact_correct_fraction")
            if exact_guess else None),
        "exact_guess_snapshots": len(exact_guess),
        "exact_ms_max": max((row["exact_ms"] for row in exact), default=None),
        "tertiles": bins,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", action="append", dest="scenarios")
    parser.add_argument("--games", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--strategy", action="append", choices=("fixed", "joint"))
    parser.add_argument("--protagonist-strategy", default="particle_ensemble",
                        choices=("particle_ensemble", "risk_aware",
                                 "defensive", "baseline"))
    parser.add_argument("--mastermind-nodes", type=int, default=16)
    parser.add_argument("--mastermind-ms", type=int, default=1000)
    parser.add_argument("--protagonist-nodes", type=int, default=8)
    parser.add_argument("--protagonist-ms", type=int, default=1000)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path,
                        help="save complete JSON data for later calibration")
    parser.add_argument("--exact-penultimate", action="store_true",
                        help="also solve red's identity MAP before the final day")
    parser.add_argument("--path-cv", action="store_true",
                        help="fit three outcome heads, holding out complete seeds")
    parser.add_argument("--fixed-work", action="store_true",
                        help="disable wall-clock search cutoffs; node limits still apply")
    parser.add_argument("--repeat-check", action="store_true",
                        help="repeat each match and compare full decision digests")
    args = parser.parse_args()
    if min(args.games, args.mastermind_nodes, args.mastermind_ms,
           args.protagonist_nodes, args.protagonist_ms) < 1:
        parser.error("games and budgets must be positive")
    rows: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []
    for scenario in args.scenarios or DEFAULT_SCENARIOS:
        for seed in range(args.seed, args.seed + args.games):
            for strategy in args.strategy or ("fixed", "joint"):
                snapshots: list[dict[str, Any]] = []
                evaluator = _PublicReplyEvaluator(SearchBudget(), seed)
                compiler = FsbtxWitnessCompiler()
                belief = FactorizedBeliefState(seed=seed)

                def observe(game: Any, event: dict[str, Any]) -> None:
                    view = game.protagonist_team_view()
                    row = {
                        "scenario": scenario, "strategy": strategy,
                        "protagonist_strategy": args.protagonist_strategy,
                        "seed": seed, "loop": game.state.loop,
                        "day_ended": int(event["round"]),
                        "days": game.scenario["days"],
                        "loops": game.scenario["loops"],
                        "hero_score": evaluator._cutoff_value(
                            game, int(event["round"])),
                        "hard_role_entropy": evaluator._role_entropy(view),
                    }
                    if (args.exact_penultimate
                            and game.state.round == game.scenario["days"]):
                        started = perf_counter()
                        solved = belief.exact_role_map(
                            PublicEvidence.from_view(view),
                            compiler.compile(view))
                        guessed = dict(solved.selected.roles) if solved.selected else {}
                        row["exact_correct"] = sum(
                            guessed.get(cid) == role
                            for cid, role in game.scenario["cast"].items())
                        row["exact_total"] = len(game.scenario["cast"])
                        row["exact_correct_fraction"] = (
                            row["exact_correct"] / row["exact_total"])
                        row["exact_ms"] = round(
                            (perf_counter() - started) * 1000, 2)
                    snapshots.append(row)

                play_kwargs = dict(
                    protagonist_nodes=args.protagonist_nodes,
                    time_limit_ms=(None if args.fixed_work
                                   else args.mastermind_ms),
                    protagonist_time_limit_ms=(None if args.fixed_work
                                               else args.protagonist_ms),
                    joint_reply_model="belief", joint_information_weight=0)
                result = play(
                    scenario, seed, args.mastermind_nodes, 8, strategy,
                    args.protagonist_strategy, **play_kwargs,
                    cutoff_observer=observe)
                repeated = (play(scenario, seed, args.mastermind_nodes, 8,
                                 strategy, args.protagonist_strategy,
                                 **play_kwargs) if args.repeat_check else None)
                repeat_stable = (result.decision_digest == repeated.decision_digest
                                 and result.winner == repeated.winner
                                 if repeated is not None else None)
                red_win = result.winner == "protagonists"
                outcome_mode = (
                    "final_guess_win" if red_win and result.final_guesses else
                    "survival_win" if red_win else
                    "final_guess_loss" if result.final_guesses else
                    "other_black_win")
                rows.extend({**row, "red_win": red_win,
                             "direct_red_win": outcome_mode == "survival_win",
                             "outcome_mode": outcome_mode,
                             "negative_entropy": -row["hard_role_entropy"],
                             "score_minus_entropy": row["hero_score"]
                             - 0.02 * row["hard_role_entropy"],
                             "weight": 1 / len(snapshots)}
                            for row in snapshots)
                matches.append({
                    "scenario": scenario, "strategy": strategy,
                    "protagonist_strategy": args.protagonist_strategy,
                    "seed": seed, "red_win": red_win,
                    "outcome_mode": outcome_mode,
                    "snapshots": len(snapshots),
                    "final_correct": sum(item.correct
                                         for item in result.final_guesses),
                    "final_total": len(result.final_guesses),
                    "elapsed_seconds": round(result.elapsed_seconds, 3),
                    "decision_digest": result.decision_digest,
                    "repeat_stable": repeat_stable,
                    "repeat_digest": (repeated.decision_digest
                                      if repeated is not None else None),
                    "repeat_elapsed_seconds": (round(repeated.elapsed_seconds, 3)
                                               if repeated is not None else None),
                })
                if not args.json:
                    print(f"{scenario} {strategy} seed={seed} "
                          f"winner={result.winner} snapshots={len(snapshots)} "
                          f"elapsed={result.elapsed_seconds:.1f}s"
                          + (f" repeat_stable={repeat_stable}"
                             if args.repeat_check else ""), flush=True)
    report = {"schema_version": 1, "budget": {
                  "mode": "fixed_work" if args.fixed_work else "wall_clock",
                  "mastermind_nodes": args.mastermind_nodes,
                  "protagonist_nodes": args.protagonist_nodes,
                  "rollout_depth": 8,
                  "mastermind_ms": None if args.fixed_work else args.mastermind_ms,
                  "protagonist_ms": None if args.fixed_work else args.protagonist_ms,
              }, "config": {
                  "joint_reply_model": "belief", "joint_information_weight": 0,
                  "protagonist_horizon": "day", "mastermind_policy_samples": 3,
                  "information_reward_weight": 0.01,
                  "exact_penultimate": args.exact_penultimate,
              }, "summary": summarize(rows),
              "outcome_counts": {mode: sum(item["outcome_mode"] == mode
                                      for item in matches)
                                 for mode in sorted({item["outcome_mode"]
                                                     for item in matches})},
              "matches": matches, "rows": rows}
    if args.repeat_check:
        report["repeat_check"] = {
            "stable": sum(item["repeat_stable"] is True for item in matches),
            "unstable": sum(item["repeat_stable"] is False for item in matches),
        }
    if args.path_cv:
        from .ai_path_calibration import cross_validated_paths
        report["path_cv"] = cross_validated_paths(rows)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(json.dumps({"budget": report["budget"],
                          "summary": report["summary"],
                          "outcome_counts": report["outcome_counts"],
                          **({"repeat_check": report["repeat_check"]}
                             if args.repeat_check else {}),
                          **({"path_cv": report["path_cv"]} if args.path_cv
                             else {})},
                         ensure_ascii=False, indent=2))
    if args.repeat_check and report["repeat_check"]["unstable"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
