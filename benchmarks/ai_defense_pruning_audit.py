"""Measure joint-card enumeration separately from full engine evaluation.

These filters measure immediate-effect candidates, not a complete legal policy:
mandatory no-op fillers, future resource costs and observation equivalence still
need explicit treatment before production integration. No player AI is changed.
"""

import argparse
from itertools import product
import json
from pathlib import Path
import random
from statistics import median
from time import perf_counter

from tragedy_sim import Game
from tragedy_sim.belief_dark_constraints import dark_card_domains
from tragedy_sim.cards import COORDS
from tragedy_sim.oracle_protagonist import OracleProtagonistAgent
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.replay import ReplayArchive
from tragedy_sim.scenario_library import ScenarioLibrary

from .ai_calibration_matrix import source_digest, write_report


MOVEMENTS = {"h": (1, 0), "v": (0, 1), "d": (1, 1)}


def destination(game, target, faces):
    character = game.state.characters[target]
    x, y = COORDS[character.location]
    for face in set(faces):
        if face in MOVEMENTS:
            dx, dy = MOVEMENTS[face]
            x, y = x ^ dx, y ^ dy
    board = next(b for b, xy in COORDS.items() if xy == (x, y))
    if board in character.forbidden or not game._movement_destination_allowed(target, board):
        return character.location
    return board


def action_domains(game, mode):
    if game.module not in {"FS", "BTX"} or game.state.phase != "protagonists":
        raise ValueError("this diagnostic requires an FS/BTX protagonist root")
    if mode not in {"raw", "literal", "conditional", "defense"}:
        raise ValueError("unknown pruning mode")
    view = game.protagonist_team_view()
    if any(c.get("echo_board_actions") for c in view["characters"].values()):
        raise ValueError("board echo effects need separate filter validation")
    placed = {p.actor for p in game.state.pending}
    actors = tuple(a for a in game.protagonist_order if a not in placed)
    targets = sorted({a["target"] for a in game.search_actions(game.controller) if a["action"] == "play"})
    _, slots, slot_targets = dark_card_domains(view)
    faces = {target: slots[slot] for slot, target in slot_targets.items()}

    def keep(face, target):
        if mode == "raw":
            return True
        possible = faces.get(target, set())
        if target in view["locations"]:
            return face == "fi" and bool(possible & {"i1", "i2"})
        character = view["characters"][target]
        if face == "fi" and not possible & {"i1", "i2"}:
            return False
        if face == "fm":
            return any(destination(game, target, (black,)) != character["location"]
                       for black in possible & MOVEMENTS.keys())
        if face == "p-1" and character["paranoia"] == 0:
            return mode != "literal" and bool(possible & {"p1a", "p1b"})
        if face in {"h", "v"}:
            if mode == "literal":
                return destination(game, target, (face,)) != character["location"]
            return any(destination(game, target, (black, face)) != destination(game, target, (black,))
                       for black in (possible or {None}))
        return not (mode == "defense" and face == "p1")

    return tuple(tuple((actor, face, target) for face in game.state.hands[actor]
                       for target in targets if keep(face, target)) for actor in actors)


def enumerate_plans(domains, *, forbid_limit=None):
    for plan in product(*domains):
        if len({p[2] for p in plan}) != len(plan):
            continue
        if forbid_limit is not None and sum(p[1] == "fi" for p in plan) > forbid_limit:
            continue
        yield plan


def audit_game(game, *, engine_samples=32, repeats=5):
    if min(engine_samples, repeats) < 1:
        raise ValueError("sample counts must be positive")
    modes = {}
    for mode in ("raw", "literal", "conditional", "defense"):
        domains = action_domains(game, mode)
        times = []
        for _ in range(repeats):
            started = perf_counter()
            count = sum(1 for _ in enumerate_plans(domains, forbid_limit=1 if mode == "defense" else None))
            times.append(perf_counter() - started)
        modes[mode] = {"seat_actions": [len(d) for d in domains], "joint_plans": count,
                       "enumeration_median_ms": 1000 * median(times)}
    plans = list(enumerate_plans(action_domains(game, "conditional")))
    sampled = random.Random(0).sample(plans, min(engine_samples, len(plans)))
    oracle = OracleProtagonistAgent(reveal_cards=True, script_aware_rollout=False)
    routes = oracle._mastermind_strategy_options(game)
    started, evaluations = perf_counter(), 0
    for plan in sampled:
        commands = tuple({"actor": a, "action": "play", "card": c, "target": t} for a, c, t in plan)
        successor = ParticleEnsembleProtagonistAgent._apply_bundle(game, commands)
        if successor is None:
            raise AssertionError("enumeration emitted an engine-illegal plan")
        for route in routes:
            oracle._day_score(successor, game.state.loop, game.state.round, mastermind_strategy=route)
            evaluations += 1
    elapsed = perf_counter() - started
    return {"loop": game.state.loop, "day": game.state.round, "modes": modes,
            "engine": {"plans": len(sampled), "routes": len(routes), "evaluations": evaluations,
                       "seconds": elapsed, "ms_per_plan_all_routes": elapsed * 1000 / len(sampled) if sampled else None},
            "scope": "immediate_effect_domain_diagnostic_no_fillers_no_complete_defense_proof"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--variant", default="partition")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--loop", type=int, default=2)
    parser.add_argument("--day", type=int, default=3)
    parser.add_argument("--engine-samples", type=int, default=32)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or min(args.engine_samples, args.loop, args.day) < 1:
        parser.error("use positive counts and a new output path")
    if args.report:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        if not report.get("progress", {}).get("complete"):
            parser.error("a completed replay report is required")
        rows = [r for r in report["results"] if r["scenario"] == args.scenario
                and r["variant"] == args.variant and r["seed"] == args.seed]
        if len(rows) != 1:
            parser.error("selectors must identify one match")
        archive = ReplayArchive.parse(rows[0]["replay_text"])
        game = Game(archive.scenario)
        for command in archive.commands:
            if game.state.phase == "protagonists" and (game.state.loop, game.state.round) == (args.loop, args.day):
                break
            game.dispatch(**command)
        else:
            parser.error("requested root was not reached")
        scope = "replayed_root"
    else:
        game = Game(ScenarioLibrary().get(args.scenario))
        while game.state.phase != "mastermind":
            game = game.search_transition(game.search_actions(game.controller)[0])
        targets = list(game.state.characters)
        targets = list(dict.fromkeys([t for t in ("girl", "worker", "school") if t in targets or t == "school"] + targets))
        for face, target in zip(("h", "i1", "v"), targets[:3]):
            game.dispatch("m", "play", card=face, target=target)
        scope = "synthetic_first_day_public_targets"
    sources = source_digest()
    result = audit_game(game, engine_samples=args.engine_samples)
    if sources != source_digest():
        raise RuntimeError("sources changed during measurement")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_report(args.output, {"sources": sources, "scenario": args.scenario, "root_scope": scope, **result})
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
