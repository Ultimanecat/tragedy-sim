"""Publicly legal dark bundles and bounded hypothesis-conditioned attacks.

Attack probes are adversarial search branches, not posterior draws. A sampled
role world is allowed as input; the real script is never an inference input.
Keep these probes outside belief counts, probability estimates and witness.
"""

from .belief_dark_constraints import dark_card_domains
from .cards import COORDS, deck
from .engine import Placement
from itertools import permutations


def tactical_dark_key(bundle, locations):
    """FS/BTX immediate-effect class, retaining limited-card consumption.

    Group only already-legal concrete assignments. Keep their members for
    engine probes, future hands, observations, and policy RNG differences.
    """
    cards = deck("m")
    effects, limited = [], []
    for p in bundle:
        card = cards[p.card]
        effect, amount = card.effect, card.amount
        if p.target in locations and effect != "intrigue":
            effect, amount = "noop", 0
        effects.append((p.target, effect, amount))
        if card.once_per_loop:
            limited.append(p.card)
    return tuple(effects), tuple(sorted(limited))


def legal_dark_bundles(view):
    """Enumerate every distinct physical face assignment to the public slots."""
    _, domains, targets = dark_card_domains(view)
    slots = tuple(domains)
    chosen, used = {}, set()

    def visit(index):
        if index == len(slots):
            yield tuple(Placement("m", chosen[slot], targets[slot]) for slot in slots)
            return
        slot = slots[index]
        for face in sorted(domains[slot] - used):
            chosen[slot] = face
            used.add(face)
            yield from visit(index + 1)
            used.remove(face)
            del chosen[slot]

    yield from visit(0)


def with_dark_bundle(source, bundle):
    """Clone a hypothesis, preserve red placements and canonical black hand."""
    existing = [p for p in source.state.pending if p.actor == "m"]
    if [p.target for p in existing] != [p.target for p in bundle]:
        raise ValueError("dark bundle must preserve all public target slots")
    faces = [p.card for p in bundle]
    available = set(source.state.hands["m"]) | {p.card for p in existing}
    if (any(p.actor != "m" for p in bundle) or len(set(faces)) != len(faces)
            or not set(faces).issubset(available)):
        raise ValueError("dark bundle violates the hypothesis hand or all-different rule")
    world = source.search_clone()
    replacements = iter(bundle)
    world.state.pending = [next(replacements) if p.actor == "m" else p for p in world.state.pending]
    world.state.hands["m"] = [face for face in world._deck("m")
                              if face in available and face not in faces]
    return world


def _complete(domains, forced, preferred):
    if any(face not in domains.get(slot, ()) for slot, face in forced.items()):
        return None
    if len(set(forced.values())) != len(forced):
        return None
    slots = sorted(domains, key=lambda s: (s not in forced, s))
    chosen, used = {}, set()

    def visit(index):
        if index == len(slots):
            return dict(chosen)
        slot = slots[index]
        values = [forced[slot]] if slot in forced else sorted(
            domains[slot], key=lambda face: (face != preferred[slot], face))
        for face in values:
            if face in used:
                continue
            chosen[slot] = face
            used.add(face)
            result = visit(index + 1)
            if result is not None:
                return result
            used.remove(face)
            del chosen[slot]
        return None

    return visit(0)


def marginal_dark_worlds(source, view):
    """Cover each legal slot/face in a complete all-different assignment.

    These are one-factor probes around a sampled baseline, not probabilities
    and not full Cartesian coverage. Other slots may change to free a forced
    physical card. Include the baseline and deduplicate full assignments.
    """
    _, domains, targets = dark_card_domains(view)
    placements = [p for p in source.state.pending if p.actor == "m"]
    preferred = {str(i): p.card for i, p in enumerate(placements)}
    result, seen = [], set()
    for slot in domains:
        for face in sorted(domains[slot]):
            completed = _complete(domains, {slot: face}, preferred)
            if completed is None:
                raise AssertionError("an arc-supported slot/face lacked a full assignment")
            signature = tuple(completed[s] for s in domains)
            if signature in seen:
                continue
            seen.add(signature)
            result.append(with_dark_bundle(source, tuple(Placement("m", completed[s], targets[s]) for s in domains)))
    return tuple(result)


def marginal_guard_worlds(source, view, *, limit=8):
    """Original draw plus templates and all supported slot/face probes.

    Keep physical faces/resources; deduplicate only identical complete dark
    signatures. This is one hypothesis's adversarial group, never extra mass.
    Coverage is marginal plus bounded templates, not full Cartesian minimax.
    """
    variants = (source, *attack_dark_worlds(source, view, limit=limit),
                *marginal_dark_worlds(source, view))
    unique = {}
    for world in variants:
        signature = tuple((p.target, p.card) for p in world.state.pending if p.actor == "m")
        unique.setdefault(signature, world)
    return tuple(unique.values())


def attack_dark_worlds(source, view, *, limit=8):
    """Up to ``limit`` extra legal probes, prioritized by current role threats.

    This is bounded scenario coverage, not exhaustive minimax and not a
    calibrated distribution. Full engine rollouts decide whether a template
    actually threatens loss. Public faces/discards/disabled cards stay fixed.
    """
    if type(limit) is not int or limit < 1:
        raise ValueError("attack probe limit must be a positive integer")
    _, domains, targets = dark_card_domains(view)
    placements = [p for p in source.state.pending if p.actor == "m"]
    preferred = {str(index): p.card for index, p in enumerate(placements)}
    slots = {target: slot for slot, target in targets.items()}
    characters = source.state.characters
    live = [cid for cid, c in characters.items() if c.alive and c.present]
    templates = []

    def force(target, face):
        slot = slots.get(target)
        return {slot: face} if slot is not None else None

    def movement(cid, destination):
        c = characters[cid]
        if destination == c.location or destination in c.forbidden:
            return None
        x, y = COORDS[c.location]
        a, b = COORDS[destination]
        return "d" if x != a and y != b else "h" if x != a else "v"

    def add(template):
        if template and template not in templates:
            templates.append(template)

    keys = [cid for cid in live if source._has(cid, "key")]
    victims = [cid for cid in live if source._has(cid, "key") or source._has(cid, "friend")]
    for killer in (cid for cid in live if source._has(cid, "killer")):
        for face in ("i2", "i1"):
            add(force(killer, face))
        for key in keys:
            move = movement(killer, characters[key].location)
            alignment = force(killer, move) if move else None
            add(alignment)
            for face in ("i2", "i1"):
                intrigue = force(key, face)
                if alignment and intrigue:
                    add({**alignment, **intrigue})
                add(intrigue)
            move = movement(key, characters[killer].location)
            if move:
                add(force(key, move))
    for serial in (cid for cid in live if source._has(cid, "serial")):
        for victim in victims:
            if victim == serial:
                continue
            for mover, destination in ((serial, characters[victim].location),
                                       (victim, characters[serial].location)):
                move = movement(mover, destination)
                if move:
                    add(force(mover, move))
    for slot, target in targets.items():
        if target in view.get("locations", {}) or target in keys:
            for face in ("i2", "i1"):
                add({slot: face})
    today = next((item for item in source.scenario["incidents"]
                  if item["day"] == source.state.round), None)
    if today:
        for face in ("p1a", "p1b", "fp"):
            add(force(today["culprit"], face))
    result, seen = [], {tuple(p.card for p in placements)}
    for forced in templates:
        completed = _complete(domains, forced, preferred)
        if completed is None:
            continue
        signature = tuple(completed[slot] for slot in domains)
        if signature in seen:
            continue
        seen.add(signature)
        bundle = tuple(Placement("m", completed[slot], targets[slot]) for slot in domains)
        result.append(with_dark_bundle(source, bundle))
        if len(result) >= limit:
            break
    return tuple(result)


def evacuation_bundles(source, view, bases):
    """Joint relocation/Forbid-Movement proposals from a role hypothesis.

    Cover a three-card conjunction: lock the killer, evacuate the Key, and
    clear a Serial from the evacuation destination when necessary. These are
    merely candidates; hidden card combinations can still defeat a proposal.
    Engine validation, available seats and common-world scoring stay external.
    """
    if not bases or len(bases[0]) != 3:
        return ()
    live = {cid: c for cid, c in source.state.characters.items() if c.alive and c.present}
    targeted = {p["target"] for p in view.get("pending", ()) if p["actor"] == "m"}
    actors = tuple(command["actor"] for command in bases[0])
    hands = view.get("team_hands", {})
    moves = (("h", (1, 0)), ("v", (0, 1)), ("d", (1, 1)))
    results = []
    for killer in (cid for cid in live if cid in targeted and source._has(cid, "killer")):
        for key in (cid for cid in live if cid != killer and source._has(cid, "key")):
            for card, (dx, dy) in moves:
                x, y = COORDS[live[key].location]
                destination = next(board for board, point in COORDS.items() if point == (x ^ dx, y ^ dy))
                if destination in live[key].forbidden:
                    continue
                assignments = [("fm", killer), (card, key)]
                serial = next((cid for cid in live if cid not in {key, killer}
                               and source._has(cid, "serial") and live[cid].location == destination), None)
                if serial is not None:
                    third = next(((face, serial) for face, (sx, sy) in moves
                                  if next(board for board, point in COORDS.items()
                                          if point == (COORDS[destination][0] ^ sx, COORDS[destination][1] ^ sy))
                                  not in live[serial].forbidden), None)
                else:
                    third = next(((p["card"], p["target"]) for base in bases for p in base
                                  if p["target"] not in {key, killer}), None)
                if third is None:
                    continue
                assignments.append(third)
                for ordered in permutations(assignments):
                    if any(face not in hands.get(actor, ()) for actor, (face, _) in zip(actors, ordered)):
                        continue
                    result = tuple({"actor": actor, "action": "play", "card": face, "target": target}
                                   for actor, (face, target) in zip(actors, ordered))
                    if result not in results:
                        results.append(result)
                    break
    return tuple(results)
