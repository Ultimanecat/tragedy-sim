"""Compatibility effect handlers extracted from Game; rule semantics are unchanged."""

from ..cards import LOCATIONS


def move(game, effect):
    c = game.state.characters[effect["target"]]
    destination = effect["location"]
    if (destination not in c.forbidden
            and game._movement_destination_allowed(c.id, destination)
            and game._movement_locks.get(c.id) != game.state.round):
        c.location = destination
        game._event("character_moved", f"{c.name}移动到{LOCATIONS[destination]}。", target=c.id, location=destination)
    else:
        game._event("movement_blocked", f"{c.name}未能移动到禁行区域。")


def move_corpse(game, effect):
    target, location = effect["target"], effect["location"]
    game.state.characters[target].location = location
    game._event("corpse_moved", f"{game.name(target)}的尸体移至{LOCATIONS[location]}。",
                target=target, location=location)


def release(game, effect):
    game.state.characters["patient"].forbidden = ()
    game._event("patient_released", "本轮住院患者的所有禁行区域被取消。")


HANDLERS = {
    "move": move,
    "move_corpse": move_corpse,
    "release": release,
}
