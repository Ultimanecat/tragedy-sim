"""Compatibility effect handlers extracted from Game; rule semantics are unchanged."""



def heroes_die(game, effect):
    if game.protected:
        game._event("heroes_protected", "主人公的死亡被本轮保护效果阻止。")
    else:
        if not effect.get("hidden"):
            game._event("heroes_died", "主人公死亡。")
        game._incident_effect = True
        game.loss_reasons.append("主人公死亡")
        game._finish_loop(forced=True)


def lose(game, effect):
    game.loss_reasons.append("时间旅行者日末能力")
    game._event("protagonists_lost", "主人公失败。")
    game._finish_loop(forced=True)


def finish_loop(game, effect):
    game.loss_reasons.append(effect.get("reason", "事件使轮回结束"))
    game._finish_loop(forced=True)


def loop_loss(game, effect):
    game.loss_reasons.append(effect["reason"])
    game._finish_loop(forced=True)


HANDLERS = {
    "heroes_die": heroes_die,
    "lose": lose,
    "finish_loop": finish_loop,
    "loop_loss": loop_loss,
}
