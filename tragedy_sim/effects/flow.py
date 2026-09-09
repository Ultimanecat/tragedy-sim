"""Compatibility effect handlers extracted from Game; rule semantics are unchanged."""

from .vocabulary import op, option


def mandatory_poison_mark(game, effect):
    game._mandatory_victims.append(effect["target"])


def mandatory_choice_batch(game, effect):
    groups = effect["choices"]
    choices = []
    for group_index, group in enumerate(groups):
        remaining = groups[:group_index] + groups[group_index + 1:]
        for item in group["options"]:
            choices.append(option(item["label"],
                                  list(item["effects"])
                                  + [op("mandatory_choice_batch", choices=remaining)]))
    if choices:
        game._queue.insert(0, op("choice", prompt="选择已触发强制能力的结算顺序及目标",
                                 options=choices))


def resolve_mandatory_deaths(game, effect):
    victims, game._mandatory_victims = game._mandatory_victims, []
    game._kill(victims)


def next_day_end_mandatory(game, effect):
    game._queue_day_end_mandatory_batch()


def incident_done(game, effect):
    game._record_incident_end()


def night(game, effect):
    game._begin_night()


HANDLERS = {
    "mandatory_poison_mark": mandatory_poison_mark,
    "mandatory_choice_batch": mandatory_choice_batch,
    "resolve_mandatory_deaths": resolve_mandatory_deaths,
    "next_day_end_mandatory": next_day_end_mandatory,
    "incident_done": incident_done,
    "night": night,
}
