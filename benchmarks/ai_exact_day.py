"""Private FS day-game oracle: full card domains and all legal abilities.

This is a known-script diagnostic, not a fair player or a room strategy.
Budget-limited results retain unknown bounds, with no safety certificate.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from tragedy_sim import Game
from tragedy_sim.day_game import PureDaySolver, WorkLimit
from tragedy_sim.replay import ReplayArchive
from tragedy_sim.scenario_library import ScenarioLibrary

from .ai_calibration_matrix import source_digest, write_report


def load_root(scenario_id, *, report=None, variant=None, seed=0, loop=1, day=1,
              targets=("girl", "worker", "doctor")):
    if report is not None:
        data = json.loads(Path(report).read_text(encoding="utf-8"))
        rows = [r for r in data["results"] if r.get("scenario", r.get("scenario_id")) == scenario_id
                and r["seed"] == seed and (variant is None or r.get("variant") == variant)]
        if len(rows) != 1:
            raise ValueError("report selectors must identify exactly one complete replay")
        archive = ReplayArchive.parse(rows[0]["replay_text"])
        if archive.scenario["id"] != scenario_id:
            raise ValueError("replay scenario mismatch")
        game = Game(archive.scenario)
        for command in archive.commands:
            if (game.state.phase == "protagonists" and (game.state.loop, game.state.round) == (loop, day)
                    and not any(p.actor != "m" for p in game.state.pending)):
                return game
            game.dispatch(**command)
        raise ValueError("requested uncommitted red root does not occur in replay")
    if (loop, day) != (1, 1) or variant is not None:
        raise ValueError("later roots and variants require --report")
    game = Game(ScenarioLibrary().get(scenario_id))
    for _ in range(100):
        if game.state.phase == "mastermind":
            break
        actions = game.legal_actions(game.controller)
        if not actions:
            raise ValueError("scenario has no initial placement root")
        game = game.transition(actions[0]).game
    else:
        raise ValueError("scenario initialization exceeded 100 decisions")
    for target in targets:
        action = next((a for a in game.legal_actions("m") if a.get("target") == target), None)
        if action is None:
            raise ValueError("black targets must be three distinct legal placement targets")
        game = game.transition(action).game
    return game


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default="official-fs-01-first-script")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--variant")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--loop", type=int, default=1)
    parser.add_argument("--day", type=int, default=1)
    parser.add_argument("--targets", nargs=3, default=("girl", "worker", "doctor"))
    parser.add_argument("--nodes", type=int, default=10000)
    parser.add_argument("--time-ms", type=int, default=10000)
    parser.add_argument("--max-depth", type=int, default=256)
    parser.add_argument("--backend", choices=("reference", "cached", "compiled"), default="reference")
    parser.add_argument("--cache-capacity", type=int, default=100000)
    parser.add_argument("--edge-cache-capacity", type=int, default=0)
    parser.add_argument("--warmstart", type=Path, help="JSON array of complete red bundles; full domain remains")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if min(args.nodes, args.time_ms, args.max_depth, args.loop, args.day, args.cache_capacity) < 1:
        parser.error("budgets and positions must be positive")
    if args.edge_cache_capacity < 0 or (args.backend == "reference" and args.edge_cache_capacity):
        parser.error("edge cache requires --backend cached/compiled and a nonnegative capacity")
    sources = source_digest()
    try:
        game = load_root(args.scenario, report=args.report, variant=args.variant, seed=args.seed,
                         loop=args.loop, day=args.day, targets=args.targets)
        starts = json.loads(args.warmstart.read_text(encoding="utf-8")) if args.warmstart else ()
        work = WorkLimit(node_limit=args.nodes, time_limit_ms=args.time_ms)
        solver = PureDaySolver(max_depth=args.max_depth, backend=args.backend, cache_capacity=args.cache_capacity,
                               edge_cache_capacity=args.edge_cache_capacity)
        result = solver.solve(game, warmstarts=starts, work=work)
    except ValueError as error:
        parser.error(str(error))
    if sources != source_digest():
        raise RuntimeError("day-game sources changed during verification")
    output = {"sources": sources, "scenario": args.scenario,
              "scenario_digest": hashlib.sha256(json.dumps(game.scenario,ensure_ascii=False).encode()).hexdigest(),
              "position": [game.state.loop, game.state.round],
              "black_targets": [p.target for p in game.state.pending if p.actor == "m"],
              "settings": {"nodes": args.nodes, "time_ms": args.time_ms, "max_depth": args.max_depth,
                           "backend": args.backend, "cache_capacity": args.cache_capacity,
                           "edge_cache_capacity": args.edge_cache_capacity},
              "root_setup_commands": game.history,
              "known_script": True, "fair_policy": False,
              "certified_pure_value": result.bounds.exact,
              "result": asdict(result)}
    if args.backend in {"cached", "compiled"}:
        from tragedy_sim.day_game.keys import rule_state_key
        from tragedy_sim.day_game.local_cards import VERSION as program_version
        output["cache"] = {**asdict(solver.continuation.stats), "entries": len(solver.continuation.values),
                           "compact_clones": solver.kernel.compact_clones,
                           "fallback_clones": solver.kernel.fallback_clones,
                           "version": solver.kernel.version,
                           "rule_key_version": rule_state_key(game).version,
                           "local_program_version": program_version if args.backend == "compiled" else None,
                           "programs": asdict(solver.kernel.program_stats)}
        if solver.kernel.edges is not None:
            output["cache"]["edges"] = {**asdict(solver.kernel.edges.stats),
                                         "entries": len(solver.kernel.edges),
                                         "version": solver.kernel.edges.version}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_report(args.output, output)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
