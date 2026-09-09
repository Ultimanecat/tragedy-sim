"""Compatibility effect handlers extracted from Game; rule semantics are unchanged."""

from ..cards import COUNTER_NAMES, LOCATIONS
from .vocabulary import op, option


def ahr_world_shift(game, effect):
    game._ahr_world_shift(effect["reason"])


def ahr_puppet_check(game, effect):
    c = game.state.characters[effect["target"]]
    if sum(getattr(c, counter) > 0 for counter in COUNTER_NAMES) >= 2:
        game._ahr_world_shift("提线木偶友好能力结算后具有两种以上指示物")


def ahr_alice(game, effect):
    source = game.state.characters[effect["source"]]
    if game.ex_gauge >= 1 and game._available_key(f"alice:{source.id}", True):
        game._mark(f"alice:{source.id}", True)
        choices = [option(f"{c.name}希望 +1",
                          [op("counter", target=c.id, counter="hope", amount=1)])
                   for c in game._living()
                   if c.id != source.id and c.location == source.location]
        if choices:
            game._queue.insert(0, op("choice", prompt="爱丽丝：选择同区域另一名角色希望 +1",
                                     options=choices))


def ahr_corpse_intrigue_check(game, effect):
    if sum(game._count(c, "intrigue") for c in game.state.characters.values()
           if not c.alive) >= 3:
        game._queue.insert(0, op("heroes_die"))


def ahr_dimension_break(game, effect):
    c = game.state.characters[effect["target"]]
    if sum(getattr(c, counter) > 0 for counter in COUNTER_NAMES) >= 3:
        game._queue.insert(0, op("heroes_die"))


def ahr_will(game, effect):
    game._ahr_will_pending = True
    game._event("hope_card_scheduled", "遗言已发生：下一轮开始主人公获得一张「希望 +1」。")


def ahr_singularity_first(game, effect):
    game._ahr_singularity_occurred = True


def ahr_singularity_hidden(game, effect):
    cid = effect["target"]
    if game.state.locations[game._loop_initial_locations[cid]] >= 1:
        game._queue.insert(0, op("heroes_die"))


HANDLERS = {
    "ahr_world_shift": ahr_world_shift,
    "ahr_puppet_check": ahr_puppet_check,
    "ahr_alice": ahr_alice,
    "ahr_corpse_intrigue_check": ahr_corpse_intrigue_check,
    "ahr_dimension_break": ahr_dimension_break,
    "ahr_will": ahr_will,
    "ahr_singularity_first": ahr_singularity_first,
    "ahr_singularity_hidden": ahr_singularity_hidden,
}
