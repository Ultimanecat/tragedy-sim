"""FS/BTX team placements from an authorized view, without game cloning.

This is an immediate-effect defense space. Ordinary ineffective board fillers
are retained explicitly; resource-changing actions keep their seat identity.
The caller supplies any proven defense clauses. No role or true game is read.
"""

from collections import Counter
from dataclasses import dataclass
from heapq import nsmallest
from itertools import product

from .belief_dark_constraints import dark_card_domains
from .cards import COORDS, HERO_CARDS, PROTAGONISTS


class UnsupportedJointSpace(ValueError):
    """A public rule feature needs the general engine placement path."""


@dataclass(frozen=True, order=True)
class JointPlacement:
    actor: str
    card: str
    target: str

    def command(self):
        return {"actor": self.actor, "action": "play", "card": self.card, "target": self.target}

    @property
    def effect(self):
        return self.card, self.target


@dataclass(frozen=True)
class DefenseRequirement:
    """OR of ANDs of (card, target) effects, proven necessary by the caller.

    An empty conjunction means already satisfied. An empty disjunction means
    unsatisfiable, never a reason to infer that the whole game is unwinnable.
    """

    alternatives: tuple[tuple[tuple[str, str], ...], ...]
    source: str


def _placement(action):
    if action.get("action") == "play":
        return JointPlacement(action["actor"], action["card"], action["target"])
    if str(action.get("type", "")).removeprefix("core.") != "play":
        raise UnsupportedJointSpace("placement-only offers required")
    return JointPlacement(action["actor"], action["parameters"]["card"], action["parameters"]["target"])


def _move(location, faces, forbidden):
    x, y = COORDS[location]
    for face in set(faces):
        dx, dy = {"h": (1, 0), "v": (0, 1), "d": (1, 1)}.get(face, (0, 0))
        x, y = x ^ dx, y ^ dy
    destination = next(board for board, point in COORDS.items() if point == (x, y))
    return location if destination in forbidden else destination


class JointActionSpace:
    def __init__(self, view, offers):
        if view.get("module") not in {"FS", "BTX"} or view.get("phase") != "protagonists":
            raise UnsupportedJointSpace("FS/BTX protagonist placement phase required")
        if set(view.get("locations", ())) != set(COORDS):
            raise UnsupportedJointSpace("standard four-board layout required")
        if any(c.get("echo_board_actions") for c in view.get("characters", {}).values()):
            raise UnsupportedJointSpace("board echoes require engine-level equivalence")
        if view.get("module") == "BTX" and any(
                c.get("alive") and c.get("present") and c.get("paranoia", 0) >= 3
                for c in view.get("characters", {}).values()):
            # Virus checks all living characters on any counter mutation,
            # including a clamped -1 at zero. Numeric equality alone cannot
            # prove a no-op without plot/current-role invariants.
            raise UnsupportedJointSpace("high-paranoia BTX mutation invariants require engine equivalence")
        order = tuple(view.get("protagonist_order", ()))
        if len(order) != 3 or set(order) != set(PROTAGONISTS):
            raise UnsupportedJointSpace("three distinct protagonist seats required")
        self.prefix = tuple(JointPlacement(p["actor"], p["card"], p["target"])
                            for p in view.get("pending", ()) if p.get("actor") in PROTAGONISTS)
        if (any(p.card is None for p in self.prefix)
                or len({p.actor for p in self.prefix}) != len(self.prefix)
                or len({p.target for p in self.prefix}) != len(self.prefix)):
            raise UnsupportedJointSpace("visible, valid team placement prefix required")
        played = {p.actor for p in self.prefix}
        self.actors = tuple(actor for actor in order if actor not in played)
        first = tuple(_placement(offer) for offer in offers)
        if not self.actors or not first or any(p.actor != self.actors[0] for p in first):
            raise UnsupportedJointSpace("offers must belong to the next unplayed seat")
        hands = view.get("team_hands", {})
        cards = {c.id: c for c in HERO_CARDS}
        if any(actor not in hands or not hands[actor] or len(set(hands[actor])) != len(hands[actor])
               or not set(hands[actor]).issubset(cards) for actor in self.actors):
            raise UnsupportedJointSpace("complete standard team hands required")
        targets = tuple(sorted({p.target for p in first}))
        occupied = {p.target for p in self.prefix}
        if any(t in occupied or t not in {*view["characters"], *COORDS} for t in targets):
            raise UnsupportedJointSpace("offers contain unavailable targets")
        # Shared FS/BTX card-target permissions are rectangular for every seat.
        if set(first) != {JointPlacement(self.actors[0], card, target)
                          for card in hands[self.actors[0]] for target in targets}:
            raise UnsupportedJointSpace("card-specific permissions require the engine path")
        _, domains, slot_targets = dark_card_domains(view)
        black = {target: domains[slot] for slot, target in slot_targets.items()}
        prefix_forbids = sum(p.card == "fi" for p in self.prefix)
        # A bad committed prefix is immutable: allow legal completions with no
        # further FI instead of making the entire action space disappear.
        self.additional_forbids = max(0, 1 - prefix_forbids)
        self.prefix_forbid_overflow = prefix_forbids > 1
        removed = Counter()
        result, fillers = [], []

        def reason(card, target):
            faces = black.get(target, set())
            if target in COORDS:
                return None if card == "fi" and faces & {"i1", "i2"} else "board_no_effect"
            char = view["characters"][target]
            location, forbidden = char["location"], char.get("forbidden", ())
            if card == "fi" and not faces & {"i1", "i2"}:
                return "intrigue_forbid_no_effect"
            if card == "fm" and not any(_move(location, (face,), forbidden) != location
                                         for face in faces & {"h", "v", "d"}):
                return "movement_forbid_no_effect"
            if card == "p-1" and char.get("paranoia", 0) == 0 and not faces & {"p1a", "p1b"}:
                return "paranoia_decrease_no_effect"
            if card in {"h", "v"} and not any(
                    _move(location, (face, card), forbidden) != _move(location, (face,), forbidden)
                    for face in (faces or {None})):
                return "movement_no_effect"
            return None

        for actor in self.actors:
            meaningful = []
            for card in hands[actor]:
                for target in targets:
                    why = "intrigue_forbid_budget" if card == "fi" and not self.additional_forbids else reason(card, target)
                    if why:
                        removed[why] += 1
                    else:
                        meaningful.append(JointPlacement(actor, card, target))
            ordinary = [c for c in ("g1", "h", "v", "p1") if c in hands[actor]]
            filler_cards = ordinary[:1] or [c for c in hands[actor] if c != "fi"]
            actor_fillers = tuple(JointPlacement(actor, card, board)
                                  for card in filler_cards for board in targets if board in COORDS)
            fillers.extend(actor_fillers)
            result.append(tuple(sorted({*meaningful, *actor_fillers})))
        self.domains = tuple(result)
        self.filler_placements = frozenset(fillers)
        self.pruning = dict(sorted(removed.items()))
        self.raw_seat_actions = tuple(len(hands[a]) * len(targets) for a in self.actors)

    def iter_plans(self, requirements=()):
        requirements = tuple(requirements)
        prefix_effects = {p.effect for p in self.prefix}
        possible = prefix_effects | {p.effect for domain in self.domains for p in domain}
        clauses, fixed = [], set()
        for req in requirements:
            alternatives = [frozenset(alternative) for alternative in req.alternatives
                            if set(alternative).issubset(possible)]
            if not alternatives:
                return
            clauses.append(tuple(alternatives))
            if len(alternatives) == 1:
                fixed.update(alternatives[0] - prefix_effects)
        if len({target for _, target in fixed}) != len(fixed):
            return
        reserved = dict((target, card) for card, target in fixed)
        domains = tuple(tuple(p for p in domain if p.target not in reserved or p.card == reserved[p.target])
                        for domain in self.domains)
        # Propagate an effect that has only one possible owning seat.
        owners = {}
        for effect in fixed:
            seats = [i for i, domain in enumerate(domains) if any(p.effect == effect for p in domain)]
            if not seats:
                return
            if len(seats) == 1:
                index = seats[0]
                if index in owners and owners[index] != effect:
                    return
                owners[index] = effect
        domains = tuple(tuple(p for p in domain if i not in owners or p.effect == owners[i])
                        for i, domain in enumerate(domains))
        for plan in product(*domains):
            if len({p.target for p in plan}) != len(plan):
                continue
            if sum(p.card == "fi" for p in plan) > self.additional_forbids:
                continue
            if clauses:
                effects = prefix_effects | {p.effect for p in plan}
                if not all(any(alternative.issubset(effects) for alternative in clause) for clause in clauses):
                    continue
            yield plan

    def ranked_bundles(self, rank, limit, *, requirements=(), joint_rank=None, distinct_effects=False):
        """Scan the whole space; shortlist by a supplied ordering, not proof.

        Node limits bound expensive engine evaluations. The ranker can later
        use joint threat features without changing the legal-space component.
        """
        if type(limit) is not int or limit < 1:
            raise ValueError("shortlist limit must be a positive integer")
        values = {p: rank(p.command()) for domain in self.domains for p in domain}
        enumerated = 0
        signatures = set()
        once = {c.id for c in HERO_CARDS if c.once_per_loop}

        def scored():
            nonlocal enumerated
            for plan in self.iter_plans(requirements):
                enumerated += 1
                if distinct_effects:
                    # A shortlist ordering equivalence, not an exhaustive
                    # future-policy certificate. Keep every scarce owner.
                    signature = (tuple(sorted(p.effect for p in plan if p not in self.filler_placements)),
                                 tuple(sorted((p.actor, p.card) for p in plan if p.card in once)))
                    if signature in signatures:
                        continue
                    signatures.add(signature)
                value = joint_rank(plan) if joint_rank is not None else sum(values[p] for p in plan)
                fields = value if isinstance(value, tuple) else (value,)
                yield tuple(-v for v in fields), plan

        selected = nsmallest(limit, scored())
        return tuple(tuple(p.command() for p in plan) for _, plan in selected), enumerated
