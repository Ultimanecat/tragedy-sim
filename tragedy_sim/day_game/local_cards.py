"""Immutable local card-effect programs; no world, resources or observations.

Compilation factors out repeated deck scans/sums only. Runtime rule policies,
counter-trigger order, printed faces, resource owners and event order survive.
"""

from dataclasses import dataclass
from functools import lru_cache

from ..cards import Card, COORDS, COUNTER_NAMES, LOCATIONS, MOVES
from ..engine import RuleError


VERSION = "fs-local-card-program-v1"
_EFFECTS = frozenset(COUNTER_NAMES) | frozenset(MOVES) | {
    "forbid_movement", "forbid_paranoia", "forbid_goodwill", "forbid_intrigue"}
_DESTINATIONS = {coords: location for location, coords in COORDS.items()}


@dataclass(frozen=True)
class CounterProgram:
    counter: str
    positive: int
    negative: int
    forbidden: bool


@dataclass(frozen=True)
class LocalCardProgram:
    effects: frozenset[str]
    movement: tuple[int, int] | None
    counters: tuple[CounterProgram, ...]
    board_bluffs: tuple[str, ...]
    intrigue_forbids: int


def compile_local(cards):
    """Ordered, physical printed faces in; static local math out, or None."""
    # Validate before entering lru_cache: unknown metadata may be unhashable.
    if type(cards) is not tuple or any(
            type(card) is not Card or type(card.effect) is not str or card.effect not in _EFFECTS
            or type(card.amount) is not int or type(card.id) is not str or type(card.name) is not str
            or type(card.once_per_loop) is not bool for card in cards):
        return None
    return _compile_local(cards)


@lru_cache(maxsize=4096)
def _compile_local(cards):
    effects = frozenset(card.effect for card in cards)
    directions = effects & MOVES.keys()
    movement = None
    if directions:
        x = y = 0
        for direction in directions:
            dx, dy = MOVES[direction]
            x, y = x ^ dx, y ^ dy
        movement = (x, y)
    counters = []
    for counter in COUNTER_NAMES:
        changes = [card.amount for card in cards if card.effect == counter]
        if changes:
            counters.append(CounterProgram(counter, sum(v for v in changes if v > 0),
                                           sum(v for v in changes if v < 0), f"forbid_{counter}" in effects))
    return LocalCardProgram(effects, movement, tuple(counters),
                            tuple(card.name for card in cards if card.effect not in {"intrigue", "forbid_intrigue"}),
                            sum(card.effect == "forbid_intrigue" for card in cards))


def target_programs(game):
    """Group active original/echo cards in the exact engine traversal order."""
    groups = {}
    for placement in game._active_placements():
        groups.setdefault(placement.target, []).append(game._deck(placement.actor)[placement.card])
    result = []
    for target, cards in groups.items():
        program = compile_local(tuple(cards))
        if program is None:
            return None
        result.append((target, program))
    return tuple(result)


def resolve_movements(game, programs):
    state = game.state
    if state.phase != "action_counters" or not state.face_up:
        raise RuleError("必须先揭示行动牌，才能结算移动")
    for target, program in programs:
        if target not in state.characters or program.movement is None:
            continue
        char = state.characters[target]
        if game._movement_is_forbidden(target, set(program.effects)):
            game._event("movement_blocked", f"{char.name}：移动被禁止。")
            continue
        x, y = COORDS[char.location]
        dx, dy = program.movement
        destination = _DESTINATIONS[(x ^ dx, y ^ dy)]
        if destination in char.forbidden or not game._movement_destination_allowed(target, destination):
            game._event("movement_blocked", f"{char.name}：最终目的地当前不可进入，留在原地。")
        else:
            char.location = destination
            game._event("character_moved", f"{char.name} 移动到{LOCATIONS[destination]}。",
                        character=target, location=destination)


def resolve_counters(game, programs):
    state = game.state
    if state.phase != "action_counters":
        raise RuleError("尚未揭示并结算移动")
    forbids = sum(program.intrigue_forbids for _, program in programs)
    if game._intrigue_forbids_cancel(forbids):
        game._event("forbids_cancelled", "本次打出了多张禁止密谋牌，所有禁止密谋牌失效。")
    for target, program in programs:
        if target in LOCATIONS:
            for name in program.board_bluffs:
                game._event("location_bluff", f"{LOCATIONS[target]}上的「{name}」没有效果（地点佯攻牌）。")
        for instruction in program.counters:
            counter = instruction.counter
            if target not in state.characters and counter != "intrigue":
                continue
            blocked = instruction.forbidden
            if counter == "intrigue":
                blocked = blocked and not game._intrigue_forbids_cancel(forbids)
            blocked = blocked and not game._ignore_forbid(counter, target)
            if blocked:
                game._event("counter_blocked", f"{game.name(target)}：{COUNTER_NAMES[counter]}变更被禁止。")
                continue
            before = getattr(state.characters[target], counter) if target in state.characters else state.locations[target]
            after, steps = before, [before]
            for delta in (instruction.positive, instruction.negative):
                if not delta:
                    continue
                after = max(0, after + delta)
                if target in state.characters:
                    setattr(state.characters[target], counter, after)
                else:
                    state.locations[target] = after
                game._counter_mutated(target, counter)
                steps.append(after)
            if len(steps) == 1:
                steps.append(after)
            progression = " → ".join(str(value) for value in steps)
            game._event("counter_changed", f"{game.name(target)}：{COUNTER_NAMES[counter]} {progression}。",
                        target=target, counter=counter, before=before, after=after, steps=steps)
    for placement in state.pending:
        if game._deck(placement.actor)[placement.card].once_per_loop:
            state.discarded[placement.actor].append(placement.card)
        else:
            state.hands[placement.actor].append(placement.card)
    state.pending.clear()
    game._board_echo_placements.clear()
    game._ignored_placement_indexes.clear()
    state.face_up = False
    state.phase = "resolved"
    game._event("actions_resolved", "行动结算完成；普通牌收回，限次牌公开留置。此处暂停。")
