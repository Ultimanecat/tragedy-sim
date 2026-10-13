"""Compare finite role posteriors against independent printed-rule enumeration.

This measures inference error on common public observations, not game win rate.
No true script, real game, or action evaluator is an input to either sampler.
"""

import argparse
from collections import Counter
from dataclasses import replace
from itertools import permutations
from pathlib import Path
from statistics import mean
from time import perf_counter

from tragedy_sim.belief import ConstraintBeliefSampler, FactorizedBeliefState, HiddenWorldHypothesis, PublicEvidence
from tragedy_sim.belief_posterior import RolePosteriorTarget
from tragedy_sim.engine import RuleError
from tragedy_sim.scenario import validate_scenario
from tragedy_sim.witness import FsbtxWitnessMatcher, PublicWitness, WitnessStrength

from .ai_calibration_matrix import source_digest, write_report


def printed_worlds(evidence):
    """Independent permutations and validator, without matrix domains/count DP.

    These diagnostic cases have no extra characters or scheduled incidents.
    Preserve known plot selection, clear observed identities for initial sizes.
    """
    if evidence.schedule or {"copycat", "irregular", "part_timer"}.intersection(evidence.characters):
        raise ValueError("Accuracy enumeration requires ordinary slots and no schedule")
    setup = replace(evidence, known_roles=(), known_initial_roles=(), known_culprits=())
    found = {}
    for main, subplots, slots in ConstraintBeliefSampler._plot_slot_sets(setup):
        if sum(slots.values()) > len(setup.characters):
            continue
        bag = list(slots.elements()) + ["ordinary"] * (len(setup.characters) - sum(slots.values()))
        for assignment in set(permutations(bag)):
            try:
                scenario = validate_scenario({
                    "id": "accuracy-reference", "title": "reference", "module": setup.module,
                    "days": setup.days, "loops": setup.loops, "table_talk": setup.table_talk,
                    "main_plot": main, "subplots": list(subplots),
                    "cast": dict(zip(setup.characters, assignment)), "incidents": [],
                    **setup.setup_fields()})
            except RuleError:
                continue
            world = HiddenWorldHypothesis.from_scenario(scenario)
            found[FactorizedBeliefState._key(world)] = world
    return tuple(found[key] for key in sorted(found))


def reference_posterior(evidence, witnesses, worlds):
    sizes = Counter((world.main_plot, world.subplots) for world in worlds)
    target = RolePosteriorTarget(evidence)
    # Check production initial denominators against independent permutations.
    for plots, count in sizes.items():
        if target.plot_sizes[plots] != count:
            raise AssertionError("Initial prior size differs from printed enumeration")
    matcher = FsbtxWitnessMatcher()
    return tuple((world, 2 ** matcher.soft_score(world, witnesses) / sizes[world.main_plot, world.subplots])
                 for world in worlds
                 if evidence.matches_roles(world.main_plot, world.subplots, world.roles)
                 and matcher.matches(world, witnesses))


def marginals(posterior):
    total = sum(weight for _, weight in posterior)
    if total <= 0:
        raise ValueError("Empty posterior cannot produce probabilities")
    roles, plots, optional = Counter(), Counter(), Counter()
    for world, weight in posterior:
        mass = weight / total
        for cid, role in world.roles:
            roles[cid, role] += mass
        plots[world.main_plot, world.subplots] += mass
        optional[sum(role == "curmudgeon" for _, role in world.roles)] += mass
    return {"roles": roles, "plots": plots, "optional": optional}


def posterior_errors(reference, estimate):
    def distance(a, b):
        return sum(abs(a.get(key, 0) - b.get(key, 0)) for key in a.keys() | b.keys()) / 2
    characters = {cid for cid, _ in reference["roles"]}
    per_character = {
        cid: distance({role: p for (who, role), p in reference["roles"].items() if who == cid},
                      {role: p for (who, role), p in estimate["roles"].items() if who == cid})
        for cid in characters}
    return {"mean_role_tv": mean(per_character.values()),
            "max_role_tv": max(per_character.values()),
            "plot_tv": distance(reference["plots"], estimate["plots"]),
            "optional_count_tv": distance(reference["optional"], estimate["optional"])}


def default_cases():
    characters = ("doctor", "girl", "maiden", "student", "worker", "patient", "informer")
    fs = PublicEvidence("FS", 1, 1, True, characters, (), (), (), ("avenger", "hideous"))
    btx = replace(fs, module="BTX", known_plots=("bomb", "friends"))
    hard = PublicWitness("role_is", "girl", "brain", 1, 1, "query", "accuracy.hard")
    soft = PublicWitness("role_pressure", "friend", {"candidates": ["doctor"]},
                         1, 1, "loop_end", "accuracy.soft", WitnessStrength.SOFT)
    return (("fs_optional_prior", fs, ()), ("fs_optional_hard", fs, (hard,)),
            ("fs_optional_soft", fs, (soft,)), ("btx_plot_prior", btx, ()),
            ("btx_plot_soft", btx, (soft,)))


def compare_case(name, evidence, witnesses, worlds, *, trials, capacity):
    exact = reference_posterior(evidence, witnesses, worlds)
    reference = marginals(exact)
    rows = []
    for seed in range(trials):
        variants = (False, True) if seed % 2 == 0 else (True, False)
        for matrix in variants:
            state = FactorizedBeliefState(seed=seed, capacity=capacity,
                                          matrix_proposals=matrix, matrix_recovery=False)
            started = perf_counter()
            posterior = state.role_posterior(evidence, witnesses)
            elapsed = perf_counter() - started
            if any(not evidence.matches_roles(world.main_plot, world.subplots, world.roles)
                   or not FsbtxWitnessMatcher().matches(world, witnesses) for world, _ in posterior):
                raise AssertionError("Sampler violated hard evidence")
            rows.append({"seed": seed, "variant": "matrix" if matrix else "legacy",
                         "seconds": elapsed, "candidates": len(posterior),
                         "errors": posterior_errors(reference, marginals(posterior)),
                         "diagnostics": state.proposal_summary()})
    summary = {}
    for variant in ("legacy", "matrix"):
        selected = [row for row in rows if row["variant"] == variant]
        summary[variant] = {key: mean(row["errors"][key] for row in selected)
                            for key in selected[0]["errors"]}
        summary[variant]["mean_seconds"] = mean(row["seconds"] for row in selected)
    return {"case": name, "module": evidence.module, "characters": len(evidence.characters),
            "initial_worlds": len(worlds), "compatible_worlds": len(exact),
            "reference_optional_probabilities": dict(reference["optional"]),
            "summary": summary, "trials": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=16)
    parser.add_argument("--capacity", type=int, default=192)
    args = parser.parse_args()
    if min(args.trials, args.capacity) < 1:
        parser.error("trials and capacity must be positive")
    if args.output.exists():
        parser.error("report exists; choose a new output path")
    report = {"sources": source_digest(), "settings": {"trials": args.trials, "capacity": args.capacity},
              "progress": {"complete": False, "completed": 0, "planned": len(default_cases())}, "results": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_report(args.output, report)
    cache = {}
    for name, evidence, witnesses in default_cases():
        if evidence not in cache:
            cache[evidence] = printed_worlds(evidence)
        row = compare_case(name, evidence, witnesses, cache[evidence],
                           trials=args.trials, capacity=args.capacity)
        if source_digest() != report["sources"]:
            raise RuntimeError("Sources changed during accuracy evaluation")
        report["results"].append(row)
        report["progress"].update(completed=len(report["results"]),
                                  complete=len(report["results"]) == len(default_cases()))
        write_report(args.output, report)
        print(f"{name}: {row['summary']}", flush=True)


if __name__ == "__main__":
    main()
