"""Full-domain pure maximin using exact known-world continuation bounds."""

from dataclasses import dataclass, replace
from time import perf_counter

from ..transcript import describe_decision

from .cards import CompleteCardSpace
from .continuation import DayContinuationSolver, ValueBounds, WorkLimit


def _rewrite_committed_faces(clone, replacements):
    """Keep mastermind's own remembered choices consistent in a hypothesis.

    FS placements have no intervening effects. Public placement events and all
    red checkpoints hide these faces, so those histories must stay unchanged.
    Search inputs with a truncated history rewrite only their recorded suffix.
    """
    count = min(len(clone.history), len(clone.state.pending))
    if not count:
        return
    recorded, pending = clone.history[-count:], clone.state.pending[-count:]
    if any(command.get("action") != "play" or command.get("actor") != placement.actor
           or command.get("target") != placement.target for command, placement in zip(recorded, pending)):
        return
    faces = {p.target: p.card for p in replacements}
    changed = {}
    for index, placement in zip(range(len(clone.history)-count, len(clone.history)), pending):
        if placement.actor == "m":
            command = {**clone.history[index], "card": faces[placement.target]}
            clone.history[index] = command
            changed[index+1] = command
    for index, record in enumerate(clone.decisions):
        if record.number in changed:
            command = changed[record.number]
            arguments = {k: v for k, v in command.items() if k not in {"actor", "action"}}
            clone.decisions[index] = replace(record, arguments=arguments,
                                             description=describe_decision(clone, "m", "play", arguments))


def commit_pair(world, red, black, *, kernel=None):
    """Counterfactual card faces on a full clone; real root stays untouched."""
    existing = [p for p in world.state.pending if p.actor == "m"]
    available = set(world.state.hands["m"]) | {p.card for p in existing}
    faces = [p.card for p in black]
    if (len(black) != len(existing) or [p.target for p in black] != [p.target for p in existing]
            or any(p.actor != "m" for p in black) or len(set(faces)) != len(faces)
            or not set(faces).issubset(available)):
        raise ValueError("black bundle must preserve legal distinct physical cards and target slots")
    clone = world.clone() if kernel is None else kernel.clone(world)
    _rewrite_committed_faces(clone, black)
    replacements = iter(black)
    clone.state.pending = [next(replacements) if p.actor == "m" else p for p in clone.state.pending]
    clone.state.hands["m"] = [c for c in clone._deck("m") if c in available and c not in faces]
    for command in red:
        clone = clone.transition(command).game if kernel is None else kernel.transition(clone, command)
    if clone.state.phase != "reveal":
        raise ValueError("both complete bundles must end at reveal")
    return clone


@dataclass(frozen=True)
class PureDayResult:
    bounds: ValueBounds
    red_bundle: tuple[dict, ...] | None
    red_actions: int
    black_actions: int
    evaluated_red: int
    evaluated_pairs: int
    continuation_nodes: int
    continuation_transitions: int
    card_transitions: int
    stop_reason: str
    continuation_stop_reasons: tuple[str, ...]
    elapsed_seconds: float
    action_domain_complete: bool = True
    belief_domain_complete: bool = True
    information: str = "known-script-unknown-committed-black-faces"
    continuation: str = "all-engine-legal-decisions"
    horizon: str = "day"
    utility: str = "day-survival-v1"
    strategy_class: str = "pure"


class PureDaySolver:
    """Exhaustive action coverage, with only rigorous [0,1] bound cuts.

    One losing black response proves a red row's value zero. One fully
    certified winning row proves the global pure value one, without scanning
    other red rows. Unknown budget-limited cells retain [0,1].
    """

    def __init__(self, *, max_depth=256, backend="reference", cache_capacity=100000, edge_cache_capacity=0):
        if backend not in {"reference", "cached", "compiled"}:
            raise ValueError("backend must be reference, cached or compiled")
        if type(edge_cache_capacity) is not int or edge_cache_capacity < 0 or (backend == "reference" and edge_cache_capacity):
            raise ValueError("edge cache requires a cached/compiled backend and a nonnegative capacity")
        self.kernel = None
        if backend in {"cached", "compiled"}:
            from .cached import CachedDayContinuationSolver
            self.continuation = CachedDayContinuationSolver(max_depth=max_depth, capacity=cache_capacity,
                                                           compiled=backend == "compiled", edge_cache_capacity=edge_cache_capacity)
            self.kernel = self.continuation.kernel
        else:
            self.continuation = DayContinuationSolver(max_depth=max_depth)

    def solve(self, world, *, warmstarts=(), work=None):
        started = perf_counter()
        space = CompleteCardSpace(world)
        if space.prefix:
            raise ValueError("pure simultaneous game requires an uncommitted complete red bundle")
        work = work if work is not None else WorkLimit()
        node_start, edge_start = work.nodes, work.transitions
        black = tuple(space.black_bundles())
        if not black:
            raise ValueError("empty legal black domain")
        red_count = sum(1 for _ in space.red_bundles())
        if not red_count:
            raise ValueError("empty legal red domain")
        seen, starts = set(), []
        for plan in warmstarts:
            if not space.contains(plan):
                raise ValueError("warmstart must be a complete engine-legal red bundle")
            key = tuple((a["actor"], a["card"], a["target"]) for a in plan)
            if key not in seen:
                seen.add(key)
                starts.append(tuple(dict(a) for a in plan))

        def proposals():
            yield from starts
            for plan in space.red_bundles():
                key = tuple((a["actor"], a["card"], a["target"]) for a in plan)
                if key not in seen:
                    yield plan

        best_lower, best_plan = 0.0, None
        row_uppers = []
        pair_count = card_edges = 0
        continuation_reasons = set()
        reason = "complete_domain"
        for plan in proposals():
            if work.exhausted():
                reason = sorted(work.reasons)[0]
                break
            lo, hi = 1.0, 1.0
            checked = 0
            for faces in black:
                if work.exhausted():
                    break
                after = commit_pair(world, plan, faces, kernel=self.kernel)
                card_edges += len(plan)
                result = self.continuation.solve(after, work=work)
                continuation_reasons.update(result.stop_reasons)
                checked += 1
                pair_count += 1
                lo, hi = min(lo, result.bounds.lower), min(hi, result.bounds.upper)
                if hi == 0:
                    lo = 0.0
                    break
            if checked < len(black):
                lo = 0.0
            row_uppers.append(hi)
            if best_plan is None or lo > best_lower:
                best_lower, best_plan = lo, plan
            if best_lower == 1:
                reason = "proven_security_one"
                break
        upper = max(row_uppers) if len(row_uppers) == red_count else 1.0
        upper = max(upper, best_lower)
        if best_lower != upper:
            if work.reasons:
                reason = sorted(work.reasons)[0]
            elif continuation_reasons:
                reason = "continuation_incomplete"
        return PureDayResult(ValueBounds(best_lower, upper), best_plan, red_count, len(black),
                             len(row_uppers), pair_count, work.nodes - node_start,
                             work.transitions - edge_start, card_edges, reason,
                             tuple(sorted(continuation_reasons)), perf_counter() - started)
