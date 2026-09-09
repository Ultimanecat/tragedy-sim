"""Compatibility effect handlers extracted from Game; rule semantics are unchanged."""

from ..cards import ACTOR_NAMES, PROTAGONISTS
from .vocabulary import op, option


def ll_internet_celeb(game, effect):
    source = game.state.characters[effect["source"]]
    key = f"internet_celeb:{source.id}"
    if game._available_key(key, True):
        game._mark(key, True)
        choices = [option(f"{c.name}不安、友好各 +1",
                          [op("counter", target=c.id, counter="paranoia", amount=1),
                           op("counter", target=c.id, counter="goodwill", amount=1)])
                   for c in game._living()
                   if c.id != source.id and c.location == source.location]
        if choices:
            game._queue.insert(0, op("choice", prompt="网络红人：选择同区域另一名角色",
                                     options=choices))


def ll_will(game, effect):
    game._ll_will_pending = True
    game._event("hope_card_scheduled", "遗言已发生：下一轮开始主人公获得一张「希望 +1」。")


def ll_declare_traitor(game, effect):
    traitors = game._ll_traitor_seats()
    labels = "、".join(ACTOR_NAMES[seat] for seat in sorted(traitors))
    game._event("traitor_declared",
                "剧作家公开：" + (f"{labels}是背叛者。" if traitors else "本局没有背叛者。"),
                seats=sorted(traitors))
    sns_traitor = game._ll_seat_for_secret("B")
    if ("ll_sns_panic" in game.scenario["subplots"] and sns_traitor
            and sum(c.alive and c.location != game._loop_initial_locations[c.id]
                    for c in game.state.characters.values())
            > len(game._living()) / 2):
        game._win(f"traitor:{sns_traitor}", "主人公 B 达成 SNS 恐慌的特殊胜利条件。")
    elif "C" in game._ll_traitor_labels() and game.scenario["incidents"]:
        game._queue.insert(0, op("ll_culprit_guess", index=0, correct=True))
    else:
        game._queue.insert(0, op("ll_begin_role_guess"))


def ll_culprit_guess(game, effect):
    index = effect["index"]
    if index >= len(game.scenario["incidents"]):
        if effect["correct"]:
            game._win(f"traitor:{game._ll_seat_for_secret('C')}",
                      "主人公 C 正确猜中所有事件当事人，单独获胜。")
        else:
            game._queue.insert(0, op("ll_begin_role_guess"))
    else:
        incident = game.scenario["incidents"][index]
        options = [option(game.name(cid), [op("ll_culprit_guess", index=index + 1,
            correct=effect["correct"] and cid == incident["culprit"])]) for cid in game.roles]
        game._queue.insert(0, op("choice", actor=game._ll_seat_for_secret("C"),
                                 prompt=f"主人公 C：猜测第 {incident['day']} 天事件当事人",
                                 options=options))


def ll_begin_role_guess(game, effect):
    traitors = game._ll_traitor_seats()
    if game.state.leader in traitors:
        game.state.leader = next(actor for actor in PROTAGONISTS if actor not in traitors)
    game.state.phase = "final_guess"
    game._return_phase = "final_guess"


HANDLERS = {
    "ll_internet_celeb": ll_internet_celeb,
    "ll_will": ll_will,
    "ll_declare_traitor": ll_declare_traitor,
    "ll_culprit_guess": ll_culprit_guess,
    "ll_begin_role_guess": ll_begin_role_guess,
}
