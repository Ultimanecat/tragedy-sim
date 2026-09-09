"""Compatibility effect handlers extracted from Game; rule semantics are unchanged."""

from ..catalog import PLOTS
from .vocabulary import op, option


def reveal(game, effect):
    game._reveal_role(effect["target"])


def announce_role(game, effect):
    game._publish_role(effect["target"], effect["role"])


def culprit(game, effect):
    incident = next(i for i in game.scenario["incidents"] if i["day"] == effect["day"])
    game.known_culprits[str(effect["day"])] = incident["culprit"]
    game._event("culprit_revealed", f"公开信息：第 {effect['day']} 天事件的当事人为{game.name(incident['culprit'])}。")


def informer(game, effect):
    choices = [option(f"公开规则 X：{PLOTS[p][0]}", [op("plot_reveal", plot=p)])
               for p in game.scenario["subplots"] if p != effect["excluded"]]
    game._queue.insert(0, op("choice", prompt="选择公开的规则 X", options=choices))


def plot_reveal(game, effect):
    if effect["plot"] not in game.known_plots:
        game.known_plots.append(effect["plot"])
    game._event("plot_revealed", f"公开信息：本剧本包含规则 X「{PLOTS[effect['plot']][0]}」。")


HANDLERS = {
    "reveal": reveal,
    "announce_role": announce_role,
    "culprit": culprit,
    "informer": informer,
    "plot_reveal": plot_reveal,
}
