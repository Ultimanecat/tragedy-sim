"""Compatibility effect handlers extracted from Game; rule semantics are unchanged."""

from .vocabulary import op, option


def add_ex(game, effect):
    target = effect["target"]
    game.ex_cards[target] += 1
    game._refresh_mz_ex_roles()
    game._event("ex_added", f"{game.name(target)}获得一张 Ex 牌（现有 {game.ex_cards[target]} 张）。",
                target=target, count=game.ex_cards[target])


def place_ex(game, effect):
    target = effect["target"]
    sources = [cid for cid, count in game.ex_cards.items() if count]
    if sources:
        choices = [option(f"使用未放置的 Ex 牌 → {game.name(target)}",
                          [op("add_ex", target=target)])]
        choices += [option(f"移动 Ex：{game.name(source)} → {game.name(target)}",
                           [op("move_ex", source=source, target=target)])
                    for source in sources]
        game._queue.insert(0, op("choice", prompt="选择使用新 Ex 牌或移动一张已有 Ex 牌",
                                 options=choices))
    else:
        game._queue.insert(0, op("add_ex", target=target))


def move_ex(game, effect):
    source, target = effect["source"], effect["target"]
    game.ex_cards[source] -= 1
    game.ex_cards[target] += 1
    game._refresh_mz_ex_roles()
    game._event("ex_moved", f"一张 Ex 牌从{game.name(source)}移至{game.name(target)}。",
                source=source, target=target)


def fake_incident_active(game, effect):
    game._fake_incident_active = True
    game._incident_effect = True
    game._event("action_restriction", "本轮余下时间，主人公不能在有 Ex 牌的角色上放置行动牌。")


def copy_mz_incident(game, effect):
    copied = game._mz_incident_effects(effect["incident"], effect["culprit"])
    game._queue = copied + game._queue


HANDLERS = {
    "add_ex": add_ex,
    "place_ex": place_ex,
    "move_ex": move_ex,
    "fake_incident_active": fake_incident_active,
    "copy_mz_incident": copy_mz_incident,
}
