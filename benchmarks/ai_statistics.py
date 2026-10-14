"""Small, explicit paired-binomial summaries for exploratory AI comparisons."""

from math import comb, sqrt


def binomial_summary(wins, total):
    if not 0 <= wins <= total:
        raise ValueError("wins must be within the number of matches")
    if not total:
        return {"wins": wins, "matches": total, "win_rate": None, "wilson95": None}
    p = wins / total
    z = 1.959963984540054
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = z * sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return {"wins": wins, "matches": total, "win_rate": p,
            "wilson95": [0.0 if wins == 0 else max(0.0, center - radius),
                         1.0 if wins == total else min(1.0, center + radius)]}


def paired_outcomes(pairs, comparison):
    counts = {"improved": 0, "regressed": 0, "both_red": 0, "both_black": 0}
    for rows in pairs:
        a, b = (rows[key]["winner"] == "protagonists" for key in comparison)
        key = "both_red" if a and b else "both_black" if not a and not b else "improved" if b else "regressed"
        counts[key] += 1
    total = sum(counts.values())
    discordant = counts["improved"] + counts["regressed"]
    k = min(counts["improved"], counts["regressed"])
    probability = min(1.0, 2 * sum(comb(discordant, i) / 2 ** discordant for i in range(k + 1)))
    return {"completed_pairs": total, **counts,
            "paired_only": {comparison[0]: binomial_summary(counts["both_red"] + counts["regressed"], total),
                            comparison[1]: binomial_summary(counts["both_red"] + counts["improved"], total)},
            "exact_paired_binomial_p": probability,
            "statistical_scope": "exploratory_fixed_seed_pairs_no_multiple_testing_correction"}
