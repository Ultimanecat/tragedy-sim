"""Compatibility effect handlers extracted from Game; rule semantics are unchanged."""

from ..cards import LOCATIONS
from .vocabulary import op, option


def suspicious_move(game, effect):
    c = game.state.characters[effect["target"]]
    destination = effect["location"]
    moved = (destination != c.location and destination not in c.forbidden
             and game._movement_destination_allowed(c.id, destination)
             and game._movement_locks.get(c.id) != game.state.round)
    if moved:
        c.location = destination
        game._event("character_moved", f"{c.name}移动到{LOCATIONS[destination]}。",
                    target=c.id, location=destination)
        game._movement_locks[c.id] = game.state.round + 1
        game._event("movement_restricted", f"{c.name}在第 {game.state.round + 1} 天不能移动。",
                    target=c.id, day=game.state.round + 1)
    elif destination != c.location:
        game._event("movement_blocked", f"{c.name}未能移动到{LOCATIONS[destination]}。")


def seal_board(game, effect):
    board = effect["board"]
    through = game.state.round + 2
    game._sealed_boards.append((board, through))
    game._incident_effect = True
    game._event("board_sealed", f"{LOCATIONS[board]}从今天起至第 {through} 天封锁；角色不能通过移动进入或离开。",
                board=board, through=through)


def mc_psychiatrist_batch(game, effect):
    remaining = list(effect["sources"])
    choices = []
    for source in remaining:
        c = game.state.characters[source]
        targets = [target.id for target in game._living()
                   if target.id != source and target.location == c.location]
        rest = [cid for cid in remaining if cid != source]
        choices += [option(f"{c.name}（心理医生·强制）：移除{game.name(target)}的 1 不安",
                           [op("counter", target=target, counter="paranoia", amount=-1,
                               silent_noop=True),
                            op("mc_psychiatrist_batch", sources=rest)])
                    for target in targets]
    if choices:
        game._queue.insert(0, op("choice", prompt="选择心理医生强制能力的结算顺序及目标",
                                 options=choices))
    elif remaining:
        game._event("no_effect", "心理医生的强制能力已触发，但没有合法目标。")


def prevent_incident(game, effect):
    target = effect["target"]
    game._prevented_incident_culprits.add(target)
    game._event("incident_prevented", f"{game.name(target)}担任当事人的今日事件不会发生。",
                target=target)


def set_loop_initial_location(game, effect):
    target, location = effect["target"], effect["location"]
    game.state.characters[target].location = location
    game._loop_initial_locations[target] = location
    game._event("initial_location_chosen", f"{game.name(target)}本轮从{LOCATIONS[location]}开始。",
                target=target, location=location)


HANDLERS = {
    "suspicious_move": suspicious_move,
    "seal_board": seal_board,
    "mc_psychiatrist_batch": mc_psychiatrist_batch,
    "prevent_incident": prevent_incident,
    "set_loop_initial_location": set_loop_initial_location,
}
