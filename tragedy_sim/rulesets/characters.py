"""Rules shared by special character cards across tragedy sets."""

from ..cards import COUNTER_NAMES
from ..catalog import CHARACTERS
from ..engine import Character
from ..effects.vocabulary import op, option


def _apply_character_setup(self):
    options = self.scenario.get("character_options", {})
    for card in self.scenario.get("special_rules", {}).get(
            "disabled_mastermind_cards", []):
        while card in self.state.hands["m"]:
            self.state.hands["m"].remove(card)
    if "godly" in self.state.characters:
        entry = options["godly"]["entry_loop"]
        self.state.characters["godly"].present = self.state.loop >= entry
    if "transfer_student" in self.state.characters:
        self.state.characters["transfer_student"].present = False
    if "part_timer_question" in self.state.characters:
        self.state.characters["part_timer_question"].present = False
    if "servant" in self.state.characters:
        location = options.get("servant", {}).get("initial_location", "city")
        self.state.characters["servant"].location = location
        self._initial["servant"].location = location
    if "henchman" in options:
        location = options["henchman"]["initial_location"]
        self.state.characters["henchman"].location = location
        self._initial["henchman"].location = location


def _character_loop_effects(self):
    effects = []
    self._servant_targets.clear()
    options = self.scenario.get("character_options", {})
    if ("godly" in self.state.characters
            and self.state.characters["godly"].present
            and options["godly"]["entry_loop"] == self.state.loop):
        effects.append(op("character_arrived", target="godly"))
    if "black_cat" in self.state.characters and self.state.characters["black_cat"].present:
        effects.append(op("counter", target="shrine", counter="intrigue", amount=1))
    if "scholar" in self.state.characters and self.state.characters["scholar"].present:
        effects.append(op("choice", prompt="轮回开始：剧作家选择学者获得的指示物",
                          options=[option(f"学者获得{COUNTER_NAMES[counter]} +1",
                                          [op("counter", target="scholar",
                                              counter=counter, amount=1)])
                                   for counter in ("goodwill", "paranoia", "intrigue")]))
    return effects


def _prepare_day_start(self):
    if "transfer_student" in self.state.characters:
        character = self.state.characters["transfer_student"]
        entry = self.scenario["character_options"]["transfer_student"]["entry_day"]
        if not character.present and self.state.round == entry:
            character.present = True
            character.location = "school"
            self._event("character_arrived", "转校生在今日开始时登场并放置到学校。",
                        character="transfer_student", location="school")
    if ("part_timer" in self.state.characters
            and not self.state.characters["part_timer"].alive):
        if "part_timer_question" not in self.state.characters:
            definition = CHARACTERS["part_timer_question"]
            self.state.characters["part_timer_question"] = Character(
                "part_timer_question", definition.name, definition.start,
                definition.forbidden,
                action_targetable=definition.action_targetable,
                echo_board_actions=definition.echo_board_actions)
        replacement = self.state.characters["part_timer_question"]
        if not replacement.present:
            self.roles.setdefault("part_timer_question",
                                  self.scenario["cast"]["part_timer"])
            self.ex_cards.setdefault("part_timer_question", 0)
            self.guards.setdefault("part_timer_question", 0)
            replacement.present = True
            replacement.alive = True
            replacement.location = "city"
            self._event("character_replaced", "临时工已经死亡：今日开始时将“临时工？”放置到都市。",
                        character="part_timer_question", replaced="part_timer", location="city")


def _ability_locations(self, cid):
    character = self.state.characters[cid]
    result = [character.location]
    if cid == "boss":
        territory = self.scenario["character_options"]["boss"]["territory"]
        if self.scenario.get("special_rules", {}).get(
                "all_locations_count_as") == territory:
            return tuple(self.state.locations)
        if territory not in result:
            result.append(territory)
    return tuple(result)


def _incident_score(self, character, counter="paranoia"):
    if character.id == "ai" and counter == "paranoia":
        return (sum(getattr(character, name) for name in COUNTER_NAMES)
                + self.guards.get(character.id, 0))
    return self._count(character, counter)


def _queue_incident_resolution(self, effects, normal_end=None, *, culprit=None,
                               repeat=True):
    if culprit == "guru" and repeat:
        effects = list(effects) + list(effects)
        self._event("incident_effect_doubled", "教祖担任当事人：本次事件效果结算两次。",
                    character="guru")
    if self._simulated_incident is not None:
        self._queue = list(effects) + [op("simulated_incident_done")]
    else:
        self._queue = list(effects) + list(normal_end or
                                           (op("incident_done"), op("night")))
        self._return_phase = "day_end"
    self._drain()


def _after_character_movements(self, before_locations):
    """Return mandatory Servant-follow effects after simultaneous card movement."""
    if "servant" not in self.state.characters:
        return []
    servant = self.state.characters["servant"]
    if not servant.present or not servant.alive:
        return []
    protected = {cid for cid in ("rich", "boss") if cid in self.state.characters}
    protected.update(self._servant_targets)
    destinations = []
    for cid in protected:
        target = self.state.characters[cid]
        if (target.present and target.alive
                and before_locations.get(cid) == before_locations.get("servant")
                and target.location != before_locations.get(cid)
                and target.location not in destinations):
            destinations.append(target.location)
    if not destinations:
        return []
    choices = [option(f"侍从随行至{self.name(location)}",
                      [op("move", target="servant", location=location, forced=True)])
               for location in destinations]
    if len(choices) == 1:
        return choices[0]["effects"]
    return [op("choice", actor=self.state.leader,
               prompt="多个侍从对象同时移动：领队选择侍从随行的目的地", options=choices)]


OPERATIONS = {
    "_apply_character_setup": _apply_character_setup,
    "_character_loop_effects": _character_loop_effects,
    "_prepare_day_start": _prepare_day_start,
    "_ability_locations": _ability_locations,
    "_incident_score": _incident_score,
    "_queue_incident_resolution": _queue_incident_resolution,
    "_after_character_movements": _after_character_movements,
}
