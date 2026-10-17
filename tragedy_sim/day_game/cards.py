"""Full FS card domain, with an independent engine-transition enumerator.

No tactical pruning, filler equivalence, FI count constraint or shortlist.
The supplied world is explicitly script-informed, never a fair-player API.
"""

from itertools import product

from ..dark_attack_scenarios import legal_dark_bundles
from ..game import Game


def _check_root(world):
    if not isinstance(world, Game) or world.module != "FS":
        raise ValueError("complete day-game card domain currently requires an FS Game")
    if world.state.phase != "protagonists" or world.state.face_up:
        raise ValueError("requires an unrevealed protagonist placement root")
    if world.mastermind_plays != 3 or set(world.protagonist_order) != {"a", "b", "c"} or len(world.protagonist_order) != 3:
        raise ValueError("requires three black cards and three protagonist seats")
    black = [p for p in world.state.pending if p.actor == "m"]
    red = [p for p in world.state.pending if p.actor != "m"]
    if len(black) != 3 or len({p.target for p in black}) != 3:
        raise ValueError("requires three committed distinct black targets")
    if (len(red) >= 3 or len({p.target for p in red}) != len(red)
            or tuple(p.actor for p in red) != world.protagonist_order[:len(red)]):
        raise ValueError("protagonist placement prefix does not match seat order")


class CompleteCardSpace:
    """Unpruned FS simultaneous-card completions, respecting committed prefix.

    FS placements have no between-placement effects: the engine resolver's
    per-seat domains plus side-wide distinct targets define the product.
    Each seat retains its own actual remaining physical cards.
    """

    def __init__(self, world):
        _check_root(world)
        self.view = world.protagonist_team_view()
        self.prefix = tuple(p for p in world.state.pending if p.actor != "m")
        self.actors = world.protagonist_order[len(self.prefix):]
        resolver = world.ruleset.phases.resolve("protagonists")
        self.domains = tuple(tuple(resolver.card_actions(world, actor)) for actor in self.actors)
        self._domain_keys = tuple(frozenset((p["card"], p["target"]) for p in domain)
                                  for domain in self.domains)

    def red_bundles(self):
        for plan in product(*self.domains):
            if len({p["target"] for p in plan}) == len(plan):
                yield tuple(dict(p) for p in plan)

    def black_bundles(self):
        yield from legal_dark_bundles(self.view)

    def contains(self, plan):
        return (len(plan) == len(self.actors)
                and len({p.get("target") for p in plan}) == len(plan)
                and all(p.get("actor") == actor and p.get("action") == "play"
                        and set(p) == {"actor", "action", "card", "target"}
                        and (p.get("card"), p.get("target")) in domain
                        for p, actor, domain in zip(plan, self.actors, self._domain_keys)))


def engine_red_bundles(world):
    """Slow gold enumerator: every prefix uses the real atomic transition."""
    _check_root(world)

    def visit(current, prefix):
        if current.state.phase == "reveal":
            yield prefix
            return
        if current.state.phase != "protagonists":
            raise RuntimeError("FS card placement unexpectedly left the placement phase")
        for action in current.legal_actions(current.controller):
            if action["action"] != "play":
                raise RuntimeError("non-card action in FS placement phase")
            child = current.transition(action).game
            yield from visit(child, (*prefix, action))

    yield from visit(world, ())
