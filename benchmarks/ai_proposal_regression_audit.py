"""Developer-only, recorded-path audit of identity proposals and evidence.

Reconstructs the persistent sampling pipeline without searching for actions.
Recorded commands drive each path; private truth is consulted only AFTER
sampling for diagnostics. No report is a new match or exact posterior.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
from itertools import product
import json
import math
from pathlib import Path
import random

from tragedy_sim import Game
from tragedy_sim.belief import FactorizedBeliefState, HiddenWorldHypothesis, PublicEvidence
from tragedy_sim.belief_planner import PublicStateDeterminizer, _key
from tragedy_sim.information_value import InformationOpportunityEvaluator
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.replay import ReplayArchive
from tragedy_sim.search import SearchBudget
from tragedy_sim.witness import FsbtxWitnessCompiler, FsbtxWitnessMatcher, PublicEvidenceLedger
from .ai_calibration_matrix import source_digest, write_report


def _role_weights(state, witnesses):
    matcher = FsbtxWitnessMatcher()
    role_facts = state._role_witnesses(witnesses)
    if state.role_importance_pool is not None:
        return state.role_importance_pool.posterior(state.role_target, role_facts)
    return [(world, state.role_target.weight(world, role_facts) if state.role_target else
             2.0 ** matcher.soft_score(world, role_facts) /
             (state._plot_sizes[(world.main_plot, world.subplots)]
              if state._exact_roles else 1)) for world in state._roles.values()]


def _culprit_profile(state, evidence, witnesses):
    matcher = FsbtxWitnessMatcher()
    facts = tuple(w for w in witnesses if w.kind in {
        "culprit_is", "culprit_in", "incident_happened", "incident_not_happened"})
    domains = state._culprits(evidence, witnesses)
    result = []
    for day, kind in evidence.schedule:
        weights = [(cid, 2.0 ** matcher.soft_score(HiddenWorldHypothesis(
            "belief-culprit", "", (), (), ((day, kind, kind, cid),)), facts))
            for cid in domains[day]]
        total = sum(weight for _, weight in weights)
        result.append({"day": day, "kind": kind, "hard_domain": list(domains[day]),
                       "precomposition_probabilities": {cid: weight / total for cid, weight in weights}})
    return result


def _culprit_composition(profile, *, limit=100_000):
    """Condition independent culprit weights on the scenario's repeat rule.

    This is exact within the culprit dimension, before dark-card
    materialization; it is not a full-world posterior. No RNG is used.
    """
    count = math.prod(len(row["hard_domain"]) for row in profile)
    if count > limit:
        return {"complete": False, "assignments_before_filter": count,
                "reason": "enumeration_limit"}
    accepted, total = 0, 0.0
    marginals = {row["day"]: Counter() for row in profile}
    for choices in product(*(row["hard_domain"] for row in profile)):
        kinds = {}
        for row, culprit in zip(profile, choices):
            kinds.setdefault(culprit, []).append(row["kind"])
        if any(len(ks) > 1 and any(k != "serial_murder" for k in ks)
               for ks in kinds.values()):
            continue
        weight = math.prod(row["precomposition_probabilities"][culprit]
                           for row, culprit in zip(profile, choices))
        accepted += 1
        total += weight
        for row, culprit in zip(profile, choices):
            marginals[row["day"]][culprit] += weight
    return {"complete": True, "assignments_before_filter": count,
            "legal_assignments": accepted, "independent_draw_acceptance": total,
            "conditioned_probabilities": {day: {cid: value / total if total else 0.0
                for cid, value in counts.items()} for day, counts in marginals.items()}}


def _probe(worlds, view, plans, seed, actual_game, witnesses):
    planner = ParticleEnsembleProtagonistAgent(
        SearchBudget(node_limit=8, rollout_depth=8, seed=seed), rng_seed=seed)
    info = InformationOpportunityEvaluator(
        worlds, view, threads_confirmed=planner._threads_confirmed(view, witnesses))
    rows = []
    for bundle in plans:
        scores = []
        for world in worlds:
            successor = planner._apply_bundle(world, bundle)
            if successor is None:
                break
            outcomes = [planner.oracle._rollout_score(
                successor, view["loop"], view["round"],
                mastermind_strategy=strategy, information_model=info)
                for strategy in planner._mastermind_strategies(world)]
            worst = min(outcomes, key=lambda x: (
                x[1], x[0] + min(0.012, planner.information_reward_weight * x[4]) - x[8]))
            scores.append(worst[:2])
        actual = planner._apply_bundle(actual_game, bundle) if actual_game is not None else None
        rows.append({"bundle": bundle, "valid_in_all_worlds": len(scores) == len(worlds),
                     "survivals": sum(ok for _, ok in scores),
                     "raw_tail": (sorted(x for x, _ in scores)[max(0, len(scores) // 5 - 1)]
                                  if len(scores) == len(worlds) else None),
                     "raw_mean": (sum(x for x, _ in scores) / len(scores) if scores else None),
                     "actual_day_outcomes": ([{"strategy": strategy,
                         "score": outcome[0], "survived": outcome[1]}
                         for strategy in planner.oracle._mastermind_strategy_options(actual_game)
                         for outcome in [planner.oracle._day_score(
                             actual, view["loop"], view["round"], mastermind_strategy=strategy)]]
                         if actual is not None else [])})
    return rows


def resample_probe(state, evidence, witnesses, view, plans, *, counts, draws, seed):
    """Freeze the existing role pool; vary only independent world draws."""
    class FrozenRoleBelief(FactorizedBeliefState):
        def _refresh_roles(self, evidence, witnesses):
            pass
    frozen = FrozenRoleBelief()
    frozen.joint_culprits_enabled = state.joint_culprits_enabled
    frozen._roles = dict(state._roles)
    frozen._plot_sizes = state._plot_sizes.copy()
    frozen._exact_roles = state._exact_roles
    frozen.role_target = state.role_target
    frozen.role_importance_pool = state.role_importance_pool
    determinizer = PublicStateDeterminizer()
    result = []
    for count in counts:
        for draw in range(draws):
            rng = random.Random(f"proposal-resample:{seed}:{count}:{draw}")
            sample = frozen.sample(evidence, witnesses, count, rng=rng)
            worlds = tuple(world for i, hypothesis in enumerate(sample.worlds)
                if (world := determinizer.determinize(hypothesis, evidence, view, rng=rng,
                    history_prior=True, force_history=i % 5 == 0, coherent_history=True)) is not None)
            result.append({"requested_worlds": count, "materialized_worlds": len(worlds),
                           "draw": draw, "fixed_role_pool": True,
                           "plan_scores": _probe(worlds, view, plans, seed, None, witnesses)
                           if worlds else []})
    return result


def audit_trajectory(row, *, matrix_proposals, joint_culprits=False, worlds=12, probe_position=None, probe_plans=(),
                     resample_counts=(), resample_draws=5, resample_plans=()):
    """Reconstruct samples along a recorded path; do not replay an AI policy."""
    archive = ReplayArchive.parse(row["replay_text"])
    game = Game(archive.scenario)
    seed = row.get("seed", 0)
    state = FactorizedBeliefState(capacity=max(192, worlds * 8), seed=seed,
                                 matrix_proposals=matrix_proposals, joint_culprits=joint_culprits)
    compiler, ledger, determinizer = FsbtxWitnessCompiler(), PublicEvidenceLedger(), PublicStateDeterminizer()
    recorded = {(s["loop"], s["day"]): s for s in row.get("protagonist_searches", ())}
    initial = [asdict(w) for w in compiler.compile(game.protagonist_team_view())]
    seen, roots, timeline = set(), [], []
    previous_facts = {_key(w): w for w in initial}
    final_map = None
    for number, command in enumerate(archive.commands, 1):
        view = game.protagonist_team_view()
        position = (game.state.loop, game.state.round)
        if game.state.phase == "protagonists" and position not in seen:
            seen.add(position)
            evidence = PublicEvidence.from_view(view)
            facts = ledger.update(view, compiler)
            before = state.proposal_summary()
            rng = random.Random(f"{seed}:{seed}:{ParticleEnsembleProtagonistAgent._sampling_hash(view)}")
            sampled = state.sample(evidence, facts, worlds, rng=rng)
            materialized = tuple(world for i, hypothesis in enumerate(sampled.worlds)
                if (world := determinizer.determinize(hypothesis, evidence, view, rng=rng,
                    history_prior=True, force_history=i % 5 == 0, coherent_history=True)) is not None)
            counts = ParticleEnsembleProtagonistAgent._counts(materialized, evidence) if materialized else ((), (), ())
            prior = _role_weights(state, facts)
            mass = sum(weight for _, weight in prior)
            truth = HiddenWorldHypothesis.from_scenario(archive.scenario)
            truth_roles = dict(truth.roles)
            saved = recorded.get(position)
            culprit_profile = _culprit_profile(state, evidence, facts)
            root = {"loop": position[0], "day": position[1], "command_number": number,
                "public_hash": ParticleEnsembleProtagonistAgent._sampling_hash(view),
                "public_board": {"characters": view["characters"], "locations": view["locations"],
                                 "pending": view["pending"]},
                "before": before, "after": state.proposal_summary(),
                "witnesses": [asdict(w) for w in facts],
                "truth_hard_compatible": FsbtxWitnessMatcher().matches(truth, facts),
                "approx_true_role_mass": {cid: (sum(weight for hypothesis, weight in prior
                    if dict(hypothesis.roles)[cid] == role) / mass if mass else None)
                    for cid, role in truth_roles.items()},
                "sampled_roles": counts[0], "sampled_culprits": counts[1], "sampled_dark_cards": counts[2],
                "culprit_profile": culprit_profile,
                "culprit_composition": _culprit_composition(culprit_profile),
                "recorded_search": saved,
                "recorded_sampling_matches": (all(json.loads(json.dumps(count)) == saved[field]
                    for count, field in zip(counts, ("belief_roles", "belief_culprits", "belief_dark_cards")))
                    if saved is not None and worlds == saved["particles"] else None)}
            if position == probe_position and materialized:
                root["union_plan_probe"] = _probe(materialized, view, probe_plans, seed, game, facts)
                root["resampling"] = resample_probe(state, evidence, facts, view,
                    resample_plans or probe_plans, counts=resample_counts, draws=resample_draws, seed=seed)
            roots.append(root)
        if command["action"] == "guess_all":
            facts = ledger.update(view, compiler)
            result = state.exact_role_map(PublicEvidence.from_view(view), facts)
            final_map = {"compatible_count": result.compatible_count,
                         "projection": "roles_and_plots_only_incidents_are_placeholders",
                         "selected_role_hard_compatible": (FsbtxWitnessMatcher().matches(
                             result.selected, state._role_witnesses(facts))
                             if result.selected else None),
                         "selected": asdict(result.selected) if result.selected else None,
                         "top": [{"world": asdict(h), "weight": weight} for h, weight in result.ranked],
                         "witnesses": [asdict(w) for w in facts]}
        cursor = len(view["events"])
        game.dispatch(command["actor"], command["action"],
                      **{k: v for k, v in command.items() if k not in {"actor", "action"}})
        after_view = game.protagonist_team_view()
        facts = {_key(asdict(w)): asdict(w) for w in compiler.compile(after_view)}
        timeline.append({"command_number": number, "recorded_command": command,
            "loop": position[0], "day": position[1], "phase_before": view["phase"],
            "public_events": after_view["events"][cursor:],
            "added_witnesses": [facts[k] for k in sorted(facts.keys() - previous_facts.keys())],
            "removed_witnesses": [previous_facts[k] for k in sorted(previous_facts.keys() - facts.keys())]})
        previous_facts = facts
    return {"scenario": row.get("scenario", archive.scenario["id"]), "strategy": row.get("strategy"),
            "seed": seed, "matrix_proposals": matrix_proposals, "worlds": worlds,
            "recorded_winner": game.winner, "initial_witnesses": initial,
            "roots": roots, "timeline": timeline, "final_map": final_map}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--scenario", action="append")
    parser.add_argument("--strategy", choices=("strategic", "joint"))
    parser.add_argument("--probe-loop", type=int)
    parser.add_argument("--probe-day", type=int)
    parser.add_argument("--worlds", type=int, default=12)
    parser.add_argument("--resample-worlds", type=int, action="append", default=[])
    parser.add_argument("--resample-draws", type=int, default=5)
    args = parser.parse_args()
    if args.worlds < 1 or (args.probe_loop is None) != (args.probe_day is None):
        parser.error("positive worlds and paired probe loop/day required")
    if any(x is not None and x < 1 for x in (args.probe_loop, args.probe_day)):
        parser.error("probe loop/day must be positive")
    if args.resample_draws < 1 or any(x < 1 for x in args.resample_worlds):
        parser.error("resample counts/draws must be positive")
    if args.resample_worlds and args.probe_loop is None:
        parser.error("resampling requires a probe root")
    raw = [p.read_bytes() for p in (args.before, args.after)]
    reports = [json.loads(x) for x in raw]
    if any(not r.get("progress", {}).get("complete") for r in reports):
        parser.error("both inputs must be complete reports")
    key = lambda row: (row["scenario"], row["strategy"], row["seed"])
    before = {key(r): r for r in reports[0]["results"]}
    pairs = [(before[key(r)], r) for r in reports[1]["results"] if key(r) in before
             and (not args.scenario or r["scenario"] in args.scenario)
             and (not args.strategy or r["strategy"] == args.strategy)]
    if not pairs:
        parser.error("no matching complete pairs")
    result = {"sources": source_digest(), "input_sha256": [hashlib.sha256(x).hexdigest() for x in raw],
              "settings": {"worlds": args.worlds, "probe": [args.probe_loop, args.probe_day],
                           "resample_counts": args.resample_worlds, "resample_draws": args.resample_draws},
              "developer_only": True, "progress": {"complete": False, "completed": 0, "planned": len(pairs)},
              "pairs": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_report(args.output, result)
    for a, b in pairs:
        position = (args.probe_loop, args.probe_day) if args.probe_loop is not None else None
        plans = {_key(c["bundle"]): c["bundle"] for row in (a, b)
                 for s in row.get("protagonist_searches", ()) if (s["loop"], s["day"]) == position
                 for c in s["candidates"]}
        selected = {_key(s["selected_bundle"]): s["selected_bundle"] for row in (a, b)
                    for s in row.get("protagonist_searches", ())
                    if (s["loop"], s["day"]) == position}
        paths = [audit_trajectory(row,
                                 matrix_proposals=row.get("matrix_proposals_enabled", enabled),
                                 joint_culprits=row.get("joint_culprits_enabled", False), worlds=args.worlds,
                                 probe_position=position, probe_plans=tuple(plans.values()),
                                 resample_counts=args.resample_worlds, resample_draws=args.resample_draws,
                                 resample_plans=tuple(selected.values()))
                 for row, enabled in ((a, False), (b, True))]
        commands = [ReplayArchive.parse(r["replay_text"]).commands for r in (a, b)]
        divergence = next((i for i, (x, y) in enumerate(zip(*commands), 1) if x != y), None)
        if divergence is None and len(commands[0]) != len(commands[1]):
            divergence = min(map(len, commands)) + 1
        result["pairs"].append({"first_command_divergence": divergence, "paths": paths})
        result["progress"].update(completed=len(result["pairs"]), complete=len(result["pairs"]) == len(pairs))
        write_report(args.output, result)
        print(f"{a['scenario']} / {a['strategy']}: {len(paths[0]['roots'])} + {len(paths[1]['roots'])} roots", flush=True)


if __name__ == "__main__":
    main()
