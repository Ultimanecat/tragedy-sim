"""Rules shared by special character cards across tragedy sets."""

from ..cards import COUNTER_NAMES
from ..effects.vocabulary import op, option


def _apply_character_setup(self):
    options = self.scenario.get("character_options", {})
    if "godly" in self.state.characters:
        entry = options["godly"]["entry_loop"]
        self.state.characters["godly"].present = self.state.loop >= entry
    if "transfer_student" in self.state.characters:
        self.state.characters["transfer_student"].present = False


def _character_loop_effects(self):
    effects = []
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
    if "transfer_student" not in self.state.characters:
        return
    character = self.state.characters["transfer_student"]
    entry = self.scenario["character_options"]["transfer_student"]["entry_day"]
    if not character.present and self.state.round == entry:
        character.present = True
        character.location = "school"
        self._event("character_arrived", "转校生在今日开始时登场并放置到学校。",
                    character="transfer_student", location="school")


def _ability_locations(self, cid):
    character = self.state.characters[cid]
    result = [character.location]
    if cid == "boss":
        territory = self.scenario["character_options"]["boss"]["territory"]
        if territory not in result:
            result.append(territory)
    return tuple(result)


def _incident_score(self, character, counter="paranoia"):
    if character.id == "ai" and counter == "paranoia":
        return (sum(getattr(character, name) for name in COUNTER_NAMES)
                + self.guards.get(character.id, 0))
    return self._count(character, counter)


def _queue_incident_resolution(self, effects, normal_end=None):
    if self._simulated_incident is not None:
        self._queue = list(effects) + [op("simulated_incident_done")]
    else:
        self._queue = list(effects) + list(normal_end or
                                           (op("incident_done"), op("night")))
        self._return_phase = "day_end"
    self._drain()


OPERATIONS = {
    "_apply_character_setup": _apply_character_setup,
    "_character_loop_effects": _character_loop_effects,
    "_prepare_day_start": _prepare_day_start,
    "_ability_locations": _ability_locations,
    "_incident_score": _incident_score,
    "_queue_incident_resolution": _queue_incident_resolution,
}
