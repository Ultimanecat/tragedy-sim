"""Serial, resumable matrix-vs-legacy matches with mandatory replay audits.

Freeze Python sources, selected scenario contents and search budgets. Audit
private truth only after each match; never supply it to a protagonist policy.
"""

import argparse
from dataclasses import asdict
import faulthandler
import hashlib
import json
from pathlib import Path

from tragedy_sim import Game
from tragedy_sim.belief import HiddenWorldHypothesis, PublicEvidence
from tragedy_sim.replay import ReplayArchive
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.witness import FsbtxWitnessCompiler, FsbtxWitnessMatcher

from .ai_belief_matrix_audit import audit_view
from .ai_calibration_matrix import source_digest, write_report
from .ai_cutoff_calibration import match_telemetry
from .ai_self_play import play


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
            "partition": (True, True, "prior")}


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
    outcomes = {"improved": 0, "regressed": 0, "both_red": 0, "both_black": 0}
    for variants in pairs.values():
        if not set(comparison).issubset(variants):
            continue
        old, new = (variants[v]["winner"] == "protagonists" for v in comparison)
        key = "both_red" if old and new else "both_black" if not old and not new else "improved" if new else "regressed"
        outcomes[key] += 1
    return {"completed_pairs": sum(outcomes.values()), "comparison": list(comparison), **outcomes,
            "variants": {v: {"matches": sum(r["variant"] == v for r in results),
                             "red_wins": sum(r["variant"] == v and r["winner"] == "protagonists"
                                             for r in results)}
                         for v in VARIANTS if any(r["variant"] == v for r in results)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", action="append", dest="scenarios")
    parser.add_argument("--seed", action="append", type=int, dest="seeds")
    parser.add_argument("--variant", action="append", choices=tuple(VARIANTS), dest="variants")
    parser.add_argument("--comparison", choices=("legacy_matrix", "matrix_partition"), default="legacy_matrix")
    parser.add_argument("--mastermind-nodes", type=int, default=24)
    parser.add_argument("--protagonist-nodes", type=int, default=8)
    parser.add_argument("--worlds", type=int, default=12)
    parser.add_argument("--mastermind-ms", type=int, default=1000)
    parser.add_argument("--protagonist-ms", type=int, default=1000)
    parser.add_argument("--depth", type=int, default=8)
    parser.add_argument("--fixed-work", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-jobs", type=int)
    args = parser.parse_args()
    if (min(args.mastermind_nodes, args.protagonist_nodes, args.worlds,
            args.mastermind_ms, args.protagonist_ms, args.depth) < 1
            or args.max_jobs is not None and args.max_jobs < 1):
        parser.error("budgets and max-jobs must be positive")
    scenarios = list(dict.fromkeys(args.scenarios or DEFAULT_SCENARIOS))
    seeds = list(dict.fromkeys(args.seeds or (0, 3)))
    comparison = ("matrix", "partition") if args.comparison == "matrix_partition" else ("legacy", "matrix")
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
    manifests = scenario_fingerprints(library, scenarios)
    jobs = [(sid, seed, variant) for i, sid in enumerate(scenarios)
            for j, seed in enumerate(seeds)
            for variant in (variants if (i + j) % 2 == 0 else list(reversed(variants)))]
    if args.resume:
        if not args.output.exists():
            parser.error("resume report does not exist")
        report = json.loads(args.output.read_text(encoding="utf-8"))
        if (report.get("schema_version") != 1 or report.get("sources") != sources
                or report.get("settings") != settings or report.get("scenario_fingerprints") != manifests):
            parser.error("resume requires unchanged sources, scenarios and budgets")
        completed = [(r["scenario"], r["seed"], r["variant"]) for r in report["results"]]
        if completed != jobs[:len(completed)] or len(completed) > len(jobs):
            parser.error("resume results do not match the planned prefix")
        if any(not r.get("replay_audit", {}).get("verified") for r in report["results"]):
            parser.error("resume requires audited completed matches")
    else:
        if args.output.exists():
            parser.error("report exists; use --resume or a new output path")
        report = {"schema_version": 1, "sources": sources, "settings": settings,
                  "scenario_fingerprints": manifests, "results": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        report["progress"] = {"completed": len(report["results"]), "planned": len(jobs),
                              "complete": len(report["results"]) == len(jobs)}
        report["paired_summary"] = paired_summary(report["results"], comparison=comparison)
        write_report(args.output, report)

    report.pop("failed_job", None)
    save()
    for index, (sid, seed, variant) in enumerate(jobs[len(report["results"]):]):
        if args.max_jobs is not None and index >= args.max_jobs:
            break
        try:
            if source_digest() != sources or scenario_fingerprints(library, scenarios) != manifests:
                raise RuntimeError("Sources or selected scenarios changed during evaluation")
            matrix, joint, policy = VARIANTS[variant]
            role_policy = "exact_partition" if variant == "partition" else "importance"
            faulthandler.dump_traceback_later(60, repeat=True)
            try:
                match = play(sid, seed, args.mastermind_nodes, args.depth, "joint", "particle_ensemble",
                             protagonist_nodes=args.protagonist_nodes, protagonist_depth=args.depth,
                             time_limit_ms=settings["mastermind_ms"],
                             protagonist_time_limit_ms=settings["protagonist_ms"],
                             protagonist_particles=args.worlds, matrix_proposals=matrix,
                             joint_culprits=joint, matrix_variant_policy=policy,
                             role_sampling_policy=role_policy,
                             joint_reply_model="belief", joint_information_weight=0.02,
                             capture_fallback_contexts=True, capture_replay=True)
            finally:
                faulthandler.cancel_dump_traceback_later()
            if (match.scenario_id != sid or match.seed != seed
                    or match.matrix_proposals_enabled != matrix or match.joint_culprits_enabled != joint
                    or match.matrix_variant_policy != policy):
                raise AssertionError("Returned match configuration differs from planned variant")
            if match.role_sampling_policy != role_policy:
                raise AssertionError("Returned role sampling policy differs from planned variant")
            audit = audit_match(match)
            if source_digest() != sources or scenario_fingerprints(library, scenarios) != manifests:
                raise RuntimeError("Sources or selected scenarios changed during the match")
            row = {**asdict(match), **match_telemetry(match), "scenario": sid,
                   "strategy": "joint", "variant": variant,
                   "final_correct": sum(g.correct for g in match.final_guesses),
                   "final_total": len(match.final_guesses), "replay_audit": audit}
            report["results"].append(row)
            save()
            print(f"{len(report['results'])}/{len(jobs)} {sid} seed={seed} {variant}: "
                  f"{match.winner}, final={row['final_correct']}/{row['final_total']}, "
                  f"{match.elapsed_seconds:.3f}s", flush=True)
        except Exception as error:
            report["failed_job"] = {"scenario": sid, "seed": seed, "variant": variant,
                                    "error": f"{type(error).__name__}: {error}"}
            save()
            raise


if __name__ == "__main__":
    main()
