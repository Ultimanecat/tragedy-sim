"""Common fair root, attack probes, and optional exhaustive legal dark faces.

Full face enumeration is conditional on sampled role/culprit worlds. It does
not assert complete identity support or historical/full-match minimax. True
game outcomes are queried only after the fair decisions have finished.
"""

import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random

from tragedy_sim import Game
from tragedy_sim.belief import HiddenWorldHypothesis, PublicEvidence
from tragedy_sim.belief_planner import PublicStateDeterminizer
from tragedy_sim.dark_attack_scenarios import legal_dark_bundles, with_dark_bundle
from tragedy_sim.engine import Placement
from tragedy_sim.oracle_protagonist import OracleProtagonistAgent
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.replay import ReplayArchive
from tragedy_sim.search import SearchBudget

from .ai_calibration_matrix import source_digest, write_report
from .ai_self_play import _policy_offer
from .parallel_jobs import DEFAULT_WORKERS, run_jobs


def _exhaustive_world(job):
    if source_digest() != job["sources"]:
        raise RuntimeError("sources changed during dark-face audit")
    view = job["view"]
    hypothesis = HiddenWorldHypothesis.from_scenario(job["hypothesis"])
    world = PublicStateDeterminizer().determinize(hypothesis, PublicEvidence.from_view(view), view,
                                                rng=random.Random(0))
    world = with_dark_bundle(world, tuple(Placement(**p) for p in job["original_dark"]))
    oracle = OracleProtagonistAgent(reveal_cards=True, rng_seed=job["seed"], script_aware_rollout=False)
    strategies = oracle._mastermind_strategy_options(world)
    result = {name: {"surviving_faces": 0, "losing_faces": 0, "examples": []} for name in job["plans"]}
    count, evaluations = 0, 0
    for faces in legal_dark_bundles(view):
        count += 1
        if count > job["face_limit"]:
            raise ValueError("face enumeration exceeds limit; no exhaustive result returned")
        variant = with_dark_bundle(world, faces)
        for name, bundle in job["plans"].items():
            successor = ParticleEnsembleProtagonistAgent._apply_bundle(variant, bundle)
            if successor is None:
                raise AssertionError("a fixed legal red plan became invalid under legal dark faces")
            outcomes = [oracle._day_score(successor, view["loop"], view["round"], mastermind_strategy=s)
                        for s in strategies]
            evaluations += len(outcomes)
            survived = all(safe for _, safe in outcomes)
            result[name]["surviving_faces" if survived else "losing_faces"] += 1
            if not survived and len(result[name]["examples"]) < 2:
                result[name]["examples"].append([asdict(p) for p in faces])
    if source_digest() != job["sources"]:
        raise RuntimeError("sources changed during dark-face audit")
    return {"world_index": job["world_index"], "faces": count, "evaluations": evaluations,
            "face_enumeration_complete": True, "role_culprit_scope": "one_sampled_hypothesis",
            "plans": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--variant", default="partition")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--loop", type=int, required=True)
    parser.add_argument("--day", type=int, required=True)
    parser.add_argument("--nodes", type=int, default=8)
    parser.add_argument("--worlds", type=int, default=4)
    parser.add_argument("--role-sampling-policy", choices=("importance", "exact_partition"), default="exact_partition")
    parser.add_argument("--exhaustive", action="store_true")
    parser.add_argument("--face-limit", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--dark-guard-proposals", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if min(args.loop, args.day, args.nodes, args.worlds, args.workers, args.face_limit) < 1:
        parser.error("budgets and positions must be positive")
    if args.output.exists():
        parser.error("choose a new output path")
    raw = args.report.read_bytes()
    source = json.loads(raw)
    if not source.get("progress", {}).get("complete"):
        parser.error("a completed paired report is required")
    rows = [r for r in source["results"] if r["scenario"] == args.scenario
            and r["variant"] == args.variant and r["seed"] == args.seed]
    if len(rows) != 1:
        parser.error("selectors must identify one completed match")
    archive = ReplayArchive.parse(rows[0]["replay_text"])
    game = Game(archive.scenario)
    for command in archive.commands:
        if game.state.phase == "protagonists" and (game.state.loop, game.state.round) == (args.loop, args.day):
            break
        game.dispatch(**command)
    else:
        parser.error("requested root was not reached")
    view = game.protagonist_team_view()
    offers = [_policy_offer(game, a) for a in game.action_offers(game.controller)]
    class CapturedPlanner(ParticleEnsembleProtagonistAgent):
        def _counts(self, worlds, evidence):
            self.worlds = deepcopy(worlds)
            return super()._counts(worlds, evidence)
    decisions, plans, sampled = [], {}, None
    for policy in ("sampled", "adversarial_guard"):
        agent = CapturedPlanner(SearchBudget(node_limit=args.nodes, rollout_depth=4, seed=args.seed),
                                particle_count=args.worlds, rng_seed=args.seed,
                                role_sampling_policy=args.role_sampling_policy, dark_card_policy=policy,
                                dark_guard_proposals=args.dark_guard_proposals)
        chosen = agent.choose_action(participant="team", view=deepcopy(view), offers=offers)
        decision = agent.decision_for_action(chosen)
        plans[policy] = tuple({"actor": p.actor, "action": "play", "card": p.card, "target": p.target}
                              for p in decision.card_plan)
        decisions.append({"policy": policy, "bundle": plans[policy], "trace": agent.last_trace.to_dict()})
        if sampled is None:
            sampled = agent.worlds
        elif [world.view("m") for world in sampled] != [world.view("m") for world in agent.worlds]:
            raise AssertionError("guard policy changed the common posterior/face samples")
    # Only after inference/decisions: evaluate the actual held-out world.
    oracle = OracleProtagonistAgent(reveal_cards=True, rng_seed=args.seed, script_aware_rollout=False)
    for row in decisions:
        successor = ParticleEnsembleProtagonistAgent._apply_bundle(game, row["bundle"])
        row["offline_true_day_outcomes"] = [
            {"strategy": s, "score": score, "survived": safe}
            for s in oracle._mastermind_strategy_options(game)
            for score, safe in (oracle._day_score(successor, args.loop, args.day, mastermind_strategy=s),)]
    report = {"sources": source_digest(), "input_sha256": hashlib.sha256(raw).hexdigest(),
              "settings": {**vars(args), "report": str(args.report), "output": str(args.output)},
              "scope": "developer_only_fair_decisions_then_offline_truth", "decisions": decisions,
              "exhaustive_worlds": [], "progress": {"complete": not args.exhaustive, "completed": 0,
                                                       "planned": len(sampled) if args.exhaustive else 0}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_report(args.output, report)
    if args.exhaustive:
        jobs = [{"world_index": i, "sources": report["sources"], "view": view, "seed": args.seed,
                 "hypothesis": world.scenario, "original_dark": [asdict(p) for p in world.state.pending if p.actor == "m"],
                 "plans": plans, "face_limit": args.face_limit} for i, world in enumerate(sampled)]
        errors = []
        for job, result, error in run_jobs(jobs, _exhaustive_world, workers=args.workers):
            if error is not None:
                errors.append(error)
                report["error"] = f"{type(error).__name__}: {error}"
            else:
                report["exhaustive_worlds"].append(result)
                report["exhaustive_worlds"].sort(key=lambda r: r["world_index"])
                report["progress"]["completed"] += 1
            report["progress"]["complete"] = not errors and report["progress"]["completed"] == len(jobs)
            write_report(args.output, report)
            print(report["progress"], flush=True)
        if errors:
            raise errors[0]
    print([(r["policy"], r["bundle"], r["offline_true_day_outcomes"]) for r in decisions], flush=True)


if __name__ == "__main__":
    main()
