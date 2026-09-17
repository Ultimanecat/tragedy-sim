"""Human-readable descriptions of deterministic player commands."""

from __future__ import annotations

from typing import Any

from .cards import ACTOR_NAMES, deck
from .flow import PHASE_LABELS


def describe_decision(game: Any, actor: str, action: str, args: dict[str, Any]) -> str:
    """Describe a command before applying it, while choice labels are available."""
    who = ACTOR_NAMES[actor]
    if action == "play":
        definition = deck(actor, game.module).get(args["card"])
        card = definition.name if definition else args["card"]
        return f"{who}将「{card}」暗置于{game.name(args['target'])}"
    if action == "resolve":
        return f"{who}统一揭示行动牌并开始结算"
    if action == "next":
        return f"{who}结束“{PHASE_LABELS[game.state.phase]}”阶段"
    if action == "choose":
        index = args["index"]
        choices = game.options(actor)
        label = choices[index - 1]["label"] if type(index) is int and 1 <= index <= len(choices) else f"选项 {index}"
        return f"{who}选择：{label}"
    if action == "guess_all":
        return f"{who}一次提交全部角色的最终身份猜测"
    if action == "final":
        return f"{who}决定提前进入最终猜测"
    return f"{who}执行 {action}"
