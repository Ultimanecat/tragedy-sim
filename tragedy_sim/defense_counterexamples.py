"""Bounded candidate-conditioned dark-card separation on hypothesis worlds.

Cheap tactical scans prioritize engine probes. Only engine-confirmed losses
enter the common scenario set. Neither a quiet scan nor a probe budget proves
universal survival; these branches never update posterior probabilities.
"""

from time import perf_counter

from .dark_attack_scenarios import legal_dark_bundles, with_dark_bundle
from .joint_action_space import JointPlacement
from .joint_defense_ranker import JointThreatRanker, TacticalWorldModel


def dark_signature(world):
    return tuple((p.target, p.card) for p in world.state.pending if p.actor == "m")


def refine_defense(root, view, space, worlds, candidates, rank, limit, verify_loss,
                   *, probe_limit=16, round_limit=8, deadline=None):
    """Return a reranked shortlist and shared scenes, scoped to one identity.

    ``verify_loss(world, commands)`` must use the authoritative engine and
    return whether any supported opponent continuation defeats the plan.
    ``worlds`` must share the same role/culprit hypothesis. Fair callers must
    refine each identity separately, preserving its original posterior mass.
    """
    if type(probe_limit) is not int or type(round_limit) is not int or min(probe_limit, round_limit) < 1:
        raise ValueError("positive integer counterexample budgets required")
    stats = {"legal_assignments": 0, "tactical_checks": 0, "engine_probes": 0,
             "rounds": 0, "added": 0, "enumerated_bundles": 0,
             "ranking_projections": 0,
             "complete_engine_scan": False, "stop": "round_limit", "examples": []}
    worlds = tuple(worlds)
    if any(w.roles != root.roles or w.scenario != root.scenario for w in worlds):
        raise ValueError("counterexample refinement requires one role/culprit hypothesis")
    expired = lambda: deadline is not None and perf_counter() >= deadline
    if expired():
        stats["stop"] = "deadline"
        return worlds, candidates, stats
    # Only public faces restrict this pool. Source is a determinized/authorized
    # hypothesis, never the real hidden-card game of a fair/blind caller.
    pool = []
    for faces in legal_dark_bundles(view):
        if expired():
            stats["stop"] = "deadline"
            return worlds, candidates, stats
        world = with_dark_bundle(root, faces)
        pool.append((dark_signature(world), world, TacticalWorldModel(world, space)))
    stats["legal_assignments"] = len(pool)
    known = {dark_signature(w) for w in worlds}
    checked = set()
    for _ in range(round_limit):
        if expired():
            stats["stop"] = "deadline"
            break
        stats["rounds"] += 1
        proposals = []
        for candidate in candidates:
            plan = tuple(JointPlacement(p["actor"], p["card"], p["target"]) for p in candidate)
            effects = tuple((p.actor, p.card, p.target) for p in plan)
            for signature, world, model in pool:
                if signature in known or (effects, signature) in checked:
                    continue
                risk, value = model.score(plan)
                stats["tactical_checks"] += 1
                if risk > 0:
                    proposals.append((-risk, value, effects, signature, candidate, world))
        proposals.sort(key=lambda p: p[:4])
        added = []
        for _, _, effects, signature, candidate, world in proposals:
            if signature in known or (effects, signature) in checked:
                continue
            if expired() or stats["engine_probes"] >= probe_limit:
                stats["stop"] = "deadline" if expired() else "probe_limit"
                break
            checked.add((effects, signature))
            stats["engine_probes"] += 1
            if verify_loss(world, candidate):
                known.add(signature)
                added.append(world)
                stats["added"] += 1
                stats["examples"].append({"dark_cards": [list(p) for p in signature],
                                          "defeated_plan": [dict(p) for p in candidate]})
                # Rerank promptly instead of spending every probe on stale
                # candidates. All returned plans share all retained witnesses.
                break
        if not added:
            if stats["stop"] not in {"deadline", "probe_limit"}:
                stats["stop"] = "no_verified_counterexample"
            break
        worlds += tuple(added)
        ranker = JointThreatRanker(worlds, space)
        candidates, count = space.ranked_bundles(rank, limit, joint_rank=ranker, distinct_effects=True)
        stats["enumerated_bundles"] += count
        stats["ranking_projections"] += ranker.projections
    return worlds, candidates, stats
