"""Private finite-world FS diagnostic with common, observable red policies.

Worlds and original masses are supplied by a caller, not inferred from a true
script. Input coverage is not automatically certified. The red continuation
is frozen to a simple observable baseline; this is not a room AI strategy.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from tragedy_sim import Game
from tragedy_sim.day_game.bayesian import BayesianDoubleOracle
from tragedy_sim.day_game.continuation import WorkLimit
from tragedy_sim.day_game.engine_game import red_commands
from tragedy_sim.day_game.fair_engine import PublicSkipOptionalPolicy, bayesian_engine_game
from tragedy_sim.day_game.matrix import rational
from tragedy_sim.day_game.zero_sum import SearchBudget

from .ai_calibration_matrix import source_digest, write_report
from .ai_exact_day import rational_json


class GenericSkipPolicy:
    """Same behavior through the conservative custom-policy path, for ablation."""
    _policy = PublicSkipOptionalPolicy()
    version = _policy.version

    def choose(self, information):
        return self._policy.choose(information)


def load_worlds(path):
    records = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(records, list) or not records:
        raise ValueError("world input must be a nonempty JSON array")
    result = []
    for record in records:
        if not isinstance(record, dict) or set(record) != {"label", "mass", "scenario", "commands"}:
            raise ValueError("each world requires label, mass, scenario and commands")
        if not isinstance(record["scenario"], dict) or not isinstance(record["commands"], list):
            raise ValueError("scenario must be an object and commands an array")
        world = Game(record["scenario"])
        for command in record["commands"]:
            if not isinstance(command, dict) or not {"actor", "action"} <= command.keys():
                raise ValueError("root setup commands require actor and action")
            world.dispatch(**command)
        result.append((record["label"], rational(record["mass"]), world))
    return tuple(result)


def result_payload(result):
    def black_action(column):
        if len(column) == 2 and type(column[0]) is int:
            return dict(history_index=column[0], placements=[asdict(card) for card in column[1]])
        return dict(placements=[asdict(card) for card in column])

    payload = asdict(result)
    payload["red"] = [{"plan": red_commands(row), "probability": p} for row, p in result.red]
    payload["black"] = [{"world": label, "conditional_policy": [
        {**black_action(column), "probability": p} for column, p in policy]}
        for label, policy in result.black]
    return rational_json(payload)


def continuation_work(game):
    if hasattr(game, "variants"):
        return dict(row_domain=game.row_count, column_domain=game.column_count,
                    compatible_histories=len(game.variants), variants=[continuation_work(v) for v in game.variants])
    return dict(row_domain=game.row_count, column_domain=game.column_count,
                continuation_nodes=game.continuation_nodes,
                continuation_transitions=game.continuation_transitions,
                continuation_stop_reasons=sorted(game.continuation_reasons),
                continuation_cache={**asdict(game.continuation.stats), "entries": len(game.continuation.values)},
                policy_context={"mode": game.continuation.context_mode, **asdict(game.continuation.context_stats)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worlds", required=True, type=Path)
    parser.add_argument("--complete-posterior", action="store_true", help="caller asserts full posterior support; not inferred")
    parser.add_argument("--backend", choices=("reference", "cached", "compiled"), default="cached")
    parser.add_argument("--generic-context-baseline", action="store_true", help="same policy; retain full context for timing/equivalence checks")
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
    if min(args.nodes, args.time_ms, args.payoff_limit, args.max_depth, args.cache_capacity, args.iterations, args.lp_pivots) < 1:
        parser.error("budgets must be positive")
    sources = source_digest()
    try:
        roots = load_worlds(args.worlds)
        model = bayesian_engine_game(roots, belief_domain_complete=args.complete_posterior, backend=args.backend,
                                     policy=GenericSkipPolicy() if args.generic_context_baseline else None,
                                     max_depth=args.max_depth, cache_capacity=args.cache_capacity)
        seeds = json.loads(args.warmstart.read_text(encoding="utf-8")) if args.warmstart else ()
        oracle = BayesianDoubleOracle(model, seed_rows=tuple(model.blocks[0].game.plan(plan) for plan in seeds),
                                      payoff_cache_capacity=args.cache_capacity)
        budget = SearchBudget(work=WorkLimit(node_limit=args.nodes, time_limit_ms=args.time_ms), payoff_limit=args.payoff_limit)
        result = oracle.solve(budget=budget, epsilon=args.epsilon, max_iterations=args.iterations, pivot_limit=args.lp_pivots)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    if sources != source_digest():
        raise RuntimeError("Bayesian day-game sources changed during verification")
    inputs = [{"label": label, "mass": str(mass), "scenario": world.scenario, "commands": world.history}
              for label, mass, world in roots]
    report = dict(sources=sources, private_diagnostic=True, room_strategy=False,
                  input_source="caller-provided-worlds/not-an-automatically-verified-posterior",
                  asserted_complete_posterior=args.complete_posterior,
                  authorized_root_digest=hashlib.sha256(model.blocks[0].game.root_information.key.encode()).hexdigest(),
                  world_inputs=inputs, settings={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                  horizon="day", utility="day-survival-v1", result=result_payload(result),
                  work=[dict(world=b.label, payoff_cache=asdict(cache.stats), **continuation_work(b.game))
                        for b, cache in zip(model.blocks, oracle.caches)])
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_report(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
