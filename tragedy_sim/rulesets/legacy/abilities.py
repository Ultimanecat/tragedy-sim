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
from ...domain import SourcedEffect, legacy_effect

def _available_key(self, key, once=False):
    return key not in self.day_used and (not once or key not in self.loop_used)


def _mark(self, key, once=False):
    self.day_used.add(key)
    if once:
        self.loop_used.add(key)


def _counter_options(self, source, key, targets, counter, amount, label, once=False):
    if not self._available_key(key, once):
        return []
    return [option(f"{label} → {self.name(t)} {COUNTER_NAMES[counter]} {amount:+}",
                   [op("counter", target=t, counter=counter, amount=amount)], key=key, once=once)
            for t in targets]


def _scoped_targets(self, source, scope):
    s = self.state.characters[source]
    living = self._living()
    same = [c for c in living if c.location == s.location]
    if scope == "self":
        return [source]
    if scope == "rich" and s.location not in ("school", "city"):
        return []
    if scope in ("corpse", "any_corpse"):
        return [c.id for c in self.state.characters.values() if not c.alive
                and (scope == "any_corpse" or c.location == s.location)]
    selected = living if scope == "any_other" else same
    if scope in ("other", "other_student", "any_other", "panicked_other"):
        selected = [c for c in selected if c.id != source]
    if scope in ("student", "other_student"):
        selected = [c for c in selected if "student" in CHARACTERS[c.id].traits]
    if scope == "panicked_other":
        selected = [c for c in selected if c.paranoia >= CHARACTERS[c.id].limit]
    targets = [c.id for c in selected]
    if scope == "same_or_location":
        targets.append(s.location)
    return targets


def _ability_options(self, source, ability, *, private=False):
    c = self.state.characters[source]
    key = f"goodwill:{source}:{ability.id}"
    used_day = self.day_used if private else self.public_day_used
    used_loop = self.loop_used if private else self.public_loop_used
    ability_counter = (self._count(c, "paranoia")
                       if self.module == "AHR" and self.ex_gauge % 2
                       else self._count(c, "goodwill"))
    if not c.alive or ability_counter < ability.threshold or key in used_day or (ability.once and key in used_loop):
        return []
    targets = self._scoped_targets(source, ability.scope)
    label = f"{c.name} · {ability.text}"
    results = []
    if ability.kind in ("counter", "adjust"):
        for amount in ((1, -1) if ability.kind == "adjust" else (ability.amount,)):
            results += [option(f"{label} → {self.name(t)} {COUNTER_NAMES[ability.counter]} {amount:+}",
                               [op("counter", target=t, counter=ability.counter, amount=amount)]) for t in targets]
    elif ability.kind in ("reveal", "kill", "revive", "guard"):
        results = [option(f"{label} → {self.name(t)}", [op(ability.kind, target=t)]) for t in targets]
    elif ability.kind == "purify" and c.location == "shrine":
        results = [option(label, [op("counter", target="shrine", counter="intrigue", amount=-1)])]
    elif ability.kind == "release" and "patient" in self.roles and self.state.characters["patient"].alive:
        results = [option(label, [op("release")])]
    elif ability.kind == "protect":
        results = [option(label, [op("protect")])]
    elif ability.kind == "prevent_incident":
        results = [option(label, [op("prevent_incident", target=source)])]
    elif ability.kind == "recover":
        results = [option(f"{label} → {self._deck(self.state.leader)[card].name}",
                          [op("recover", actor=self.state.leader, card=card)])
                   for card in self.state.discarded[self.state.leader]]
    elif ability.kind == "culprit":
        results = [option(f"{label} → 第 {r['day']} 天的{INCIDENT_NAMES[r['kind']]}",
                          [op("culprit", day=r["day"])]) for r in self.incident_records if r["happened"]]
    elif ability.kind == "plot":
        for plot in MODULE_PLOTS[self.module]:
            if PLOTS[plot][1] == "X":
                results.append(option(f"{label}；声明：{PLOTS[plot][0]}", [op("informer", excluded=plot)]))
    elif ability.kind == "transfer":
        others = self._scoped_targets(source, "other")
        for a in others:
            for b in others:
                if a == b:
                    continue
                counters = COUNTER_NAMES if self.module == "AHR" else STANDARD_COUNTERS
                for counter in (*counters, "guard"):
                    count = self.guards[a] if counter == "guard" else getattr(self.state.characters[a], counter)
                    if count:
                        results.append(option(f"{label}：{self.name(a)} → {self.name(b)}，"
                                              f"{COUNTER_NAMES.get(counter, '护卫')}",
                                              [op("transfer", source=a, target=b, counter=counter)]))
    for result in results:
        result.update(key=key, once=ability.once, source=source, ability=ability.id,
                      unrefusable=ability.unrefusable, goodwill=True)
    return results


def options(self, actor):
    """Private choices MUST only be returned to the controlling actor."""
    if actor != self.controller:
        return []
    phase = self.state.phase
    if self._pending:
        return deepcopy(self._pending["options"])
    if not self._timing_optional_ready():
        return []
    result = []
    if phase == "action_counters":
        for c in self._living():
            key = f"cultist:{c.id}"
            if self.roles[c.id] == "cultist" and self._available_key(key):
                result.append(option(f"{c.name}（邪教徒）：忽略{LOCATIONS[c.location]}及该区域角色的禁止密谋",
                                     [op("ignore_intrigue", location=c.location)], key=key))
    elif phase == "master_abilities":
        for c in self._living():
            if self._has(c.id, "brain"):
                targets = self._scoped_targets(c.id, "same_or_location")
                result += self._counter_options(c.id, f"brain:{c.id}", targets, "intrigue", 1, f"{c.name}（主谋）")
            if self._has(c.id, "conspiracy"):
                result += self._counter_options(c.id, f"conspiracy:{c.id}", self._scoped_targets(c.id, "same"),
                                                "paranoia", 1, f"{c.name}（传谣能力）")
            if self._has(c.id, "paranoid"):
                result += self._counter_options(c.id, f"paranoid:{c.id}", [c.id],
                                                "intrigue", 1, f"{c.name}（偏执狂）")
            if c.id == "doctor" and self.roles[c.id] in REFUSAL:
                # Same daily limit as the Doctor's protagonist ability.
                for choice in self._ability_options(c.id, CHARACTERS[c.id].abilities[0], private=True):
                    choice["goodwill"] = False
                    result.append(choice)
        if "rumor" in self.scenario["subplots"]:
            result += self._counter_options(None, "plot:rumor", list(LOCATIONS), "intrigue", 1,
                                            "流言四起（每轮一次）", True)
        if "mz_factor" in self.scenario["subplots"]:
            factor_locations = sorted({c.location for c in self._living() if self._has(c.id, "factor")})
            result += self._counter_options(None, "plot:mz_factor", factor_locations,
                                            "intrigue", 1, "X 异因子（每轮一次）", True)
        if ("hsa_monster_plot" in self.scenario["subplots"]
                and "plot:hsa_monster:day" not in self.day_used
                and self._hsa_monster_uses < 2):
            locations = sorted({c.location for c in self._living()
                                if self.roles[c.id] in REFUSAL})
            for location in locations:
                result.append(option(
                    f"怪物们的阴谋：在{LOCATIONS[location]}放置一具尸体",
                    [op("counter", target=location, counter="intrigue", amount=1),
                     op("hsa_monster_used")], key="plot:hsa_monster:day"))
        if "wm_rumor" in self.scenario["subplots"]:
            result += self._counter_options(None, "plot:wm_rumor", list(LOCATIONS),
                                            "intrigue", 1, "流言四起（每轮一次）", True)
        for c in self._living():
            if self._has(c.id, "deep_one"):
                result += self._counter_options(c.id, f"deep_one:{c.id}",
                                                self._scoped_targets(c.id, "same_or_location"),
                                                "intrigue", 1, f"{c.name}（深潜者）")
            if self.module == "AHR" and self._has(c.id, "preacher"):
                result += self._counter_options(c.id, f"preacher:{c.id}",
                                                self._scoped_targets(c.id, "same"),
                                                "goodwill", 1, f"{c.name}（布道者）")
            if self.module == "AHR" and self._has(c.id, "narrator") and self.ex_gauge >= 1:
                for source in self._scoped_targets(c.id, "same"):
                    for target in self._scoped_targets(c.id, "same"):
                        if source == target:
                            continue
                        for counter in COUNTER_NAMES:
                            if getattr(self.state.characters[source], counter):
                                result.append(option(
                                    f"{c.name}（叙述者）：{self.name(source)} → {self.name(target)}，"
                                    f"{COUNTER_NAMES[counter]}",
                                    [op("transfer", source=source, target=target, counter=counter)],
                                    key=f"narrator:{c.id}"))
            if self.module == "AHR" and self._has(c.id, "ahr_puppet"):
                for ability in CHARACTERS[c.id].abilities:
                    for item in self._ability_options(c.id, ability, private=True):
                        item["label"] = f"{c.name}（提线木偶代行）：" + item["label"]
                        item["goodwill"] = False
                        item["effects"] += ([op("ahr_world_shift", reason="剧作家使用每轮一次友好能力")]
                                            if item.get("once") else [])
                        item["effects"].append(op("ahr_puppet_check", target=c.id))
                        result.append(item)
        if (self.module == "AHR" and "ahr_unspeakable" in self.scenario["subplots"]
                and self._available_key("plot:ahr_unspeakable", True)):
            boards = sorted({self._loop_initial_locations[c.id] for c in self._living()
                             if self._has(c.id, "obsessive")})
            result += self._counter_options(None, "plot:ahr_unspeakable", boards, "intrigue", 1,
                                            "难以言喻的怪物（每轮一次）", True)
        if (self.module == "LL" and "ll_x_citizen" in self.scenario["subplots"]
                and self._available_key("plot:ll_x_citizen", True)):
            boards = sorted({self._loop_initial_locations[c.id] for c in self._living()
                             if self.roles[c.id] == "factor"})
            result += self._counter_options(None, "plot:ll_x_citizen", boards, "intrigue", 1,
                                            "X 民周至（每轮一次）", True)
        if self.module == "MZ" and self._available_key("role:magician", True):
            for magician in self._living():
                if not self._has(magician.id, "magician"):
                    continue
                for target in self._living():
                    if target.location != magician.location or target.goodwill < 1:
                        continue
                    x, y = COORDS[target.location]
                    for location, (dx, dy) in COORDS.items():
                        if abs(x - dx) + abs(y - dy) != 1 or location in target.forbidden:
                            continue
                        result.append(option(
                            f"{magician.name}（魔术师）：将{target.name}移至{LOCATIONS[location]}",
                            [op("move", target=target.id, location=location)],
                            key="role:magician", once=True))
    elif phase == "goodwill":
        for c in self._living():
            for ability in CHARACTERS[c.id].abilities:
                result += self._ability_options(c.id, ability)
    elif phase == "day_end":
        for c in self._living():
            if self._has(c.id, "killer"):
                key = f"killer:character:{c.id}"
                if self._available_key(key):
                    for t in self._living():
                        # Factor borrows a death ability, not the Key Person identity.
                        if ((self.module == "LL" or self.roles[t.id] == "key")
                                and t.id != c.id and t.location == c.location
                                and self._count(t, "intrigue") >= 2):
                            result.append(option(f"{c.name}（杀手）：使{t.name}死亡", [op("kill", target=t.id)], key=key))
                key = f"killer:heroes:{c.id}"
                if self._count(c, "intrigue") >= 4 and self._available_key(key):
                    result.append(option(f"{c.name}（杀手）：使主人公死亡", [op("heroes_die")], key=key))
            if self._has(c.id, "lover") and c.paranoia >= 3 and c.intrigue >= 1:
                key = f"lover:{c.id}"
                if self._available_key(key):
                    result.append(option(f"{c.name}（求爱者）：使主人公死亡",
                                         [op("heroes_die")], key=key))
            traveler_ready = (all(getattr(c, counter) <= 2 for counter in STANDARD_COUNTERS)
                              if self.module == "WM" else c.goodwill <= 2)
            if (self._has(c.id, "time_traveler") and self.state.round == self.scenario["days"]
                    and traveler_ready):
                key = f"time_traveler:{c.id}"
                if self._available_key(key):
                    result.append(option(f"{c.name}（时间旅行者）：使主人公失败", [op("lose")], key=key))
            if self._has(c.id, "ninja"):
                key = f"ninja:{c.id}"
                if self._available_key(key):
                    for target in self._living():
                        if target.location == c.location and target.intrigue >= 2:
                            result.append(option(f"{c.name}（忍者）：使{target.name}死亡",
                                                 [op("kill", target=target.id)], key=key))
            if self._has(c.id, "vampire"):
                key = f"vampire:key:{c.id}"
                if self._available_key(key):
                    for target in self._living():
                        if (target.location == c.location and self._has(target.id, "key")
                                and target.intrigue >= 2):
                            result.append(option(f"{c.name}（吸血鬼）：使{target.name}死亡",
                                                 [op("kill", target=target.id)], key=key))
                key = f"vampire:heroes:{c.id}"
                if (self._hsa_corpses(self._loop_initial_locations[c.id]) >= 2
                        and self._available_key(key)):
                    result.append(option(f"{c.name}（吸血鬼）：使主人公死亡",
                                         [op("heroes_die")], key=key))
            if self._has(c.id, "werewolf") and self._hsa_frenzied_night:
                key = f"werewolf:{c.id}"
                if self._available_key(key):
                    result.append(option(f"{c.name}（狼人）：使主人公死亡",
                                         [op("heroes_die")], key=key))
            if self._has(c.id, "nightmare"):
                key = f"nightmare:kill:{c.id}"
                if self._available_key(key):
                    for target in self._living():
                        if target.location == c.location:
                            result.append(option(f"{c.name}（梦魇）：使{target.name}死亡",
                                                 [op("kill", target=target.id)], key=key))
                key = f"nightmare:heroes:{c.id}"
                if self._hsa_curse_total() >= 3 and self._available_key(key):
                    result.append(option(f"{c.name}（梦魇）：使主人公死亡",
                                         [op("heroes_die")], key=key))
            if (self._has(c.id, "sacrifice") and c.intrigue >= 2 and c.paranoia >= 2
                    and self._available_key(f"sacrifice:{c.id}")):
                result.append(option(f"{c.name}（祭品）：使所有角色和主人公死亡",
                                     [op("kill_many", targets=[target.id for target in self._living()]),
                                      op("heroes_die")], key=f"sacrifice:{c.id}"))
            if self.module == "AHR" and self._has(c.id, "piper"):
                if self.ex_gauge >= 2 and self._available_key(f"piper:kill:{c.id}", True):
                    for target in self._living():
                        if target.location == c.location:
                            result.append(option(f"{c.name}（吹笛人）：使{target.name}死亡",
                                                 [op("kill", target=target.id)],
                                                 key=f"piper:kill:{c.id}", once=True))
                for corpse in self.state.characters.values():
                    if not corpse.alive and corpse.location == c.location:
                        result.append(option(f"{c.name}（吹笛人）：{corpse.name}尸体密谋 +1",
                                             [op("counter", target=corpse.id, counter="intrigue", amount=1),
                                              op("ahr_corpse_intrigue_check")],
                                             key=f"piper:corpse:{c.id}"))
        if (self.scenario["main_plot"] == "hsa_cursed_land"
                and any(self.board_ex[board] and not any(
                    c.alive and c.location == board and not self.ex_cards[c.id]
                    for c in self.state.characters.values()) for board in LOCATIONS)):
            result.append(option("被诅咒的土地：无目标的版图诅咒使主人公死亡",
                                 [op("heroes_die")], key="plot:hsa_cursed_land"))
        if self.module == "HSA" and "zombie:move" not in self.day_used:
            for c in self.state.characters.values():
                if c.alive or not self._has(c.id, "zombie"):
                    continue
                x, y = COORDS[c.location]
                for location, coords in COORDS.items():
                    if abs(x - coords[0]) + abs(y - coords[1]) == 1:
                        result.append(option(
                            f"丧尸：将{c.name}的尸体移至{LOCATIONS[location]}",
                            [op("move_corpse", target=c.id, location=location)],
                            key="zombie:move"))
    elif phase == "refusal":
        request = self._request
        if request.get("already_used"):
            return [option("本日已结算此能力；公开宣布本次没有效果", refuse=True)]
        refusal = None if request["unrefusable"] else REFUSAL.get(self.roles[request["source"]])
        if (self._has(request["source"], "paper_tiger")
                and self.state.characters[request["source"]].paranoia >= 2):
            refusal = "mandatory"
        if (self.module == "AHR" and "ahr_jekyll" in self.scenario["subplots"]
                and self._has(request["source"], "ahr_puppet")):
            refusal = "mandatory"
        if (self.module == "LL" and "ll_fabricated_secret" in self.scenario["subplots"]
                and self._has(request["source"], "secret_key")):
            refusal = "optional"
        if (self.module in ("AHR", "LL")
                and self.state.characters[request["source"]].despair):
            refusal = "mandatory"
        if (self.module in ("AHR", "LL")
                and self.state.characters[request["source"]].hope and refusal == "optional"):
            refusal = None
        if refusal != "mandatory":
            result.append(option("执行已声明的友好能力", request["effects"], accept=True))
        if refusal:
            result.append(option("拒绝；公开宣布能力没有效果（仍计入次数）", refuse=True))
        return result
    if phase in ("action_counters", "master_abilities", "goodwill", "day_end"):
        result.append(option("结束本阶段 / 不再发动可选能力", finish=True))
    return deepcopy(result)


def _choose(self, actor, index):
    options = self.options(actor)
    if type(index) is not int or not 1 <= index <= len(options):
        raise RuleError("选择编号无效；请重新查看 options")
    selected = options[index - 1]
    if self._pending:
        source = self._pending_source
        self._pending = None
        self._pending_source = None
        self._decision_actor = None
        self._queue = [SourcedEffect(legacy_effect(effect), source) for effect in selected["effects"]] + self._queue
        self._drain()
        return
    if selected.get("finish"):
        self.ruleset.phases.resolve(self.state.phase).execute(self, actor, "next", {})
        return
    already_used = "key" in selected and selected["key"] in self.day_used
    if "key" in selected:
        self._mark(selected["key"], selected.get("once", False))
    if selected.get("goodwill"):
        selected["already_used"] = already_used
        self.public_day_used.add(selected["key"])
        if selected.get("once"):
            self.public_loop_used.add(selected["key"])
        if self.module == "LL" and selected["source"] not in self._ll_friended_once:
            self._ll_friended_once.add(selected["source"])
            self._event("friended_token_placed",
                        f"{self.name(selected['source'])}首次被声明使用友好能力，放置交友完毕标志。",
                        target=selected["source"])
            if ("ll_myth_collector" in self.scenario["subplots"]
                    and len(self._ll_friended_once) >= 6):
                seat = self._ll_seat_for_secret("B")
                self._win(f"traitor:{seat}", "主人公 B 达成神话收集者的特殊胜利条件。")
                return
        self._request = selected
        self.state.phase = "refusal"
        self._event("goodwill_requested", f"领队声明：{selected['label']}。")
        return
    if self.state.phase == "refusal":
        request = self._request
        self._request = None
        if selected.get("refuse"):
            rei_once = self.module in ("AHR", "LL") and request.get("once")
            if rei_once:
                for used in (self.day_used, self.loop_used,
                             self.public_day_used, self.public_loop_used):
                    used.discard(request["key"])
            detail = ("本轮一次能力被拒绝，不计为已使用；友好不消耗。" if rei_once
                      else "这项友好能力没有效果；次数已使用，友好不消耗。")
            self._event("ability_no_effect", detail)
            if self.module == "WM":
                self._change_ex_gauge(1)
            self.state.phase = "goodwill"
            if self.module == "LL":
                self._return_phase = "goodwill"
                self._queue = (([op("ll_internet_celeb", source=request["source"])]
                                if self._has(request["source"], "internet_celeb") else [])
                               + ([op("reveal", target=request["source"])]
                                  if self._has(request["source"], "secret_key") else []))
                self._drain()
            return
        self._return_phase = "goodwill"
        if self.module == "AHR" and request.get("once"):
            selected["effects"] = list(selected["effects"]) + [
                op("ahr_world_shift", reason="每轮一次的友好能力")]
        if self.module == "AHR" and self._has(request["source"], "ahr_puppet"):
            selected["effects"] = list(selected["effects"]) + [
                op("ahr_puppet_check", target=request["source"])]
        if self.module == "AHR" and self._has(request["source"], "alice"):
            selected["effects"] = list(selected["effects"]) + [
                op("ahr_alice", source=request["source"])]
        if self.module == "LL" and self._has(request["source"], "internet_celeb"):
            selected["effects"] = list(selected["effects"]) + [
                op("ll_internet_celeb", source=request["source"])]
        if self.module == "LL" and self._has(request["source"], "secret_key"):
            selected["effects"] = list(selected["effects"]) + [
                op("reveal", target=request["source"])]
        if self._has(request["source"], "wizard"):
            selected["effects"] = list(selected["effects"]) + [
                op("reveal", target=request["source"]),
                op("choice", actor=self.state.leader,
                   prompt="巫师友好能力已结算：领队是否令 Ex 槽 +1",
                   options=[option("Ex 槽 +1", [op("ex_gauge", amount=1)]),
                            option("不增加 Ex 槽", [])])]
    else:
        self._return_phase = self.state.phase
    self._queue = self._optional_effects(selected, actor)
    self._drain()


OPERATIONS = {
    '_available_key': _available_key,
    '_mark': _mark,
    '_counter_options': _counter_options,
    '_scoped_targets': _scoped_targets,
    '_ability_options': _ability_options,
    'options': options,
    '_choose': _choose,
}
