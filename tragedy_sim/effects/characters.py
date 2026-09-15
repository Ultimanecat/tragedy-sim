"""Effect handlers for generally available special character cards."""

from ..cards import COUNTER_NAMES
from ..catalog import INCIDENT_NAMES
from .vocabulary import op, option


def character_arrived(game, effect):
    target = effect["target"]
    character = game.state.characters[target]
    character.present = True
    game._event("character_arrived", f"{character.name}从本轮开始登场。",
                character=target, location=character.location)


def reset_character_counters(game, effect):
    target = effect["target"]
    character = game.state.characters[target]
    changed = False
    for counter in COUNTER_NAMES:
        amount = getattr(character, counter)
        if amount:
            game._change(target, counter, -amount)
            changed = True
    if game.guards.get(target, 0):
        before = game.guards[target]
        game.guards[target] = 0
        game._event("counter_changed", f"{character.name}：护卫 {before} → 0。",
                    target=target, counter="guard", before=before, after=0)
        changed = True
    if not changed:
        game._event("no_effect", f"{character.name}身上没有可移除的指示物。")
    if game.module in {"MC", "WM", "AHR"}:
        game._queue.insert(0, op(
            "choice", actor=game.state.leader, prompt="学者：领队选择调整 Ex 槽",
            options=[option("Ex 槽 +1", [op("ex_gauge", amount=1)]),
                     option("Ex 槽 -1", [op("ex_gauge", amount=-1)])]))


def vanish(game, effect):
    target = effect["target"]
    game.state.characters[target].present = False
    game._event("character_left", f"{game.name(target)}在本轮中从版图上移除。",
                character=target)


def convert_intrigue(game, effect):
    target = effect["target"]
    if game.state.characters[target].intrigue:
        game._change(target, "intrigue", -1)
        game._change(target, "goodwill", 1)
    else:
        game._event("no_effect", f"{game.name(target)}没有可替换的密谋指示物。")


def simulate_incident(game, effect):
    kind = effect["incident"]
    game._simulated_incident = {"day": game.state.round, "kind": kind, "culprit": "ai"}
    game._choice_actor_override = game.state.leader
    game._event("simulated_incident_started",
                f"A.I. 的友好能力开始结算「{INCIDENT_NAMES[kind]}」的事件效果；"
                "所有原由剧作家作出的决定改由领队作出。",
                incident=kind, source="ai")
    game._incident()


def simulated_incident_done(game, effect):
    kind = game._simulated_incident["kind"]
    game._simulated_incident = None
    game._choice_actor_override = None
    game._event("simulated_incident_ended",
                f"A.I. 对「{INCIDENT_NAMES[kind]}」的模拟结算完成；该事件不视为发生。",
                incident=kind, source="ai")


HANDLERS = {
    "character_arrived": character_arrived,
    "reset_character_counters": reset_character_counters,
    "vanish": vanish,
    "convert_intrigue": convert_intrigue,
    "simulate_incident": simulate_incident,
    "simulated_incident_done": simulated_incident_done,
}
