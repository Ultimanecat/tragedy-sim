"""Complete joint-space counts and sampled engine legality on FS/BTX roots.

Initial roots are synthetic and this is not a win-rate experiment. All three
partial-prefix depths are checked. Unsupported mechanisms stay explicit.
"""

import argparse
import hashlib
import json
from pathlib import Path
import random
from time import perf_counter

from tragedy_sim import Game
from tragedy_sim.joint_action_space import JointActionSpace, UnsupportedJointSpace
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.scenario_library import ScenarioLibrary

from .ai_calibration_matrix import source_digest, write_report


DEFAULT_SCENARIOS = ("official-fs-01-first-script", "official-tragic-aiplay-fs-02g",
                     "official-btx-04-young-womens-battlefield", "official-btx-06-secret-that-was-kept",
                     "community-tragic-aiplay-btx-41", "community-tragic-aiplay-btx-45")


def validate_scenario(scenario, *, samples=16, limit=32):
    if min(samples, limit) < 1:
        raise ValueError("counts must be positive")
    game = Game(scenario)
    while game.state.phase != "protagonists":
        game = game.search_transition(game.search_actions(game.controller)[0])
    rows = []
    for prefix_depth in range(3):
        view = game.protagonist_team_view()
        before = game.view("m")
        try:
            space = JointActionSpace(view, game.search_actions(game.controller))
        except UnsupportedJointSpace as error:
            rows.append({"prefix_depth": prefix_depth, "unsupported": str(error)})
            break
        started = perf_counter()
        plans = list(space.iter_plans())
        enumeration_ms = 1000 * (perf_counter() - started)
        selected = random.Random(prefix_depth).sample(plans, min(samples, len(plans)))
        for plan in selected:
            if ParticleEnsembleProtagonistAgent._apply_bundle(game, tuple(p.command() for p in plan)) is None:
                raise AssertionError("joint space emitted an engine-illegal plan")
        ranked, counted = space.ranked_bundles(lambda command: int(command["card"] == "fi"), limit)
        if counted != len(plans) or len(ranked) != min(limit, len(plans)):
            raise AssertionError("shortlist did not scan the complete declared space")
        if before != game.view("m"):
            raise AssertionError("validation changed the original game")
        rows.append({"prefix_depth": prefix_depth, "raw_seat_actions": space.raw_seat_actions,
                     "filtered_seat_actions": [len(d) for d in space.domains],
                     "plans": len(plans), "enumeration_ms": enumeration_ms,
                     "sampled_engine_legal_plans": len(selected), "shortlist": len(ranked),
                     "pruning": space.pruning, "fillers": len(space.filler_placements)})
        if not plans:
            raise AssertionError("ordinary synthetic root unexpectedly has no defense plans")
        command = plans[0][0].command()
        game.dispatch(command.pop("actor"), command.pop("action"), **command)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", action="append")
    parser.add_argument("--samples", type=int, default=16)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.samples < 1 or args.output.exists():
        parser.error("use positive samples and a new output path")
    library = ScenarioLibrary()
    sources = source_digest()
    report = {"sources": sources, "scope": "synthetic_roots_space_and_sampled_legality_not_match_strength",
              "results": [], "complete": False}
    for sid in dict.fromkeys(args.scenario or DEFAULT_SCENARIOS):
        scenario = library.get(sid)
        report["results"].append({"scenario": sid,
                                  "scenario_sha256": hashlib.sha256(json.dumps(scenario, ensure_ascii=False).encode()).hexdigest(),
                                  "roots": validate_scenario(scenario, samples=args.samples)})
    if sources != source_digest():
        raise RuntimeError("sources changed during validation")
    report["complete"] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_report(args.output, report)
    print([(r["scenario"], [(root["prefix_depth"], root.get("plans"), root.get("unsupported"))
                             for root in r["roots"]]) for r in report["results"]])


if __name__ == "__main__":
    main()
