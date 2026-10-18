"""Private FS diagnostic starting exclusively from an authorized team view.

Connects current matrix/witness role partitions and legal joint culprits to
the fair blocked day-game model. No real secret script or true Game is input.
Evidence work is reported separately and does not consume action work.
"""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from tragedy_sim.day_game.public_day import solve_public_day
from .ai_bayesian_day import result_payload
from .ai_calibration_matrix import source_digest, write_report
from .ai_exact_day import rational_json


def report_payload(solved):
    posterior = None
    if solved.posterior is not None:
        posterior = asdict(solved.posterior)
        posterior.pop("snapshot_key")
    reconstruction = None
    if solved.reconstruction is not None:
        roots = solved.reconstruction
        reconstruction = dict(roots=len(roots.roots), failed_mass=roots.failed_mass,
                              approximated_state_mass=roots.approximated_state_mass, failures=roots.failures)
    return rational_json(dict(posterior=posterior, reconstruction=reconstruction,
                              result=result_payload(solved.result) if solved.result is not None else None,
                              stop_reason=solved.stop_reason, evidence_seconds=solved.evidence_elapsed_seconds,
                              action_seconds=solved.action_elapsed_seconds))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", type=Path, required=True)
    parser.add_argument("--own-commands", type=Path)
    parser.add_argument("--world-limit", type=int, default=12)
    parser.add_argument("--posterior-nodes", type=int, default=100000)
    parser.add_argument("--allow-state-prior", action="store_true")
    parser.add_argument("--backend", choices=("reference", "cached", "compiled"), default="reference")
    parser.add_argument("--nodes", type=int, default=100000)
    parser.add_argument("--time-ms", type=int, default=10000)
    parser.add_argument("--payoff-limit", type=int, default=100000)
    parser.add_argument("--max-depth", type=int, default=256)
    parser.add_argument("--cache-capacity", type=int, default=100000)
    parser.add_argument("--iterations", type=int, default=64)
    parser.add_argument("--lp-pivots", type=int, default=100000)
    parser.add_argument("--epsilon", default="1/100")
    parser.add_argument("--warmstart", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    sources = source_digest()
    try:
        view = json.loads(args.view.read_text(encoding="utf-8"))
        commands = json.loads(args.own_commands.read_text(encoding="utf-8")) if args.own_commands else ()
        seeds = json.loads(args.warmstart.read_text(encoding="utf-8")) if args.warmstart else ()
        solved = solve_public_day(view, own_commands=commands, world_limit=args.world_limit,
                                  posterior_node_limit=args.posterior_nodes, allow_state_prior=args.allow_state_prior,
                                  backend=args.backend, max_depth=args.max_depth, cache_capacity=args.cache_capacity,
                                  node_limit=args.nodes, time_limit_ms=args.time_ms, payoff_limit=args.payoff_limit,
                                  epsilon=args.epsilon, max_iterations=args.iterations, pivot_limit=args.lp_pivots,
                                  seed_plans=seeds)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    if source_digest() != sources:
        raise RuntimeError("public-day sources changed during evaluation")
    output = dict(sources=sources, private_diagnostic=True, room_strategy=False,
                  input_source="authorized-team-view/matrix-role-partition/legal-joint-culprits",
                  view=view, own_commands=commands,
                  settings={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                  **report_payload(solved))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_report(args.output, output)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
