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

def _can_target_action(self, actor, target):
    if target not in self.state.characters:
        return True
    if actor == "m" and self._has(target, "prophet"):
        return False
    if actor != "m" and self._fake_incident_active and self.ex_cards.get(target, 0):
        return False
    if actor == "m" and target in self.roles and self._has(target, "werewolf"):
        return False
    return True


def play(self, actor, card_id, target):
    if target in self.state.characters and not self._can_target_action(actor, target):
        if actor == "m":
            raise RuleError("预言家在场时，剧作家不能向其放置行动牌")
        raise RuleError("伪造事件生效后，主人公本轮不能向有 Ex 牌的角色放置行动牌")
    ActionGame.play(self, actor, card_id, target)


def _apply_current_roles(self):
    if self.scenario["main_plot"] == "mz_causal":
        for cid, count in self.ex_cards.items():
            if count:
                self.roles[cid] = "key"


def _refresh_mz_ex_roles(self):
    if self.scenario["main_plot"] != "mz_causal":
        return
    for cid, initial in self.scenario["cast"].items():
        self.roles[cid] = "key" if self.ex_cards[cid] else initial


def _movement_is_forbidden(self, target, effects):
    return (ActionGame._movement_is_forbidden(self, target, effects)
            or ("mz_clear_mind" in self.scenario["subplots"] and "forbid_goodwill" in effects)
            or (self.module == "MC" and self._movement_locks.get(target) == self.state.round))


def _movement_destination_allowed(self, target, destination):
    origin = self.state.characters[target].location
    return not any(self.state.round <= through and origin != destination
                   and board in (origin, destination)
                   for board, through in self._sealed_boards)


def _intrigue_forbids_cancel(self, count):
    if self.module == "WM" and self.ex_gauge >= 3:
        return False
    return ActionGame._intrigue_forbids_cancel(self, count)


def _has(self, cid, role):
    if (not self.state.characters[cid].alive
            and not (self.module == "HSA" and role in ("ghost", "zombie"))):
        return False
    return (self.roles[cid] == role
            or (self.module == "AHR" and role == "ahr_puppet"
                and "ahr_puppet_lines" in self.scenario["subplots"]
                and self.roles[cid] in REFUSAL)
            or (self.module == "WM" and self.roles[cid] == "faceless"
                and ((role == "conspiracy" and self.ex_gauge >= 1)
                     or (role == "deep_one" and self.ex_gauge >= 2)))
            or (self.module == "WM" and self.roles[cid] == "paranoid"
                and "wm_deep_whisper" in self.scenario["subplots"] and role == "key")
            or (self.module == "LL" and self.roles[cid] == "clown"
                and self.state.round % 3 == 0 and role in ("conspiracy", "brain", "killer"))
            or (self.roles[cid] == "factor" and
            ((role == "key" and self.state.locations["city"] >= 2) or
             (role == "conspiracy" and self.state.locations["school"] >= 2))))


def _ahr_world_shift(self, reason):
    self._ahr_world_shift_pending = True
    self._incident_effect = True
    self._event("world_shift_triggered", f"已触发世界线变动（{reason}）；将在日末开始时令 Ex 槽 +1。")


def _ahr_refresh_roles(self):
    if self.module == "AHR":
        source = self.scenario["cast"] if self.ex_gauge % 2 == 0 else self.scenario["hidden_cast"]
        self.roles = dict(source)


def _ll_traitor_labels(self):
    if self.scenario["main_plot"] == "ll_final_plan" and any(
            self.roles[c.id] == "key" and c.hope >= 1
            for c in self.state.characters.values()):
        return set()
    plots = self.scenario["subplots"]
    result = set()
    if "ll_true_monster" in plots:
        result.add("A")
    if "ll_myth_collector" in plots or "ll_sns_panic" in plots:
        result.add("B")
    if "ll_detective" in plots:
        result.add("C")
    return result


def _ll_seat_for_secret(self, label):
    return next((seat for seat, secret in self._ll_secrets.items() if secret == label), None)


def _ll_traitor_seats(self):
    return {self._ll_seat_for_secret(label) for label in self._ll_traitor_labels()}


def _count(self, character, counter):
    """Return a counter's rules value after hope/despair modifiers."""
    value = getattr(character, counter)
    if self.module not in ("AHR", "LL"):
        return value
    if counter == "goodwill":
        return value + character.hope
    if counter == "paranoia":
        return value + character.despair
    if counter == "intrigue":
        return max(0, value + character.despair - character.hope)
    return value


def _hsa_corpses(self, board):
    return self.state.locations[board] + sum(
        not c.alive for c in self.state.characters.values() if c.location == board)


def _hsa_curse_total(self):
    return sum(self.ex_cards.values()) + sum(self.board_ex.values())


def _wm_plot_loss(self, plot):
    if plot == "wm_outer_chorus":
        return sum(c.intrigue >= 1 for c in self._living()) >= 5
    if plot == "wm_gospel":
        return self.state.locations["shrine"] >= self.ex_gauge
    if plot == "wm_yellow_king":
        return self.ex_gauge == self._wm_loop_start_ex
    if plot == "wm_bomb":
        return any(self.state.locations[self._loop_initial_locations[c.id]] >= 2
                   for c in self.state.characters.values() if self.roles[c.id] == "witch")
    if plot == "wm_blood_ritual":
        return sum(not c.alive for c in self.state.characters.values()) >= self.ex_gauge
    return False


def _counter_mutated(self, target, counter):
    if "virus" in self.scenario["subplots"]:
        for c in self._living():
            if self.roles[c.id] == "ordinary" and c.paranoia >= 3:
                self.roles[c.id] = "serial"  # Mandatory, permanent until the next loop; not announced.
    if self.module == "AHR" and "ahr_imaginary_virus" in self.scenario["subplots"]:
        for c in self._living():
            if self.roles[c.id] == "ordinary" and c.hope >= 2 and c.despair >= 2:
                self.roles[c.id] = "serial"


def _ignore_forbid(self, counter, target):
    location = self.state.characters[target].location if target in self.state.characters else target
    return ((counter == "intrigue" and location in self._ignore_intrigue) or
            (counter == "goodwill" and target in self.roles and self._has(target, "time_traveler")))


def _kill(self, targets):
    # Snapshot simultaneous deaths (e.g. Hospital or two Serial Killers); no order bias.
    killed = []
    key_death = False
    dying_magicians = []
    dying_wm_conspirators = []
    dying_preachers = []
    dying_celebrities = []
    dying_secret_keys = []
    for target in dict.fromkeys(targets):
        c = self.state.characters[target]
        if not c.alive:
            continue
        if (self._has(target, "time_traveler") or self._has(target, "immortal")
                or self._has(target, "detective") or self._has(target, "vampire")
                or self._has(target, "nightmare") or self._has(target, "paper_tiger")
                or self._has(target, "sacrifice") or self._has(target, "faceless")
                or self._has(target, "narrator") or self._has(target, "watcher")
                or self._has(target, "clown")):
            self._event("death_prevented", f"{c.name}没有死亡。", target=target)
        elif self.guards[target]:
            self.guards[target] -= 1
            self._event("guard_spent", f"{c.name}的一个护卫标记被移除，替代这次死亡。", target=target)
        else:
            key_death |= self._has(target, "key")
            if self._has(target, "magician"):
                dying_magicians.append(target)
            if self.module == "WM" and self._has(target, "conspiracy"):
                dying_wm_conspirators.append(target)
            if self.module == "AHR" and self._has(target, "preacher"):
                dying_preachers.append(target)
            if self.module == "LL" and self._has(target, "internet_celeb"):
                dying_celebrities.append(target)
            if self.module == "LL" and self._has(target, "secret_key"):
                dying_secret_keys.append(target)
            killed.append(target)
    for target in killed:
        self.state.characters[target].alive = False
        if self.module == "LL" and target not in self._ll_dead_once:
            self._ll_dead_once.add(target)
            self._event("death_token_placed", f"{self.name(target)}首次死亡，放置死亡完毕标志。",
                        target=target)
        if (self.scenario["main_plot"] == "hsa_ancient_dead"
                and self.roles[target] in ("ordinary", "paper_tiger")):
            self.roles[target] = "zombie"
        self._event("character_died", f"{self.name(target)}死亡；尸体留在原地，计数物保留。", target=target)
    for target in dying_magicians:
        goodwill = self.state.characters[target].goodwill
        if goodwill:
            self._change(target, "goodwill", -goodwill)
    for target in dying_wm_conspirators:
        self._publish_role(target, self.roles[target])
        self._change_ex_gauge(1)
    for target in dying_preachers:
        location = self.state.characters[target].location
        options = [option(f"{c.name}绝望 +1",
                          [op("counter", target=c.id, counter="despair", amount=1)])
                   for c in self._living() if c.location == location]
        self._ahr_world_shift("布道者死亡")
        if options:
            self._queue.insert(0, op("choice", prompt="布道者死亡：选择同区域一名角色绝望 +1",
                                     options=options))
    for target in dying_celebrities:
        initial = self._loop_initial_locations[target]
        for c in self._living():
            if c.id != target and self._loop_initial_locations[c.id] == initial:
                self._change(c.id, "paranoia", 1)
    for target in dying_secret_keys:
        self._publish_role(target, self.roles[target])
    for target in killed:
        partner = {"lover": "loved", "loved": "lover"}.get(self.roles[target])
        if partner:
            for c in self._living():
                if self.roles[c.id] == partner:
                    self._change(c.id, "paranoia", 6)
    if key_death:
        self.loss_reasons.append("关键人物（或持有该能力的因子）死亡")
        self._finish_loop(forced=True)


OPERATIONS = {
    '_can_target_action': _can_target_action,
    'play': play,
    '_apply_current_roles': _apply_current_roles,
    '_refresh_mz_ex_roles': _refresh_mz_ex_roles,
    '_movement_is_forbidden': _movement_is_forbidden,
    '_movement_destination_allowed': _movement_destination_allowed,
    '_intrigue_forbids_cancel': _intrigue_forbids_cancel,
    '_has': _has,
    '_ahr_world_shift': _ahr_world_shift,
    '_ahr_refresh_roles': _ahr_refresh_roles,
    '_ll_traitor_labels': _ll_traitor_labels,
    '_ll_seat_for_secret': _ll_seat_for_secret,
    '_ll_traitor_seats': _ll_traitor_seats,
    '_count': _count,
    '_hsa_corpses': _hsa_corpses,
    '_hsa_curse_total': _hsa_curse_total,
    '_wm_plot_loss': _wm_plot_loss,
    '_counter_mutated': _counter_mutated,
    '_ignore_forbid': _ignore_forbid,
    '_kill': _kill,
}
