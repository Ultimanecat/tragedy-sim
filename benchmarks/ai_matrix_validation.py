"""Parallel, resumable paired matches with mandatory replay audits.

Freeze Python sources, selected scenario contents and search budgets. Audit
private truth only after each match; never supply it to a protagonist policy.
"""

import argparse
from dataclasses import asdict
import faulthandler
import hashlib
import json
import os
from functools import partial
from pathlib import Path
from time import perf_counter, process_time

from tragedy_sim import Game
from tragedy_sim.belief import HiddenWorldHypothesis, PublicEvidence
from tragedy_sim.replay import ReplayArchive
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.witness import FsbtxWitnessCompiler, FsbtxWitnessMatcher

from .ai_belief_matrix_audit import audit_view
from .ai_calibration_matrix import source_digest, write_report
from .ai_cutoff_calibration import match_telemetry
from .ai_self_play import play
from .parallel_jobs import DEFAULT_WORKERS, job_id, peak_memory_mib, run_jobs
from .ai_statistics import paired_outcomes


DEFAULT_SCENARIOS = (
    "official-fs-01-first-script",
    "official-tragic-aiplay-fs-02g",
    "official-tragic-aiplay-btx-02g",
    "official-btx-04-young-womens-battlefield",
    "official-tragic-aiplay-btx-01g-easy",
    "official-btx-06-secret-that-was-kept",
)
VARIANTS = {"legacy": (False, False, "uniform"),
            "matrix": (True, True, "prior"), "uniform": (True, True, "uniform"),
            "partition": (True, True, "prior"), "dark_guard": (True, True, "prior"),
            "dark_guard_scoring": (True, True, "prior"),
            "joint_candidates": (True, True, "prior"), "joint_candidates_guard": (True, True, "prior"),
            "joint_candidates_marginal": (True, True, "prior")}


def scenario_fingerprints(library, scenarios):
    # Preserve mapping order: numeric choice IDs can depend on cast order.
    return {sid: hashlib.sha256(json.dumps(library.get(sid), ensure_ascii=False,
                                         separators=(",", ":")).encode()).hexdigest()
            for sid in scenarios}


def audit_match(match):
    archive = ReplayArchive.parse(match.replay_text)
    if archive.scenario["id"] != match.scenario_id:
        raise AssertionError("Replay scenario does not match evaluation")
    game = Game(archive.scenario)
    truth = HiddenWorldHypothesis.from_scenario(archive.scenario)
    compiler, matcher, seen = FsbtxWitnessCompiler(), FsbtxWitnessMatcher(), set()
    for number, command in enumerate(archive.commands, 1):
        if game.state.phase == "protagonists" and command["actor"] != "m":
            position = (game.state.loop, game.state.round)
            if position not in seen:
                seen.add(position)
                view = game.protagonist_team_view()
                check = audit_view(view, compiler.compile(view), archive.scenario)
                if check["false_hard_exclusions"]:
                    raise AssertionError(f"Matrix excluded truth at command {number}: {check['false_hard_exclusions']}")
        game.dispatch(**command)
        view = game.protagonist_team_view()
        if (not matcher.matches(truth, compiler.compile(view))
                or not PublicEvidence.from_view(view).matches_roles(
                    truth.main_plot, truth.subplots, truth.roles)):
            raise AssertionError(f"Public evidence excluded truth after command {number}")
    if game.winner != match.winner or game.winner != archive.winner:
        raise AssertionError("Replay winner does not match evaluation")
    return {"verified": True, "commands": len(archive.commands), "roots": len(seen),
            "all_hard_compatible": True, "matrix_truth_retained": True}


def paired_summary(results, *, comparison=("legacy", "matrix")):
    pairs = {}
    for row in results:
        pairs.setdefault((row["scenario"], row["seed"]), {})[row["variant"]] = row
    complete = {key: rows for key, rows in pairs.items() if set(comparison).issubset(rows)}
    return {**paired_outcomes(complete.values(), comparison), "comparison": list(comparison),
            "per_scenario": {sid: paired_outcomes([rows for (scenario, _), rows in complete.items() if scenario == sid], comparison)
                             for sid in sorted({sid for sid, _ in pairs})},
            "variants": {v: {"matches": sum(r["variant"] == v for r in results),
                             "red_wins": sum(r["variant"] == v and r["winner"] == "protagonists"
                                             for r in results)}
                         for v in VARIANTS if any(r["variant"] == v for r in results)}}


def _run_match_job(job, *, settings, sources, manifests):
    """A single process owns a match and its replay verification."""
    sid, seed, variant = job
    library = ScenarioLibrary()
    if source_digest() != sources or scenario_fingerprints(library, settings["scenarios"]) != manifests:
        raise RuntimeError("Sources or selected scenarios changed during evaluation")
    matrix, joint, policy = VARIANTS[variant]
    role_policy = "exact_partition" if variant == "partition" else "importance"
    dark_policy = ("marginal_guard" if variant == "joint_candidates_marginal" else "adversarial_guard"
                   if variant.startswith("dark_guard") or variant == "joint_candidates_guard" else "sampled")
    candidate_policy = "joint_threat" if variant.startswith("joint_candidates") else "legacy"
    guard_proposals = variant != "dark_guard_scoring"
    started, cpu_started = perf_counter(), process_time()
    faulthandler.dump_traceback_later(60, repeat=True)
    try:
        match = play(sid, seed, settings["mastermind_nodes"], settings["depth"], "joint", "particle_ensemble",
                     protagonist_nodes=settings["protagonist_nodes"], protagonist_depth=settings["depth"],
                     time_limit_ms=settings["mastermind_ms"],
                     protagonist_time_limit_ms=settings["protagonist_ms"],
                     protagonist_particles=settings["worlds"], matrix_proposals=matrix,
                     joint_culprits=joint, matrix_variant_policy=policy, role_sampling_policy=role_policy,
                     dark_card_policy=dark_policy,
                     dark_guard_proposals=guard_proposals,
                     protagonist_candidate_policy=candidate_policy,
                     joint_reply_model="belief", joint_information_weight=0.02,
                     capture_fallback_contexts=True, capture_replay=True)
        if (match.scenario_id != sid or match.seed != seed
                or match.matrix_proposals_enabled != matrix or match.joint_culprits_enabled != joint
                or match.matrix_variant_policy != policy or match.role_sampling_policy != role_policy
                or match.dark_card_policy != dark_policy or match.protagonist_candidate_policy != candidate_policy):
            raise AssertionError("Returned match configuration differs from planned variant")
        if match.dark_guard_proposals != guard_proposals:
            raise AssertionError("Returned dark proposal policy differs from planned variant")
        audit = audit_match(match)
        if source_digest() != sources or scenario_fingerprints(library, settings["scenarios"]) != manifests:
            raise RuntimeError("Sources or selected scenarios changed during the match")
        return {**asdict(match), **match_telemetry(match), "scenario": sid,
                "strategy": "joint", "variant": variant, "job_id": job_id(job),
                "final_correct": sum(g.correct for g in match.final_guesses),
                "final_total": len(match.final_guesses), "replay_audit": audit,
                "execution": {"worker_pid": os.getpid(), "wall_seconds_including_audit": perf_counter() - started,
                              "cpu_seconds_including_audit": process_time() - cpu_started,
                              "peak_worker_memory_mib": peak_memory_mib()}}
    finally:
        faulthandler.cancel_dump_traceback_later()


def completed_jobs(results, jobs):
    """Validate a non-prefix checkpoint set; holes and completion order are legal."""
    allowed = {job_id(job) for job in jobs}
    completed = {}
    for row in results:
        key = job_id((row["scenario"], row["seed"], row["variant"]))
        if key not in allowed or key in completed or row.get("job_id") != key:
            raise ValueError("resume has duplicate, unknown or mismatched job IDs")
        if not row.get("replay_audit", {}).get("verified"):
            raise ValueError("resume requires audited completed matches")
        completed[key] = row
    return completed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", action="append", dest="scenarios")
    parser.add_argument("--seed", action="append", type=int, dest="seeds")
    parser.add_argument("--variant", action="append", choices=tuple(VARIANTS), dest="variants")
    parser.add_argument("--comparison", choices=("legacy_matrix", "matrix_partition", "matrix_dark_guard",
                                               "matrix_joint_candidates", "guard_joint_candidates", "joint_marginal_guard"), default="legacy_matrix")
    parser.add_argument("--mastermind-nodes", type=int, default=24)
    parser.add_argument("--protagonist-nodes", type=int, default=8)
    parser.add_argument("--worlds", type=int, default=12)
    parser.add_argument("--mastermind-ms", type=int, default=1000)
    parser.add_argument("--protagonist-ms", type=int, default=1000)
    parser.add_argument("--depth", type=int, default=8)
    parser.add_argument("--fixed-work", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help="whole-match process concurrency; default up to 4")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-jobs", type=int)
    args = parser.parse_args()
    if (min(args.mastermind_nodes, args.protagonist_nodes, args.worlds,
            args.mastermind_ms, args.protagonist_ms, args.depth, args.workers) < 1
            or args.max_jobs is not None and args.max_jobs < 1):
        parser.error("budgets and max-jobs must be positive")
    scenarios = list(dict.fromkeys(args.scenarios or DEFAULT_SCENARIOS))
    seeds = list(dict.fromkeys(args.seeds or range(10)))
    comparison = {"matrix_partition": ("matrix", "partition"),
                  "joint_marginal_guard": ("joint_candidates_guard", "joint_candidates_marginal"),
                  "matrix_joint_candidates": ("matrix", "joint_candidates"),
                  "guard_joint_candidates": ("dark_guard", "joint_candidates_guard"),
                  "matrix_dark_guard": ("matrix", "dark_guard"), "legacy_matrix": ("legacy", "matrix")}[args.comparison]
    variants = list(dict.fromkeys(args.variants or comparison))
    library = ScenarioLibrary()
    if any(library.get(sid)["module"] not in {"FS", "BTX"} for sid in scenarios):
        parser.error("matrix evaluation supports FS/BTX")
    settings = {"scenarios": scenarios, "seeds": seeds, "variants": variants,
                "mastermind_nodes": args.mastermind_nodes, "protagonist_nodes": args.protagonist_nodes,
                "worlds": args.worlds, "depth": args.depth,
                "mastermind_ms": None if args.fixed_work else args.mastermind_ms,
                "protagonist_ms": None if args.fixed_work else args.protagonist_ms,
                "mastermind": "joint", "reply_model": "belief", "information_weight": 0.02,
                "horizon": "day", "fixed_work": args.fixed_work, "comparison": list(comparison)}
    sources = source_digest()
    # Fixed work can resume with a different scheduling width. Timed search
    # changes work performed under contention, so keep that resource profile.
    if not args.fixed_work:
        settings["timed_resource_profile"] = {"workers": args.workers}
    manifests = scenario_fingerprints(library, scenarios)
    jobs = [(sid, seed, variant) for i, sid in enumerate(scenarios)
            for j, seed in enumerate(seeds)
            for variant in (variants if (i + j) % 2 == 0 else list(reversed(variants)))]
    if args.resume:
        if not args.output.exists():
            parser.error("resume report does not exist")
        report = json.loads(args.output.read_text(encoding="utf-8"))
        if (report.get("schema_version") != 2 or report.get("sources") != sources
                or report.get("settings") != settings or report.get("scenario_fingerprints") != manifests):
            parser.error("resume requires unchanged sources, scenarios and budgets")
        try:
            completed = completed_jobs(report["results"], jobs)
        except ValueError as error:
            parser.error(str(error))
    else:
        if args.output.exists():
            parser.error("report exists; use --resume or a new output path")
        report = {"schema_version": 2, "sources": sources, "settings": settings,
                  "scenario_fingerprints": manifests, "results": []}
        completed = {}
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        report["results"] = [completed[job_id(job)] for job in jobs if job_id(job) in completed]
        report["progress"] = {"completed": len(completed), "planned": len(jobs),
                              "complete": len(completed) == len(jobs)}
        report["paired_summary"] = paired_summary(report["results"], comparison=comparison)
        write_report(args.output, report)

    failures = {row["job_id"]: row for row in report.get("failed_jobs", ())}
    execution = {"workers": args.workers, "fixed_work": args.fixed_work,
                 "timing_comparable_to_serial": args.workers == 1, "completed": 0}
    report.setdefault("executions", []).append(execution)
    selected = [job for job in jobs if job_id(job) not in completed]
    if args.max_jobs is not None:
        selected = selected[:args.max_jobs]
    started = perf_counter()
    save()
    def validate(job, row):
        if source_digest() != sources or scenario_fingerprints(library, scenarios) != manifests:
            raise RuntimeError("Sources or selected scenarios changed before parent checkpoint")
        completed_jobs((row,), (job,))
    worker = partial(_run_match_job, settings=settings, sources=sources, manifests=manifests)
    errors = []
    try:
        for job, row, error in run_jobs(selected, worker, workers=args.workers, validate=validate):
            sid, seed, variant = job
            key = job_id(job)
            if error is not None:
                failures[key] = {"job_id": key, "scenario": sid, "seed": seed, "variant": variant,
                                 "error": f"{type(error).__name__}: {error}"}
                report["failed_job"] = failures[key]
                errors.append(error)
            else:
                completed[key] = row
                failures.pop(key, None)
                execution["completed"] += 1
                print(f"{len(completed)}/{len(jobs)} {sid} seed={seed} {variant}: "
                      f"{row['winner']}, final={row['final_correct']}/{row['final_total']}, "
                      f"{row['elapsed_seconds']:.3f}s", flush=True)
            report["failed_jobs"] = list(failures.values())
            if failures:
                report["failed_job"] = next(reversed(failures.values()))
            else:
                report.pop("failed_job", None)
            execution["wall_seconds"] = perf_counter() - started
            save()
    finally:
        execution["wall_seconds"] = perf_counter() - started
        save()
    if errors:
        raise errors[0]


if __name__ == "__main__":
    main()
