"""Same authorized final-guess roots; terminal choices only, no new match play.

Both policies finish inference before private truth evaluates their decisions.
Historical recorded answers remain a separate row, never a policy input.
"""

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from time import perf_counter

from tragedy_sim import Game
from tragedy_sim.belief import PublicEvidence
from tragedy_sim.final_guess_probability import JointGuessProbabilitySolver
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.replay import ReplayArchive
from tragedy_sim.search import SearchBudget
from tragedy_sim.witness import FsbtxWitnessCompiler

from .ai_calibration_matrix import source_digest, write_report
from .ai_self_play import _policy_offer


def compare_final_root(game, *, seed=0, node_limit=100_000, recorded_guesses=None):
    if game.module != "BTX" or game.state.phase != "final_guess":
        raise ValueError("comparison requires a BTX root before guess submission")
    view = game.protagonist_team_view()
    offers = [_policy_offer(game, action) for action in game.action_offers(game.controller)]
    decisions = []
    for mode in ("latent_map", "cast_map"):
        agent = ParticleEnsembleProtagonistAgent(
            SearchBudget(node_limit=1, seed=seed), particle_count=1, rng_seed=seed,
            final_guess_policy=mode, final_guess_node_limit=node_limit)
        started = perf_counter()
        chosen = agent.choose_action(participant="team", view=deepcopy(view), offers=offers)
        decisions.append({"policy": mode, "guesses": chosen["arguments"]["guesses"],
                          "elapsed_ms": (perf_counter() - started) * 1000,
                          "belief_source": agent.last_trace.belief_source,
                          "reason": agent.last_trace.fallback,
                          "belief_failure": agent.last_trace.belief_failure})
    if recorded_guesses is not None:
        decisions.append({"policy": "historical_recorded", "guesses": dict(recorded_guesses)})
    result = JointGuessProbabilitySolver(node_limit=node_limit).solve(
        PublicEvidence.from_view(view), FsbtxWitnessCompiler().compile(view))
    # These queries and true-game transitions occur strictly after both fair
    # decisions. The true script never enters a protagonist constructor/view.
    for row in decisions:
        guesses = row["guesses"]
        row["model_probability"] = result.probability_for(guesses)
        successor = game.search_transition({"actor": game.controller, "action": "guess_all",
                                            "guesses": guesses})
        row["offline_outcome"] = {
            "information_scope": "true_world_after_inference",
            "winner": successor.winner,
            "correct": sum(role == game.scenario["cast"][cid] for cid, role in guesses.items()),
            "total": len(guesses)}
    old, new = (row["model_probability"] for row in decisions[:2])
    maximizing = None
    if result.exact:
        maximizing = (new >= old or math.isclose(new, old, rel_tol=1e-11, abs_tol=1e-14))
        if not maximizing:
            raise AssertionError("cast marginal MAP reduced the model's joint success probability")
    return {"loop": view["loop"], "day": view["round"], "model": result.to_dict(),
            "cast_map_maximizes_probability": maximizing, "decisions": decisions}


def compare_row(row, *, node_limit=100_000):
    archive = ReplayArchive.parse(row["replay_text"])
    game = Game(archive.scenario)
    if game.module not in {"FS", "BTX"}:
        raise ValueError("comparison supports FS/BTX archives only")
    finals = []
    for number, command in enumerate(archive.commands, 1):
        if command["action"] == "guess_all":
            compared = compare_final_root(game, seed=row.get("seed", 0), node_limit=node_limit,
                                          recorded_guesses=command["guesses"])
            finals.append({"command_number": number, **compared})
        game.dispatch(**command)
    if game.winner != archive.winner:
        raise AssertionError("reconstructed winner differs from recorded replay")
    return {"scenario": archive.scenario["id"], "module": game.module,
            "seed": row.get("seed"), "variant": row.get("variant"),
            "strategy": row.get("strategy", row.get("mastermind_strategy")),
            "replay_verified": True, "commands": len(archive.commands),
            "recorded_winner": archive.winner, "finals": finals}


def summary(results):
    finals = [root for row in results for root in row["finals"]]
    exact = [root for root in finals if root["model"]["exact"]]
    return {"rows": len(results), "final_roots": len(finals), "exact_roots": len(exact),
            "strict_model_improvements": sum(
                root["decisions"][1]["model_probability"] > root["decisions"][0]["model_probability"] + 1e-12
                for root in exact),
            "changed_guesses": sum(root["decisions"][0]["guesses"] != root["decisions"][1]["guesses"]
                                   for root in finals),
            "terminal_wins": {mode: sum(any(
                row["policy"] == mode and row["offline_outcome"]["winner"] == "protagonists"
                for row in root["decisions"]) for root in finals)
                for mode in ("latent_map", "cast_map", "historical_recorded")}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--node-limit", type=int, default=100_000)
    parser.add_argument("--scenario", action="append")
    parser.add_argument("--max-jobs", type=int)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.node_limit < 1 or args.max_jobs is not None and args.max_jobs < 1:
        parser.error("work limits must be positive")
    inputs, jobs = [], []
    for path in args.reports:
        raw = path.read_bytes()
        source = json.loads(raw)
        if "progress" in source and not source["progress"].get("complete"):
            parser.error("comparison requires completed input reports")
        inputs.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                       "sources": source.get("sources")})
        jobs.extend((len(inputs) - 1, index, row) for index, row in enumerate(source["results"])
                    if (not args.scenario or row.get("scenario", row.get("scenario_id")) in args.scenario))
    if not jobs:
        parser.error("no rows match selectors")
    settings = {"node_limit": args.node_limit, "scenario": args.scenario}
    report = {"sources": source_digest(), "inputs": inputs, "settings": settings,
              "progress": {"completed": 0, "planned": len(jobs), "complete": False}, "results": []}
    if args.resume:
        saved = json.loads(args.output.read_text(encoding="utf-8"))
        if any(saved.get(key) != report[key] for key in ("sources", "inputs", "settings")):
            parser.error("resume requires identical sources, inputs and settings")
        expected = [(input_index, row_index) for input_index, row_index, _ in jobs]
        actual = [(row["input_index"], row["row_index"]) for row in saved["results"]]
        if actual != expected[:len(actual)] or len(actual) > len(expected):
            parser.error("resume result order does not match selected jobs")
        report = saved
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_report(args.output, report)
    start = len(report["results"])
    selected = jobs[start:] if args.max_jobs is None else jobs[start:start + args.max_jobs]
    for input_index, row_index, row in selected:
        compared = compare_row(row, node_limit=args.node_limit)
        report["results"].append({"input_index": input_index, "row_index": row_index, **compared})
        completed = len(report["results"])
        report["progress"] = {"completed": completed, "planned": len(jobs), "complete": completed == len(jobs)}
        report["summary"] = summary(report["results"])
        write_report(args.output, report)
        print(f"{compared['scenario']}: {len(compared['finals'])} final roots ({completed}/{len(jobs)})", flush=True)


if __name__ == "__main__":
    main()
