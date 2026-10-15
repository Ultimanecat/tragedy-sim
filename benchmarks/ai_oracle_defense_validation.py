"""Paired fixed-work oracle defense matches, with audited resumable reports.

BTX's oracle final answer is excluded from action wins. Search node counts
are candidate limits, not equal CPU budgets; timings/work remain reported.
"""

import argparse
from dataclasses import asdict
from functools import partial
import json
from pathlib import Path
from time import perf_counter

from tragedy_sim.scenario_library import ScenarioLibrary
from .ai_calibration_matrix import source_digest, write_report
from .ai_matrix_validation import audit_match, completed_jobs, paired_summary, scenario_fingerprints
from .ai_self_play import play
from .parallel_jobs import DEFAULT_WORKERS, job_id, run_jobs


def run_match(job, *, settings, sources):
    sid, seed, variant = job
    policy = settings["candidate"] if settings.get("skill_ablation") else variant
    skill_information = variant if settings.get("skill_ablation") else settings.get("skill_information", "script")
    if source_digest() != sources:
        raise RuntimeError("evaluation sources changed")
    match = play(sid, seed, settings["black_nodes"], 8, "joint", settings["oracle"],
                 protagonist_nodes=settings["red_nodes"], joint_reply_model="belief",
                 oracle_candidate_policy=policy, oracle_skill_information=skill_information, capture_replay=True)
    if match.oracle_candidate_policy != policy or match.oracle_skill_information != skill_information:
        raise AssertionError("returned oracle configuration differs from planned job")
    audit = audit_match(match)
    if source_digest() != sources:
        raise RuntimeError("evaluation sources changed")
    return {**asdict(match), "scenario": sid, "variant": variant, "job_id": job_id(job),
            "replay_audit": audit, "action_win": match.winner == "protagonists" and not match.final_guesses,
            "final_correct": sum(g.correct for g in match.final_guesses),
            "final_total": len(match.final_guesses)}


def summarize(rows, comparison=("legacy", "joint_threat")):
    action_rows = [{**r, "winner": "protagonists" if r["action_win"] else "mastermind"} for r in rows]
    summary = paired_summary(action_rows, comparison=comparison)
    summary["variants"] = {v: {"matches": sum(r["variant"] == v for r in action_rows),
                                "red_wins": sum(r["variant"] == v and r["action_win"] for r in action_rows)}
                           for v in sorted({r["variant"] for r in action_rows})}
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", action="append", required=True)
    parser.add_argument("--seed", action="append", type=int)
    parser.add_argument("--oracle", choices=("oracle_cards", "oracle_script"), default="oracle_script")
    parser.add_argument("--black-nodes", type=int, default=4)
    parser.add_argument("--red-nodes", type=int, default=4)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-jobs", type=int)
    parser.add_argument("--baseline", choices=("legacy", "joint_threat"), default="legacy")
    parser.add_argument("--candidate", choices=("joint_threat", "joint_counterexample"), default="joint_threat")
    parser.add_argument("--skill-information", choices=("public", "script"), default="script")
    parser.add_argument("--skill-ablation", action="store_true", help="compare public/script skill context on --candidate")
    args = parser.parse_args()
    if not args.skill_ablation and args.baseline == args.candidate:
        parser.error("comparison policies must differ")
    if min(args.black_nodes, args.red_nodes, args.workers) < 1 or args.max_jobs is not None and args.max_jobs < 1:
        parser.error("budgets, workers and max-jobs must be positive")
    scenarios = list(dict.fromkeys(args.scenario))
    library = ScenarioLibrary()
    if any(library.get(sid)["module"] not in {"FS", "BTX"} for sid in scenarios):
        parser.error("FS/BTX required")
    settings = {"scenarios": scenarios, "seeds": sorted(set(args.seed or range(10))),
                "oracle": args.oracle, "black_nodes": args.black_nodes, "red_nodes": args.red_nodes,
                "scope": "action_wins_exclude_oracle_final_answers", "fixed_work": True,
                "comparison": ["public", "script"] if args.skill_ablation else [args.baseline, args.candidate],
                "skill_ablation": args.skill_ablation, "candidate": args.candidate,
                "skill_information": args.skill_information}
    sources = source_digest()
    manifests = scenario_fingerprints(library, scenarios)
    jobs = [(sid, seed, policy) for sid in scenarios for seed in settings["seeds"]
            for policy in (settings["comparison"] if seed % 2 == 0 else settings["comparison"][::-1])]
    if args.resume:
        report = json.loads(args.output.read_text(encoding="utf-8"))
        if report.get("settings") != settings or report.get("sources") != sources or report.get("scenario_fingerprints") != manifests:
            parser.error("resume requires unchanged sources, scenarios and settings")
        completed = completed_jobs(report["results"], jobs)
    else:
        if args.output.exists():
            parser.error("report exists; use --resume")
        report = {"settings": settings, "sources": sources, "scenario_fingerprints": manifests}
        completed = {}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        report["results"] = [completed[job_id(j)] for j in jobs if job_id(j) in completed]
        report["progress"] = {"completed": len(completed), "planned": len(jobs), "complete": len(completed) == len(jobs)}
        report["action_summary"] = summarize(report["results"], comparison=tuple(settings["comparison"]))
        write_report(args.output, report)
    def validate(job, row):
        if source_digest() != sources or scenario_fingerprints(library, scenarios) != manifests:
            raise RuntimeError("sources or scenarios changed before checkpoint")
        completed_jobs((row,), (job,))
    selected = [j for j in jobs if job_id(j) not in completed]
    if args.max_jobs is not None:
        selected = selected[:args.max_jobs]
    started = perf_counter()
    errors = []
    save()
    try:
        for job, row, error in run_jobs(selected, partial(run_match, settings=settings, sources=sources),
                                        workers=args.workers, validate=validate):
            if error is not None:
                report.setdefault("failures", []).append({"job_id": job_id(job), "error": str(error)})
                errors.append(error)
            else:
                completed[job_id(job)] = row
                print(f"{len(completed)}/{len(jobs)} {job}: action_win={row['action_win']} {row['elapsed_seconds']:.2f}s", flush=True)
            save()
    finally:
        report["last_execution"] = {"workers": args.workers, "wall_seconds": perf_counter() - started}
        save()
    if errors:
        raise errors[0]


if __name__ == "__main__":
    main()
