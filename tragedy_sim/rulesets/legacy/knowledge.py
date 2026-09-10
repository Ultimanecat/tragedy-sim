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

def _script_roles(self):
    roles = set()
    for plot in (self.scenario["main_plot"], *self.scenario["subplots"]):
        roles.update(PLOTS[plot][2])
    return roles


def _publish_role(self, target, role):
    # Knowledge changes are an observable incident result even when no board
    # counter or character state changes (notably identity-reveal incidents).
    if self._incident_before is not None:
        self._incident_effect = True
    self.known_roles[target] = {"role": role, "loop": self.state.loop, "day": self.state.round}
    if self.module == "LL" and role == "secret_key":
        c = self.state.characters[target]
        if c.hope >= 1 or c.despair >= 2:
            self._ll_restricted_day = self.state.round + 1
    self.role_announcements.append({"character": target, "role": role, "loop": self.state.loop,
                                    "day": self.state.round,
                                    "may_be_ninja_claim": (self.module == "MZ" and role != "ninja"
                                                           and self.state.phase != "final_guess")})
    if self.module == "MZ":
        self._announced_roles.add(role)
    self._event("role_revealed", f"公开信息：{self.name(target)}的身份为{ROLE_NAMES[role]}。",
                character=target, role=role)


def _reveal_role(self, target, *, truthful=False):
    if self.module == "MZ" and self.roles[target] == "ninja" and not truthful:
        choices = [option(f"公开宣称：{ROLE_NAMES[role]}",
                          [op("announce_role", target=target, role=role)])
                   for role in ROLE_NAMES if role != "ordinary" and role in self._script_roles()]
        self._queue.insert(0, op("choice", prompt=f"{self.name(target)}是忍者：选择公开宣称的身份",
                                 options=choices))
        return
    self._publish_role(target, self.roles[target])


OPERATIONS = {
    '_script_roles': _script_roles,
    '_publish_role': _publish_role,
    '_reveal_role': _reveal_role,
}
