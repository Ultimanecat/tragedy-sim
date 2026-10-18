"""Private FS selected-card game with optimized native information-set abilities.

This is an explicit-tree diagnostic. A selected root matrix is not a complete
domain oracle; no room strategy or default AI is changed by this command.
"""

import argparse
from dataclasses import asdict
from itertools import islice
import json
from pathlib import Path
from time import perf_counter

from tragedy_sim.day_game.continuation import WorkLimit
from tragedy_sim.day_game.fair_engine import bayesian_engine_game
from tragedy_sim.day_game.information_game import build_root_information_tree, solve_information_tree
from tragedy_sim.day_game.information_oracle import InformationDoubleOracle
from tragedy_sim.day_game.matrix import MatrixLimit
from tragedy_sim.day_game.posterior import PublicWorldPosterior, PosteriorUnavailable, reconstruct_public_roots
from .ai_bayesian_day import load_worlds
from .ai_calibration_matrix import source_digest, write_report
from .ai_exact_day import rational_json


def tree_payload(tree):
    return dict(scope=tree.scope, source_scope=tree.source_scope, continuation_complete=tree.continuation_complete,
        unknown_leaves=tree.unknown_leaves, stop_reasons=tree.stop_reasons, engine_nodes=tree.engine_nodes,
        engine_transitions=tree.engine_transitions, root_domain_complete=tree.root_domain_complete,
        belief_domain_complete=tree.belief_domain_complete, explicit_nodes=tree.lower.nodes,
        red_sequences=len(tree.lower.red.sequences), black_sequences=len(tree.lower.black.sequences),
        red_information_sets=len(tree.lower.red.information_sets), black_information_sets=len(tree.lower.black.information_sets))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--worlds", type=Path)
    inputs.add_argument("--view", type=Path)
    parser.add_argument("--warmstart", type=Path, required=True, help="finite common root red bundles, not a full-domain assertion")
    parser.add_argument("--mode", choices=("selected", "full-responses"), default="selected")
    parser.add_argument("--iterations", type=int, default=32)
    parser.add_argument("--epsilon", default="1/100")
    parser.add_argument("--response-candidates", type=int, help="optional per-response cutoff, never a complete-domain assertion")
    parser.add_argument("--own-commands", type=Path)
    parser.add_argument("--world-limit", type=int, default=2)
    parser.add_argument("--posterior-nodes", type=int, default=100000)
    parser.add_argument("--history-nodes", type=int)
    parser.add_argument("--allow-state-prior", action="store_true")
    parser.add_argument("--complete-posterior", action="store_true", help="caller assertion for --worlds only")
    parser.add_argument("--black-limit", type=int, default=2, help="prefix columns per world; incomplete domains are labeled")
    parser.add_argument("--nodes", type=int, default=500)
    parser.add_argument("--time-ms", type=int, default=10000)
    parser.add_argument("--max-depth", type=int, default=128)
    parser.add_argument("--tree-nodes", type=int, default=10000)
    parser.add_argument("--lp-cells", type=int, default=2000000)
    parser.add_argument("--lp-pivots", type=int, default=100000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for name in ("world_limit", "posterior_nodes", "black_limit", "nodes", "time_ms", "max_depth", "tree_nodes", "lp_cells", "lp_pivots", "iterations"):
        if getattr(args, name) < 1:
            parser.error(name + " must be positive")
    if args.view and args.complete_posterior:
        parser.error("--complete-posterior is a caller assertion for --worlds only")
    if args.history_nodes is not None and args.history_nodes < 1:
        parser.error("history_nodes must be positive")
    if args.response_candidates is not None and args.response_candidates < 1:
        parser.error("response_candidates must be positive")
    sources, started, tree, solved = source_digest(), perf_counter(), None, None
    evidence_report = None
    try:
        if args.view:
            view = json.loads(args.view.read_text(encoding="utf-8"))
            own = json.loads(args.own_commands.read_text(encoding="utf-8")) if args.own_commands else ()
            selection = PublicWorldPosterior(view, node_limit=args.posterior_nodes).select(args.world_limit)
            roots = reconstruct_public_roots(selection, view, own_commands=own, allow_state_prior=args.allow_state_prior,
                                             history_node_limit=args.history_nodes)
            model = roots.model()
            evidence_report = dict(selected_mass=selection.selected_mass, missing_mass=selection.missing_mass,
                joint_support=selection.joint_support, failed_mass=roots.failed_mass,
                approximated_state_mass=roots.approximated_state_mass, history_audits=roots.history_audits)
        else:
            model = bayesian_engine_game(load_worlds(args.worlds), belief_domain_complete=args.complete_posterior)
        plans = json.loads(args.warmstart.read_text(encoding="utf-8"))
        rows = tuple(model.blocks[0].game.plan(plan) for plan in plans)
        columns = tuple(tuple(islice(block.game.columns(), args.black_limit)) for block in model.blocks)
        evidence_seconds = perf_counter()-started
        work = WorkLimit(node_limit=args.nodes, time_limit_ms=args.time_ms)
        try:
            if args.mode == "full-responses":
                solved = InformationDoubleOracle(model, seed_rows=rows, seed_columns=columns).solve(work=work,
                    epsilon=args.epsilon, max_iterations=args.iterations, max_depth=args.max_depth,
                    tree_node_limit=args.tree_nodes, lp_cell_limit=args.lp_cells, pivot_limit=args.lp_pivots,
                    response_candidate_limit=args.response_candidates)
                reason = solved.stop_reason
            else:
                tree = build_root_information_tree(model, rows, columns, work=work, max_depth=args.max_depth,
                                                   tree_node_limit=args.tree_nodes)
                solved = solve_information_tree(tree, deadline=work.started+args.time_ms/1000,
                                                pivot_limit=args.lp_pivots, lp_cell_limit=args.lp_cells)
                reason = "complete_selected_game" if tree.continuation_complete else "interval_tree"
        except MatrixLimit as error:
            reason = error.reason
        result = dict(sources=sources, private_diagnostic=True, room_strategy=False, horizon="day",
            utility="day-survival-v1", settings={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
            evidence=evidence_report, evidence_seconds=evidence_seconds, action_seconds=perf_counter()-work.started,
            tree=tree_payload(tree) if tree is not None else None, result=asdict(solved) if solved is not None else None,
            fallback_bounds=dict(lower=0, upper=1) if solved is None else None, stop_reason=reason)
    except (OSError, ValueError, PosteriorUnavailable) as error:
        parser.error(str(error))
    if source_digest() != sources:
        raise RuntimeError("information-day sources changed during evaluation")
    result = rational_json(result)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_report(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
