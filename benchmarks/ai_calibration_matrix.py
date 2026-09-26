"""Serial, resumable fixed-work calibration across recorded FS/BTX scripts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from tragedy_sim.scenario_library import ScenarioLibrary
from .ai_cutoff_calibration import summarize
from .ai_path_calibration import cross_validated_paths


ROOT = Path(__file__).resolve().parents[1]


def source_digest() -> str:
    digest = hashlib.sha256()
    for folder in ("tragedy_sim", "benchmarks"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            digest.update(path.relative_to(ROOT).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def select_scenarios(library: ScenarioLibrary, module: str,
                     difficulties: str) -> list[str]:
    return sorted(item["id"] for item in library.list()
                  if item["source"] == "library"
                  and item["module"] in ({"FS", "BTX"} if module == "all"
                                         else {module})
                  and (difficulties == "all" or not item["id"].endswith(
                      ("-easy", "-very-easy"))))


def write_report(path: Path, report: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", choices=("all", "FS", "BTX"), default="all")
    parser.add_argument("--difficulties", choices=("standard", "all"), default="all")
    parser.add_argument("--games", type=int, default=1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--protagonist-nodes", type=int, action="append")
    parser.add_argument("--protagonist-particles", type=int,
                        help="override worlds independently of candidate budgets")
    parser.add_argument("--mastermind-nodes", type=int, default=2)
    parser.add_argument("--strategy", choices=("fixed", "joint"), default="fixed")
    parser.add_argument("--protagonist-strategy", choices=(
        "particle_ensemble", "risk_aware", "defensive", "baseline"),
        default="particle_ensemble")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-jobs", type=int,
                        help="maximum new matches this invocation (resume to continue)")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--repeat-check", action="store_true")
    args = parser.parse_args()
    budgets = sorted(set(args.protagonist_nodes or [2]))
    if (min([args.games, args.mastermind_nodes, *budgets]) < 1
            or args.protagonist_particles is not None and args.protagonist_particles < 1
            or args.max_jobs is not None and args.max_jobs < 1):
        parser.error("games and budgets must be positive")
    library = ScenarioLibrary()
    scenarios = select_scenarios(library, args.module, args.difficulties)
    config = {
        "schema_version": 1, "sources": source_digest(),
        "scenarios": {sid: library.get(sid) for sid in scenarios},
        "seeds": list(range(args.seed, args.seed + args.games)),
        "protagonist_nodes": budgets, "mastermind_nodes": args.mastermind_nodes,
        "protagonist_particles": args.protagonist_particles,
        "strategy": args.strategy, "protagonist_strategy": args.protagonist_strategy,
        "repeat_check": args.repeat_check,
    }
    fingerprint = hashlib.sha256(json.dumps(
        config, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    directory = args.output_dir / ("run-" + fingerprint)
    directory.mkdir(parents=True, exist_ok=True)
    manifest = directory / "manifest.json"
    if manifest.exists():
        if not args.resume:
            parser.error(f"run already exists; use --resume: {directory}")
        if json.loads(manifest.read_text(encoding="utf-8")) != config:
            parser.error("manifest does not match current configuration")
    else:
        write_report(manifest, config)
    reports = []
    new_jobs = 0
    total = len(scenarios) * args.games * len(budgets)
    for nodes in budgets:
        for sid in scenarios:
            for seed in config["seeds"]:
                path = directory / f"{sid}-seed{seed}-nodes{nodes}.json"
                metadata = {"scenario": sid, "seed": seed, "nodes": nodes,
                            "fingerprint": fingerprint}
                if path.exists():
                    report = json.loads(path.read_text(encoding="utf-8"))
                    if report.get("matrix_job") != metadata:
                        raise ValueError(f"invalid checkpoint: {path}")
                elif args.max_jobs is not None and new_jobs >= args.max_jobs:
                    continue
                else:
                    command = [sys.executable, "-m", "benchmarks.ai_cutoff_calibration",
                               "--scenario", sid, "--games", "1", "--seed", str(seed),
                               "--strategy", args.strategy, "--protagonist-strategy",
                               args.protagonist_strategy, "--protagonist-nodes", str(nodes),
                               "--mastermind-nodes", str(args.mastermind_nodes),
                               "--fixed-work", "--json"]
                    if args.repeat_check:
                        command.append("--repeat-check")
                    if args.protagonist_particles is not None:
                        command.extend(["--protagonist-particles",
                                        str(args.protagonist_particles)])
                    print(f"running {sid} seed={seed} nodes={nodes}", flush=True)
                    try:
                        result = subprocess.run(
                            command, cwd=ROOT, capture_output=True, encoding="utf-8",
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, check=True)
                    except subprocess.CalledProcessError as error:
                        print(error.stderr or str(error), file=sys.stderr)
                        raise
                    report = json.loads(result.stdout)
                    report["matrix_job"] = metadata
                    write_report(path, report)
                    new_jobs += 1
                    match = report["matches"][0]
                    print(f"  {match['outcome_mode']} {match['final_correct']}/"
                          f"{match['final_total']} {match['elapsed_seconds']:.1f}s",
                          flush=True)
                reports.append(report)
    groups = []
    for nodes in budgets:
        for module in ("FS", "BTX"):
            selected = [report for report in reports
                        if report["matrix_job"]["nodes"] == nodes
                        and config["scenarios"][report["matrix_job"]["scenario"]]
                        ["module"] == module]
            if not selected:
                continue
            rows = [row for report in selected for row in report["rows"]]
            matches = [match for report in selected for match in report["matches"]]
            groups.append({"module": module, "nodes": nodes,
                           "outcomes": {mode: sum(m["outcome_mode"] == mode
                                                   for m in matches)
                                        for mode in sorted({m["outcome_mode"]
                                                            for m in matches})},
                           "cutoffs": summarize(rows),
                           "path_cv": cross_validated_paths(rows)
                           if module == "BTX" else None})
    summary = {"fingerprint": fingerprint, "completed": len(reports),
               "planned": total, "new_jobs": new_jobs, "groups": groups}
    write_report(directory / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"saved: {directory}")


if __name__ == "__main__":
    main()
