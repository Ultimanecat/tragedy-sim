"""Compatibility effect handlers extracted from Game; rule semantics are unchanged."""

from ..cards import LOCATIONS
from .vocabulary import op, option


def hsa_add_curse(game, effect):
    target = effect["target"]
    if target in LOCATIONS:
        game.board_ex[target] += 1
        count = game.board_ex[target]
    else:
        game.ex_cards[target] += 1
        count = game.ex_cards[target]
    game._incident_effect = True
    game._event("curse_added", f"{game.name(target)}获得一张诅咒牌（现有 {count} 张）。",
                target=target, count=count)


def hsa_attach_curse(game, effect):
    board, target = effect["board"], effect["target"]
    game.board_ex[board] -= 1
    game.ex_cards[target] += 1
    game._event("curse_attached", f"{LOCATIONS[board]}的一张诅咒牌附身于{game.name(target)}。",
                board=board, target=target)


def hsa_resolve_curse(game, effect):
    target = effect["target"]
    board = game.state.characters[target].location
    game.ex_cards[target] -= 1
    game._kill([target])
    game.board_ex[board] += 1
    game._event("curse_returned", f"{game.name(target)}身上的诅咒牌移至{LOCATIONS[board]}。",
                target=target, board=board)


def hsa_curse_batch(game, effect):
    remaining = list(effect["remaining"])
    if remaining:
        choices = []
        for index, source in enumerate(remaining):
            rest = remaining[:index] + remaining[index + 1:]
            if source in game.roles:
                choices.append(option(
                    f"结算{game.name(source)}身上的诅咒牌",
                    [op("hsa_resolve_curse", target=source),
                     op("hsa_curse_batch", remaining=rest)]))
                continue
            targets = [c.id for c in game._living()
                       if c.location == source and not game.ex_cards[c.id]]
            choices += [option(
                f"{LOCATIONS[source]}的诅咒附身于{game.name(target)}",
                [op("hsa_attach_curse", board=source, target=target),
                 op("hsa_curse_batch", remaining=rest)])
                for target in targets]
            if not targets:
                choices.append(option(
                    f"结算{LOCATIONS[source]}无目标的诅咒牌",
                    [op("hsa_curse_no_target", board=source),
                     op("hsa_curse_batch", remaining=rest)]))
        game._queue.insert(0, op("choice", prompt="选择下一张诅咒牌及其结算方式",
                                 options=choices))


def hsa_curse_no_target(game, effect):
    board = effect["board"]
    game._event("curse_no_target", f"{LOCATIONS[board]}的诅咒牌没有可附身的角色。",
                board=board)


def hsa_monster_used(game, effect):
    game._hsa_monster_uses += 1


def hsa_frenzied_night(game, effect):
    game._hsa_frenzied_night = True
    game._hsa_frenzied_night_lethal = (
        sum(game._hsa_corpses(board) for board in LOCATIONS) >= 6)
    game._incident_effect = True
    game._event("frenzied_night_active", "疯狂之夜已经发生；将在日末检查尸体总数。")


def hsa_apocalypse(game, effect):
    board = effect["board"]
    game._kill([c.id for c in game._living() if c.location == board])
    if game.state.phase not in ("loop_end", "final_guess", "game_over") \
            and game._hsa_corpses(board) >= 5:
        game._queue.insert(0, op("heroes_die"))


HANDLERS = {
    "hsa_add_curse": hsa_add_curse,
    "hsa_attach_curse": hsa_attach_curse,
    "hsa_resolve_curse": hsa_resolve_curse,
    "hsa_curse_batch": hsa_curse_batch,
    "hsa_curse_no_target": hsa_curse_no_target,
    "hsa_monster_used": hsa_monster_used,
    "hsa_frenzied_night": hsa_frenzied_night,
    "hsa_apocalypse": hsa_apocalypse,
}
