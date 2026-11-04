"""Calibrate the three-card day-plan simulation against real loop outcomes.

Plays the fair long-horizon agent against the joint mastermind, records every
first-seat day-plan evaluation (anchor score, chosen score, variant flag), then
joins each evaluation with whether that loop actually ended in a loss (and
whether the loss was rule Y). Diagnostic only.

Run from the repository root:

    python -m benchmarks.day_plan_calibration --seeds 4
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

from benchmarks.ai_self_play import _choose_policy_action
from tragedy_sim import Game
from tragedy_sim.day_game.protagonist import TwoDayProtagonistAgent
from tragedy_sim.joint_mastermind import JointPlanMastermindAgent
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.search import SearchBudget

BUCKETS = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01))


def play_one(scenario, seed: int, *, nodes: int, depth: int,
             sim_black: str = "fixed", sim_nodes: int = 2,
             sim_adversary: bool = False):
    game = Game(scenario)
    base = ParticleEnsembleProtagonistAgent(
        SearchBudget(node_limit=24, rollout_depth=12, seed=seed),
        particle_count=8, rng_seed=seed)
    policy = TwoDayProtagonistAgent(base=base, particle_count=8,
                                    posterior_cover=True,
                                    sim_black=sim_black,
                                    sim_black_nodes=sim_nodes,
                                    sim_adversary=sim_adversary)
    black = JointPlanMastermindAgent(
        SearchBudget(node_limit=nodes, rollout_depth=depth, seed=seed))
    while game.winner is None:
        offers = game.action_offers(game.controller)
        if not offers:
            break
        if game.controller == "m":
            action, arguments = _choose_policy_action(black, "m", game, offers)
        else:
            action, arguments = _choose_policy_action(
                policy, "team", game, offers,
                policy_view=game.protagonist_team_view())
        game = game.transition({**action.command, **(arguments or {})}).game
    lost_loops = [event.get("loop") for event in game.state.events
                  if event.get("kind") == "loop_lost"]
    reasons = list(game.loss_reasons)
    loop_reasons = dict(zip(lost_loops, reasons))
    rows = []
    for entry in policy.plan_log:
        loop = entry["loop"]
        rows.append({
            "seed": seed,
            "loop": loop,
            "round": entry["round"],
            "anchor_score": entry["anchor_score"],
            "chosen_score": entry["chosen_score"],
            "variant": entry["variant"],
            "loop_lost": loop in lost_loops,
            "rule_y_lost": "规则 Y" in str(loop_reasons.get(loop, "")),
            "winner": game.winner,
        })
    return rows


def bucket(score: float) -> str:
    for low, high in BUCKETS:
        if low <= score < high:
            return f"{low:.1f}-{high:.1f}"
    return "?"


def summarize(rows):
    calibration = defaultdict(lambda: {"n": 0, "lost": 0, "rule_y": 0})
    for row in rows:
        key = bucket(row["anchor_score"])
        calibration[key]["n"] += 1
        calibration[key]["lost"] += int(row["loop_lost"])
        calibration[key]["rule_y"] += int(row["rule_y_lost"])
    variants = [row for row in rows if row["variant"]]
    anchors = [row for row in rows if not row["variant"]]
    summary = {
        "evaluations": len(rows),
        "variant_share": round(len(variants) / len(rows), 3) if rows else None,
        "variant_loss_rate": (round(sum(r["loop_lost"] for r in variants)
                                    / len(variants), 3) if variants else None),
        "anchor_loss_rate": (round(sum(r["loop_lost"] for r in anchors)
                                  / len(anchors), 3) if anchors else None),
        "calibration": {
            key: {"n": value["n"],
                  "loss_rate": round(value["lost"] / value["n"], 3),
                  "rule_y_rate": round(value["rule_y"] / value["n"], 3)}
            for key, value in sorted(calibration.items())
        },
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=4)
    parser.add_argument("--scenario", default="official-tragic-aiplay-fs-02g")
    parser.add_argument("--nodes", type=int, default=8)
    parser.add_argument("--depth", type=int, default=12)
    parser.add_argument("--sim-black", choices=("fixed", "joint"), default="fixed")
    parser.add_argument("--sim-nodes", type=int, default=2)
    parser.add_argument("--sim-adversary", action="store_true")
    parser.add_argument("--out", default="references/day-plan-calibration.json")
    args = parser.parse_args()
    library = ScenarioLibrary()
    scenario = library.get(args.scenario)
    rows = []
    for seed in range(args.seeds):
        seed_rows = play_one(scenario, seed, nodes=args.nodes, depth=args.depth,
                             sim_black=args.sim_black,
                             sim_nodes=args.sim_nodes,
                             sim_adversary=args.sim_adversary)
        rows.extend(seed_rows)
        print("seed", seed, "evaluations", len(seed_rows), flush=True)
    summary = summarize(rows)
    payload = {"scenario": args.scenario, "rows": rows, "summary": summary}
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("wrote", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
