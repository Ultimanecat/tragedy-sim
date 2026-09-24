"""Offline, match-held-out BTX competing-outcome calibration prototype.

The three heads model direct survival, reaching the final guess after failing
to survive, and winning that guess. No fitted coefficient is used by game AI.
"""

from __future__ import annotations

import math
from typing import Any

from .ai_cutoff_calibration import weighted_auc


def _features(row: dict[str, Any], head: str) -> tuple[float, ...]:
    progress = (row["loop"] - 1 + row["day_ended"] / row["days"])
    progress /= row["loops"]
    if head == "guess_win":
        return (-row["hard_role_entropy"], progress)
    return (row["hero_score"], progress)


def _eligible(row: dict[str, Any], head: str) -> bool:
    mode = row["outcome_mode"]
    return (head in {"direct", "overall"} or
            (head == "reach_guess" and mode != "survival_win") or
            (head == "guess_win" and mode.startswith("final_guess_")))


def _target(row: dict[str, Any], head: str) -> bool:
    mode = row["outcome_mode"]
    if head == "overall":
        return bool(row["red_win"])
    return (mode == "survival_win" if head == "direct" else
            mode.startswith("final_guess_") if head == "reach_guess" else
            mode == "final_guess_win")


def _fit(rows: list[dict[str, Any]], head: str):
    selected = [row for row in rows if _eligible(row, head)]
    mass = sum(row["weight"] for row in selected)
    positives = sum(row["weight"] * _target(row, head) for row in selected)
    prior = (positives + 1) / (mass + 2)
    if not selected or positives == 0 or positives == mass:
        return lambda row: prior
    vectors = [_features(row, head) for row in selected]
    means = [sum(row["weight"] * values[index]
                 for row, values in zip(selected, vectors)) / mass
             for index in range(len(vectors[0]))]
    scales = [max(0.1, math.sqrt(sum(
        row["weight"] * (values[index] - means[index]) ** 2
        for row, values in zip(selected, vectors)) / mass))
              for index in range(len(means))]
    features = [tuple((value - center) / scale for value, center, scale
                      in zip(values, means, scales)) for values in vectors]
    intercept = math.log(prior / (1 - prior))
    slopes = [0.0] * len(means)
    for _ in range(200):
        errors = []
        for row, values in zip(selected, features):
            raw = intercept + sum(coef * value
                                  for coef, value in zip(slopes, values))
            probability = 1 / (1 + math.exp(-max(-30, min(30, raw))))
            errors.append(row["weight"] * (probability - _target(row, head)))
        intercept -= 0.2 * sum(errors) / mass
        for index in range(len(slopes)):
            gradient = sum(error * values[index]
                           for error, values in zip(errors, features)) / mass
            slopes[index] -= 0.2 * (gradient + 0.3 * slopes[index])

    def predict(row: dict[str, Any]) -> float:
        values = _features(row, head)
        raw = intercept + sum(coef * (value - center) / scale
                              for coef, value, center, scale
                              in zip(slopes, values, means, scales))
        return 1 / (1 + math.exp(-max(-30, min(30, raw))))

    return predict


def cross_validated_paths(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Hold out complete paired seeds; report proper scores and path support."""
    seeds = {row["seed"] for row in rows}
    if len(seeds) < 2:
        return {"heldout_seeds": len(seeds), "reason": "need at least two seeds"}
    predicted = []
    for seed in sorted(seeds):
        train = [row for row in rows if row["seed"] != seed]
        if not train:
            continue
        models = {head: _fit(train, head)
                  for head in ("direct", "reach_guess", "guess_win", "overall")}
        baseline = (1 + sum(row["weight"] * row["red_win"]
                            for row in train)) / (2 + sum(row["weight"]
                                                          for row in train))
        for row in rows:
            if row["seed"] != seed:
                continue
            direct = models["direct"](row)
            reach = models["reach_guess"](row)
            guess = models["guess_win"](row)
            predicted.append({**row, "path_probability": direct +
                              (1 - direct) * reach * guess,
                              "direct_probability": direct,
                              "guess_reach_probability": reach,
                              "guess_win_probability": guess,
                              "single_probability": models["overall"](row),
                              "baseline_probability": baseline})
    mass = sum(row["weight"] for row in predicted)

    def brier(field: str, subset: list[dict[str, Any]], head: str) -> float | None:
        denominator = sum(row["weight"] for row in subset)
        if not denominator:
            return None
        return sum(row["weight"] * (row[field] - _target(row, head)) ** 2
                   for row in subset) / denominator

    direct_rows = predicted
    reach_rows = [row for row in predicted if _eligible(row, "reach_guess")]
    guess_rows = [row for row in predicted if _eligible(row, "guess_win")]
    outcome_counts = {mode: len({(row["scenario"], row["strategy"],
                                 row.get("protagonist_strategy", "particle_ensemble"),
                                 row["seed"])
                                 for row in predicted if row["outcome_mode"] == mode})
                      for mode in sorted({row["outcome_mode"] for row in predicted})}
    return {
        "heldout_seeds": len(seeds), "matches": sum(outcome_counts.values()),
        "outcome_counts": outcome_counts,
        "path_auc": weighted_auc(predicted, "path_probability"),
        "single_auc": weighted_auc(predicted, "single_probability"),
        "hero_score_auc": weighted_auc(predicted, "hero_score"),
        "path_brier": sum(row["weight"] *
                          (row["path_probability"] - row["red_win"]) ** 2
                          for row in predicted) / mass,
        "single_brier": sum(row["weight"] *
                            (row["single_probability"] - row["red_win"]) ** 2
                            for row in predicted) / mass,
        "constant_brier": sum(row["weight"] *
                              (row["baseline_probability"] - row["red_win"]) ** 2
                              for row in predicted) / mass,
        "direct_brier": brier("direct_probability", direct_rows, "direct"),
        "reach_guess_brier": brier("guess_reach_probability", reach_rows,
                                   "reach_guess"),
        "guess_win_brier": brier("guess_win_probability", guess_rows,
                                 "guess_win"),
        "conditional_guess_win_matches": outcome_counts.get("final_guess_win", 0),
        "conditional_guess_loss_matches": outcome_counts.get("final_guess_loss", 0),
    }
