"""Compatibility effect handlers extracted from Game; rule semantics are unchanged."""

from ..cards import ACTOR_NAMES


def missing_intrigue(game, effect):
    game._change(game.state.characters[effect["target"]].location, "intrigue", 1)


def ex_gauge(game, effect):
    game._change_ex_gauge(effect["amount"])


def clear_paranoia(game, effect):
    target = effect["target"]
    game._change(target, "paranoia", -game.state.characters[target].paranoia,
                 silent_noop=True)


def revive(game, effect):
    c = game.state.characters[effect["target"]]
    c.alive = True
    game._event("revived", f"{c.name}在原位置复活，保留计数物。", target=c.id)
    game._counter_mutated(c.id, "paranoia")


def guard(game, effect):
    game.guards[effect["target"]] += 1
    game._event("guard_added", f"{game.name(effect['target'])}获得一个护卫标记。")


def protect(game, effect):
    game.protected = True
    game._event("heroes_protected", "本轮主人公不会死亡（不阻止其他失败条件）。")


def recover(game, effect):
    actor, card = effect["actor"], effect["card"]
    game.state.discarded[actor].remove(card)
    game.state.hands[actor].append(card)
    game._event("card_recovered", f"{ACTOR_NAMES[actor]}收回{game._deck(actor)[card].name}。")


def transfer(game, effect):
    a, b, counter = effect["source"], effect["target"], effect["counter"]
    if counter == "guard":
        game.guards[a] -= 1
        game.guards[b] += 1
        game._event("guard_moved", f"一个护卫标记从{game.name(a)}移至{game.name(b)}。")
    else:
        game._change(a, counter, -1)
        game._change(b, counter, 1)


def ignore_intrigue(game, effect):
    game._ignore_intrigue.add(effect["location"])  # private; announce only the resulting counters


def ignore_card(game, effect):
    index = effect["index"]
    game._ignored_placement_indexes.add(index)
    placement = game.state.pending[index]
    game._event("card_ignored", f"{ACTOR_NAMES[placement.actor]}在{game.name(placement.target)}的"
                f"「{game._deck(placement.actor)[placement.card].name}」被无效化。",
                actor=placement.actor, card=placement.card, target=placement.target)


HANDLERS = {
    "missing_intrigue": missing_intrigue,
    "ex_gauge": ex_gauge,
    "clear_paranoia": clear_paranoia,
    "revive": revive,
    "guard": guard,
    "protect": protect,
    "recover": recover,
    "transfer": transfer,
    "ignore_intrigue": ignore_intrigue,
    "ignore_card": ignore_card,
}
