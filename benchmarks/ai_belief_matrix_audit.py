"""Replay-root hard-domain audit and paired recovery ablation.

The stored script is used only after projection/sampling, to validate truth
retention. This audits historical roots, not new self-play win rates.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random
from time import perf_counter

from tragedy_sim import Game
from tragedy_sim.belief import FactorizedBeliefState, PublicEvidence
from tragedy_sim.belief_matrix import BeliefMatrixProjection, HardStatus, role_domains
from tragedy_sim.replay import ReplayArchive
from tragedy_sim.witness import FsbtxWitnessCompiler

from .ai_calibration_matrix import source_digest, write_report


def audit_view(view, witnesses, truth=None):
    started = perf_counter()
    projection = BeliefMatrixProjection.from_view(view, witnesses)
    milliseconds = (perf_counter() - started) * 1000
    _, unary, _ = role_domains(view, witnesses)
    incident_options = FactorizedBeliefState()._culprits(PublicEvidence.from_view(view), witnesses)
    allowed = lambda column: tuple(sorted(value for value, cell in column.items()
                                         if cell.hard_status != HardStatus.NEVER))
    matrix_options = {int(day): allowed(column) for day, column in projection.culprits.items()}
    result = {
        "loop": projection.loop, "day": projection.day, "projection_ms": milliseconds,
        "unary_role_cells": sum(map(len, unary.values())),
        "propagated_role_cells": sum(len(allowed(column)) for column in projection.roles.values()),
        "plot_candidates": len(projection.plot_candidates),
        "culprit_options": matrix_options, "culprit_sampler_equal": matrix_options == incident_options,
        "witnesses": [asdict(w) for w in witnesses],
        "false_hard_exclusions": [],
    }
    if truth is not None:
        # Diagnostic validation only: never send this script to domain builders.
        for cid, role in truth["cast"].items():
            if projection.roles[cid][role].hard_status == HardStatus.NEVER:
                result["false_hard_exclusions"].append(["role", cid, role])
        for incident in truth["incidents"]:
            day, cid = str(incident["day"]), incident["culprit"]
            if projection.culprits[day][cid].hard_status == HardStatus.NEVER:
                result["false_hard_exclusions"].append(["culprit", day, cid])
    return result


def audit_row(row, *, worlds=0, seed=0):
    archive = ReplayArchive.parse(row["replay_text"])
    game = Game(archive.scenario)
    compiler = FsbtxWitnessCompiler()
    states = {enabled: FactorizedBeliefState(seed=seed, matrix_recovery=enabled)
              for enabled in (False, True)}
    roots, seen = [], set()
    for number, command in enumerate(archive.commands, 1):
        position = (game.state.loop, game.state.round)
        if game.state.phase == "protagonists" and command["actor"] != "m" and position not in seen:
            seen.add(position)
            view = game.protagonist_team_view()
            witnesses = compiler.compile(view)
            root = audit_view(view, witnesses, archive.scenario)
            root["command_number"] = number
            if worlds:
                samples, summaries = {}, {}
                evidence = PublicEvidence.from_view(view)
                for enabled, state in states.items():
                    started = perf_counter()
                    sample = state.sample(evidence, witnesses, worlds,
                                          rng=random.Random(seed + number))
                    samples[enabled] = sample
                    summaries[str(enabled).lower()] = {
                        "ms": (perf_counter() - started) * 1000,
                        "worlds": len(sample.worlds), "role_candidates": sample.role_candidates,
                        "reason": sample.reason, "recovery_attempts": state.matrix_recovery_attempts,
                        "recovery_worlds": state.matrix_recovery_worlds,
                    }
                root["recovery_ablation"] = summaries
                root["paired_samples_equal"] = samples[False] == samples[True]
            roots.append(root)
        game.dispatch(**command)
    return {"scenario": row.get("scenario", archive.scenario["id"]),
            "strategy": row.get("strategy"), "seed": row.get("seed"),
            "historical_winner": archive.winner, "roots": roots,
            "replay_verified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--worlds", type=int, default=0, help="0 disables paired sampling")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if args.worlds < 0:
        parser.error("--worlds must be non-negative")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": 1, "source_digest": source_digest(),
              "settings": {"worlds": args.worlds, "seed": args.seed},
              "sources": [], "complete": False, "results": []}
    write_report(args.output, report)
    for path in args.reports:
        raw = path.read_bytes()
        report["sources"].append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()})
        rows = json.loads(raw)["results"]
        for row in rows:
            report["results"].append(audit_row(row, worlds=args.worlds, seed=args.seed))
            write_report(args.output, report)
            print(f"Audited {row.get('scenario')} / {row.get('strategy')}", flush=True)
    report["complete"] = True
    write_report(args.output, report)


if __name__ == "__main__":
    main()
