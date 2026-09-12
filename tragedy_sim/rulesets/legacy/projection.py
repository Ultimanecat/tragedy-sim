"""Compatibility rules pending full ruleset migration."""

from copy import deepcopy
from dataclasses import asdict
import random
from ...cards import ACTORS, ACTOR_NAMES, COORDS, COUNTER_NAMES, LOCATIONS, PROTAGONISTS, STANDARD_COUNTERS, deck
from ...catalog import CHARACTERS, INCIDENT_NAMES, MODULES, MODULE_PLOTS, PLOTS, REFUSAL, ROLE_NAMES, TRAIT_NAMES
from ...engine import ActionGame, Character, RuleError, State
from ...effects.vocabulary import op, option
from ...flow import phase_label
from ...i18n import format_timepoint, label, normalize_language
from ...model import TimingId

def name(self, target):
    if target.endswith("@surface") or target.endswith("@hidden"):
        cid, side = target.rsplit("@", 1)
        return f"{self.state.characters[cid].name}（{'表' if side == 'surface' else '里'}身份）"
    return self.state.characters[target].name if target in self.state.characters else LOCATIONS.get(target, target)


def view(self, viewer="spectator", language="zh"):
    language = normalize_language(language)
    result = ActionGame.view(self, viewer, language)
    # `decision` is an internal pause. Showing it publicly can reveal that
    # several hidden abilities are simultaneously applicable. Other seats
    # continue to see the surrounding public rules phase instead.
    if viewer != "m" and result["phase"] == "decision" and self._decision_public_phase:
        result["phase"] = self._decision_public_phase
    timing = (TimingId(result["events"][-1]["timing"]) if result["phase"] == "game_over" and result["events"]
              else self._current_timing())
    result.update(language=language, phase_name=phase_label(result["phase"], language),
                  timing=timing.value,
                  timepoint=format_timepoint(timing.value, result["loop"], result["round"], language))
    spec = MODULES[self.module]
    for cid, char in result["characters"].items():
        definition = CHARACTERS[cid]
        char.update(name=label("characters", cid, language, fallback=definition.name),
                    paranoia_limit=definition.limit,
                    traits=[label("traits", t, language, fallback=TRAIT_NAMES[t]) for t in definition.traits],
                    guard=self.guards[cid], abilities=[asdict(a) for a in definition.abilities],
                    passive=definition.passive,
                    initial_location=self._loop_initial_locations.get(cid, definition.start),
                    ex_cards=self.ex_cards.get(cid, 0),
                    friended_token=(self.module == "LL" and cid in self._ll_friended_once),
                    death_token=(self.module == "LL" and cid in self._ll_dead_once))
    result.update(scenario_id=self.scenario["id"], title=self.scenario["title"], days=self.scenario["days"], loops=self.scenario["loops"],
                  table_talk=self.scenario["table_talk"], controller=self.controller, winner=self.winner,
                  module_name=label("modules", self.module, language, fallback=spec.name),
                  labels={"actors": {actor: label("actors", actor, language, fallback=ACTOR_NAMES[actor])
                                     for actor in ACTORS},
                          "locations": {location: label("locations", location, language, fallback=name)
                                        for location, name in LOCATIONS.items()},
                          "counters": {counter: label("counters", counter, language, fallback=name)
                                       for counter, name in COUNTER_NAMES.items()}},
                  capabilities={"final_guess": spec.final_guess,
                                "early_final_guess": spec.early_final_guess},
                  known_roles=deepcopy(self.known_roles), known_culprits=dict(self.known_culprits),
                  role_announcements=deepcopy(self.role_announcements),
                  known_plots=list(self.known_plots), protected=self.protected,
                  ex_gauge=self.ex_gauge,
                  world=("surface" if self.ex_gauge % 2 == 0 else "hidden")
                  if self.module == "AHR" else None,
                  board_ex=dict(self.board_ex),
                  movement_locks=dict(self._movement_locks),
                  sealed_boards=[{"board": board, "through": through}
                                 for board, through in self._sealed_boards
                                 if self.state.round <= through],
                  ability_day_used=sorted(self.public_day_used),
                  ability_loop_used=sorted(self.public_loop_used),
                  schedule=[{"day": i["day"], "kind": i.get("public_kind", i["kind"]),
                             **({"board": i["culprit"]}
                                if self.module == "HSA" and i["kind"] in {
                                    "frenzied_night", "curse_awakening", "filth_overflow",
                                    "dead_apocalypse"} else {})}
                            for i in self.scenario["incidents"]],
                  incidents=deepcopy(self.incident_records), guess_remaining=list(self._guess_remaining))
    if self.module == "LL" and viewer in PROTAGONISTS:
        result["protagonist_secret"] = self._ll_secrets[viewer]
    if viewer == "m":
        result["secret"] = {"roles": dict(self.roles), "initial_roles": dict(self.scenario["cast"]),
                            "main_plot": self.scenario["main_plot"], "subplots": list(self.scenario["subplots"]),
                            "incidents": deepcopy(self.scenario["incidents"]), "loss_reasons": list(self.loss_reasons),
                            "current_loop_days": self._current_loop_days(),
                            "ability_day_used": sorted(self.day_used), "ability_loop_used": sorted(self.loop_used)}
        if self.module == "AHR":
            result["secret"]["hidden_roles"] = dict(self.scenario["hidden_cast"])
    return result


OPERATIONS = {
    'name': name,
    'view': view,
}
