"""T1 calibration on real self-play day boundaries.

Diagnostic only: compares boundary estimates with the eventual match winner.
Not a strength test and not a certificate.
"""

import argparse
import json
from pathlib import Path
from statistics import mean

from benchmarks import ai_self_play
from benchmarks.ai_calibration_matrix import source_digest, write_report
from tragedy_sim.day_game.final_guess_information import estimate_final_guess_information
from tragedy_sim.day_game.value import (DaySurvivalEvaluator, RandomRolloutEvaluator, boundary_context)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", action="append", dest="scenarios")
    parser.add_argument("--games", type=int, default=1)
    parser.add_argument("--strategy", default="strategic")
    parser.add_argument("--protagonists", default="baseline")
    parser.add_argument("--nodes", type=int, default=8)
    parser.add_argument("--depth", type=int, default=8)
    parser.add_argument("--rollouts", type=int, default=2)
    parser.add_argument("--rollout-steps", type=int, default=512)
    parser.add_argument("--guess-node-limit", type=int, default=5000,
                        help="current best-cast probability node limit; 0 disables")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for name, value in (("games", args.games), ("nodes", args.nodes), ("depth", args.depth),
                        ("rollouts", args.rollouts), ("rollout_steps", args.rollout_steps)):
        if value < 1:
            parser.error(name + " must be positive")
    if args.guess_node_limit < 0:
        parser.error("guess_node_limit must be nonnegative")
    scenarios = args.scenarios or ["official-btx-01-machina-solar-cogwheel"]
    sources = source_digest()
    results = []
    for scenario in scenarios:
        for index in range(args.games):
            seed = args.seed + index
            records = []
            evaluator = RandomRolloutEvaluator(rollouts=args.rollouts, max_steps=args.rollout_steps, seed=seed)
            survival = DaySurvivalEvaluator()

            def observer(game, event):
                position = (int(event.get("loop", game.state.loop)), int(event.get("round", game.state.round)))
                context = boundary_context(game, position)
                fallback = survival.evaluate(context)
                rollout = evaluator.evaluate(context)
                record = dict(position=list(position),
                              day_survival=float(fallback.lower),
                              rollout_lower=str(rollout.lower), rollout_upper=str(rollout.upper),
                              rollout_midpoint=float((rollout.lower + rollout.upper) / 2))
                if args.guess_node_limit:
                    try:
                        guess = estimate_final_guess_information(game, node_limit=args.guess_node_limit)
                    except ValueError:
                        record.update(guess_status="unsupported", guess_probability=None)
                    else:
                        record.update(guess_status=guess.status, guess_probability=guess.probability)
                records.append(record)

            match = ai_self_play.play(scenario, seed, args.nodes, args.depth, args.strategy,
                                      protagonist_strategy=args.protagonists,
                                      cutoff_observer=observer)
            actual = 1.0 if match.winner == "protagonists" else 0.0
            guesses = tuple(getattr(match, "final_guesses", ()) or ())
            guess_accuracy = (sum(entry.correct for entry in guesses) / len(guesses)) if guesses else None
            for record in records:
                record["actual_win"] = actual
                record["day_survival_error"] = (record["day_survival"] - actual) ** 2
                record["rollout_error"] = (record["rollout_midpoint"] - actual) ** 2
                record["final_guess_accuracy"] = guess_accuracy
            results.append(dict(scenario=scenario, seed=seed, winner=match.winner,
                                final_guess_accuracy=guess_accuracy, records=records))
    records = [record for result in results for record in result["records"]]
    day_errors = [record["day_survival_error"] for record in records]
    rollout_errors = [record["rollout_error"] for record in records]
    guess_probs = [record["guess_probability"] for record in records
                   if record.get("guess_probability") is not None]
    guess_accuracies = [result["final_guess_accuracy"] for result in results
                        if result["final_guess_accuracy"] is not None]
    report = dict(sources=sources,
                  note="self-play day-boundary calibration; diagnostic only",
                  settings=dict(games=args.games, strategy=args.strategy, protagonists=args.protagonists,
                                nodes=args.nodes, depth=args.depth, rollouts=args.rollouts,
                                rollout_steps=args.rollout_steps, guess_node_limit=args.guess_node_limit,
                                seed=args.seed),
                  boundaries=len(records),
                  day_survival_brier=mean(day_errors) if day_errors else None,
                  rollout_brier=mean(rollout_errors) if rollout_errors else None,
                  guess_probability_mean=mean(guess_probs) if guess_probs else None,
                  final_guess_accuracy_mean=mean(guess_accuracies) if guess_accuracies else None,
                  results=results)
    if source_digest() != sources:
        raise RuntimeError("sources changed during calibration")
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        write_report(args.output, json.loads(text))
    print(text)


if __name__ == "__main__":
    main()
