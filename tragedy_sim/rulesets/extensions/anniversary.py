"""Tenth-anniversary composition over an existing complete ruleset.

The operation map is fixed at construction. It is inspectable and deepcopy-safe;
simulators use exactly the same phase entry points as human players.
"""

from dataclasses import replace

from ...cards import ACTORS, PROTAGONISTS
from ...catalog import REFUSAL
from ...effects.vocabulary import op, option
from ...model import TimingId


PLOT = "anniversary_beyond_worldline"
INCIDENTS = ("hope_light", "despair_dark")


def matches_guess(module, actual, guessed):
    return guessed == actual or (module in ("BTX+", "MZ+")
                                 and actual == "fragment" and guessed == "ordinary")


def incident_effects(game, kind):
    counter = "hope" if kind == "hope_light" else "despair"
    title = "希望之光" if counter == "hope" else "绝望之暗"
    actor = game.state.leader if counter == "hope" else "m"
    return [op("choice", actor=actor, prompt=f"{title}：选择目标角色",
               options=[option(f"{character.name}：{title[:2]} +1", [
                   op("counter", target=character.id, counter=counter, amount=1)])
                        for character in game._living()])]


def _count(game, character, counter):
    value = getattr(character, counter)
    if counter == "goodwill":
        return value + character.hope
    if counter == "paranoia":
        return value + character.despair
    if counter == "intrigue":
        return max(0, value + character.despair - character.hope)
    return value


def _clear_special_hands(game):
    for actor in ACTORS:
        special = "ahr_d1" if actor == "m" else "ahr_h1"
        game.state.hands[actor] = [cid for cid in game.state.hands[actor] if cid != special]


def _grant_loop_cards(game):
    loop = game.state.loop
    beyond = PLOT in game.scenario["subplots"]
    despair = game._anniversary_previous_dead or (beyond and loop % 2 == 0)
    hope = game._anniversary_previous_friendly or (beyond and loop == game.scenario["loops"])
    # Do not disclose which role / plot caused this observable grant.
    if despair:
        game.state.hands["m"].append("ahr_d1")
        game._event("special_card_gained", "剧作家获得「绝望 +1」（本轮限用一次）。",
                    timing=TimingId.LOOP_START, actor="m", card="ahr_d1")
    if hope:
        for actor in PROTAGONISTS:
            game.state.hands[actor].append("ahr_h1")
        game._event("special_card_gained", "三位主人公各获得一张「希望 +1」（本轮限用一次）。",
                    timing=TimingId.LOOP_START, actors=list(PROTAGONISTS), card="ahr_h1")


def compose(base, identifier, validator):
    """Compose named operations; base implementations remain independently usable."""
    def initialize(game):
        _clear_special_hands(game)
        game._anniversary_previous_dead = False
        game._anniversary_previous_friendly = False
        base.initialize(game)
        _grant_loop_cards(game)

    def restore_board(game, *, apply_loop_rules=False):
        base.operations["_restore_board"](game, apply_loop_rules=apply_loop_rules)
        _clear_special_hands(game)

    def resolve_loop_end(game, forced=False):
        fragments = [c for c in game.state.characters.values()
                     if c.present and game.roles[c.id] == "fragment"]
        game._anniversary_previous_dead = any(not c.alive for c in fragments)
        game._anniversary_previous_friendly = any(
            c.alive and game._count(c, "goodwill") >= 2 for c in fragments)
        return base.operations["_resolve_loop_end"](game, forced)

    def new_loop(game):
        base.operations["_new_loop"](game)
        _grant_loop_cards(game)

    def options(game, actor):
        result = base.operations["options"](game, actor)
        if game.state.phase != "refusal" or actor != game.controller:
            return result
        request = game._request
        if request.get("already_used"):
            return result
        source = game.state.characters[request["source"]]
        refusal = REFUSAL.get(game.roles[source.id])
        if source.hope and refusal == "optional":
            refusal = None
        if source.despair:
            refusal = "mandatory"
        if request["unrefusable"]:
            refusal = None
        result = []
        if refusal != "mandatory":
            result.append(option("执行已声明的友好能力", request["effects"], accept=True))
        if refusal:
            detail = "本轮一次能力被拒绝不计入次数" if request.get("once") else "仍计入本日次数"
            result.append(option(f"拒绝；公开宣布能力没有效果（{detail}）", refuse=True))
        return result

    def view(game, viewer="spectator", language="zh"):
        result = base.operations["view"](game, viewer, language)
        for cid, character in result["characters"].items():
            character["effective_counters"] = {
                counter: game._count(game.state.characters[cid], counter)
                for counter in ("goodwill", "paranoia", "intrigue")}
        return result

    operations = dict(base.operations)
    operations.update(_count=_count, _restore_board=restore_board,
                      _resolve_loop_end=resolve_loop_end, _new_loop=new_loop,
                      options=options, view=view)
    if "_mz_incident_effects" in operations:
        def mz_effects(game, kind, culprit_id):
            if kind in INCIDENTS:
                return incident_effects(game, kind)
            return base.operations["_mz_incident_effects"](game, kind, culprit_id)
        operations["_mz_incident_effects"] = mz_effects
    return replace(base, id=identifier, operations=operations,
                   initialize=initialize, validator=validator)
