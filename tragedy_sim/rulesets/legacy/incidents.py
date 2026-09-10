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

def _incident(self):
    scheduled_day = self._scheduled_day()
    incident = next((i for i in self.scenario["incidents"] if i["day"] == scheduled_day), None)
    if incident is None:
        self._event("no_incident", "今日没有预定事件。")
        self._begin_night()
        return
    if self.module == "HSA":
        self._hsa_incident(incident)
        return
    if self.module == "WM":
        self._wm_incident(incident)
        return
    if self.module == "AHR":
        self._ahr_incident(incident)
        return
    if self.module == "LL":
        self._ll_incident(incident)
        return
    culprit = self.state.characters[incident["culprit"]]
    kind = incident["kind"]
    threshold = CHARACTERS[culprit.id].limit
    if self.module == "MC" and kind == "omen":
        threshold -= 1
    elif self.module == "MC" and kind == "bizarre_murder":
        threshold += 1
    prophet_alive = any(self._has(c.id, "prophet") for c in self.state.characters.values())
    if ("mz_doom_song" in self.scenario["subplots"] and self.roles[culprit.id] == "ordinary"
            and prophet_alive):
        threshold -= 1
    prophet_blocks = any(self._has(c.id, "prophet") and c.id != culprit.id
                         and c.location == culprit.location for c in self.state.characters.values())
    forced = self._has(culprit.id, "obsessive")
    if self.module == "MC" and self.ex_gauge == 0:
        forced |= any(self._has(c.id, "detective") and c.location == culprit.location
        for c in self.state.characters.values())

    incident_paranoia = culprit.paranoia
    if (self.scenario["main_plot"] == "mc_strychnine"
            and kind in ("serial_murder", "suicide")):
        incident_paranoia += culprit.intrigue
    prevented = culprit.id in self._prevented_incident_culprits
    happened = (culprit.alive and not prevented
                and (forced or (not prophet_blocks and incident_paranoia >= threshold)))
    public_kind = incident.get("public_kind", kind)
    record = {"day": self.state.round, "kind": public_kind, "happened": happened, "effective": False}
    self.incident_records.append(record)
    self._event("incident_status", f"第 {self.state.round} 天「{INCIDENT_NAMES[public_kind]}」："
                + ("发生。" if happened else "未发生。"), incident=public_kind, happened=happened)
    if not happened:
        self._begin_night()
        return
    self._incident_before = self._public_board()
    self._incident_effect = self.module == "MC" and kind == "silver_bullet"
    if self.module == "MC":
        effects = [op("ex_gauge", amount=0 if kind == "silver_bullet" else
                      (2 if kind == "bizarre_murder" else 1))]
        effects += self._mc_incident_effects(kind, culprit.id)
        if self._has(culprit.id, "fool"):
            effects.append(op("clear_paranoia", target=culprit.id))
        effects.append(op("incident_done"))
        effects.append(op("finish_loop", reason="银色子弹使轮回结束") if kind == "silver_bullet"
                       else op("night"))
        self._queue = effects
        self._return_phase = "day_end"
        self._drain()
        return
    if self.module == "MZ":
        effects = self._mz_incident_effects(kind, culprit.id)
        # Copy effects refer to the public incident list.  A fake incident
        # therefore contributes its announced name, not its secret effect.
        self._occurred_incidents.append({"kind": public_kind, "culprit": culprit.id})
        self._queue = effects + [op("incident_done"), op("night")]
        self._return_phase = "day_end"
        self._drain()
        return
    living = self._living()
    choices, effects = [], []
    if kind in ("murder", "faraway"):
        targets = ([c for c in living if c.id != culprit.id and c.location == culprit.location]
                   if kind == "murder" else [c for c in living if c.intrigue >= 2])
        choices = [option(f"使{c.name}死亡", [op("kill", target=c.id)]) for c in targets]
    elif kind == "suicide":
        effects = [op("kill", target=culprit.id)]
    elif kind == "hospital":
        if self.state.locations["hospital"] >= 1:
            effects.append(op("kill_many", targets=[c.id for c in living if c.location == "hospital"]))
        if self.state.locations["hospital"] >= 2:
            effects.append(op("heroes_die"))
    elif kind == "foul_play":
        effects = [op("counter", target="shrine", counter="intrigue", amount=2)]
    elif kind == "malicious_rumor":
        effects = [op("counter", target=c.id, counter="paranoia", amount=2)
                   for c in living if c.location == culprit.location]
    elif kind == "poison_gas":
        choices = [option(f"{LOCATIONS[culprit.location]}与{LOCATIONS[location]}各获得密谋 +1",
                          [op("counter", target=culprit.location, counter="intrigue", amount=1),
                           op("counter", target=location, counter="intrigue", amount=1)])
                   for location in LOCATIONS if location != culprit.location]
    elif kind == "exposure":
        same = [c for c in living if c.location == culprit.location]
        for index, first in enumerate(same):
            for second in same[index:]:
                add_effects = [op("counter", target=first.id, counter="goodwill", amount=1),
                               op("counter", target=second.id, counter="goodwill", amount=1)]
                choices.append(option(f"放置 2 友好：{first.name}、{second.name}", add_effects))
                if first.id == second.id and first.goodwill >= 2:
                    choices.append(option(f"移除 2 友好：{first.name}",
                                          [op("counter", target=first.id, counter="goodwill", amount=-2)]))
                elif first.id != second.id and first.goodwill and second.goodwill:
                    choices.append(option(f"移除 2 友好：{first.name}、{second.name}",
                                          [op("counter", target=first.id, counter="goodwill", amount=-1),
                                           op("counter", target=second.id, counter="goodwill", amount=-1)]))
    elif kind == "confession":
        effects = [op("reveal", target=culprit.id)]
    elif kind == "missing":
        choices = [option(f"将{culprit.name}移至{LOCATIONS[loc]}，随后所在版图密谋 +1",
                          [op("move", target=culprit.id, location=loc), op("missing_intrigue", target=culprit.id)])
                   for loc in LOCATIONS if loc not in culprit.forbidden]
    elif kind in ("unease", "spreading"):
        counter, amount = ("paranoia", 2) if kind == "unease" else ("goodwill", -2)
        for a in living:
            follow = [option(f"{b.name}：{'密谋 +1' if kind == 'unease' else '友好 +2'}",
                             [op("counter", target=b.id, counter="intrigue" if kind == "unease" else "goodwill",
                                 amount=1 if kind == "unease" else 2)]) for b in living if b.id != a.id]
            choices.append(option(f"{a.name}：{COUNTER_NAMES[counter]} {amount:+}",
                                  [op("counter", target=a.id, counter=counter, amount=amount),
                                   op("choice", prompt="选择另一个目标", options=follow)]))
    elif kind == "butterfly":
        choices = [option(f"{c.name}：{COUNTER_NAMES[counter]} +1", [op("counter", target=c.id, counter=counter, amount=1)])
                   for c in living if c.location == culprit.location for counter in STANDARD_COUNTERS]
    if kind in ("murder", "faraway", "missing", "unease", "spreading", "butterfly",
                "poison_gas", "exposure"):
        effects = [op("choice", prompt=f"结算{INCIDENT_NAMES[kind]}：选择合法目标", options=choices)]
    self._queue = effects + [op("incident_done"), op("night")]
    self._return_phase = "day_end"
    self._drain()


def _hsa_incident(self, incident):
    kind = incident["kind"]
    group_requirements = {"frenzied_night": 0, "curse_awakening": 1,
                          "filth_overflow": 2, "dead_apocalypse": 2}
    group = kind in group_requirements
    if group:
        board = incident["culprit"]
        happened = self._hsa_corpses(board) > group_requirements[kind]
        culprit = None
    else:
        culprit = self.state.characters[incident["culprit"]]
        board = culprit.location
        threshold = CHARACTERS[culprit.id].limit - (kind == "funeral")
        happened = culprit.alive and culprit.paranoia >= threshold
    record = {"day": self.state.round, "kind": kind, "happened": happened, "effective": False}
    if group:
        record["board"] = board
    self.incident_records.append(record)
    self._event("incident_status", f"第 {self.state.round} 天「{INCIDENT_NAMES[kind]}」："
                + ("发生。" if happened else "未发生。"), incident=kind, happened=happened)
    if not happened:
        self._begin_night()
        return
    self._incident_before = self._public_board()
    living = self._living()
    effects = []
    if kind == "frenzied_murder":
        choices = [option(f"使{target.name}死亡", [op("kill", target=target.id)])
                   for target in living if target.id != culprit.id and target.location == board]
        choices.append(option(f"在{LOCATIONS[board]}放置一具尸体",
                              [op("counter", target=board, counter="intrigue", amount=1)]))
        effects = [op("choice", prompt="结算癫狂杀人", options=choices)]
    elif kind == "unease":
        choices = []
        for first in living:
            follow = [option(f"{second.name}：密谋 +1",
                             [op("counter", target=second.id, counter="intrigue", amount=1)])
                      for second in living if second.id != first.id]
            choices.append(option(f"{first.name}：不安 +2",
                                  [op("counter", target=first.id, counter="paranoia", amount=2),
                                   op("choice", prompt="选择另一名角色密谋 +1", options=follow)]))
        effects = [op("choice", prompt="结算不安扩散", options=choices)]
    elif kind == "missing":
        effects = [op("choice", prompt="结算失踪", options=[
            option(f"将{culprit.name}移至{LOCATIONS[location]}，随后版图增加一具尸体",
                   [op("move", target=culprit.id, location=location),
                    op("missing_intrigue", target=culprit.id)])
            for location in LOCATIONS if location not in culprit.forbidden])]
    elif kind == "foul_play":
        effects = [op("counter", target="shrine", counter="intrigue", amount=2)]
    elif kind == "funeral":
        effects = [op("choice", actor=self.state.leader, prompt="送葬：领队选择一名角色死亡",
                      options=[option(f"使{target.name}死亡", [op("kill", target=target.id)])
                               for target in living])]
    elif kind == "curse_declaration":
        effects = [op("hsa_add_curse", target=culprit.id)]
    elif kind == "barricade":
        groups = []
        for target in living:
            if target.id == culprit.id or target.location != board:
                continue
            groups.append({"prompt": f"孤守：移动{target.name}", "options": [
                option(f"将{target.name}移至{LOCATIONS[location]}",
                       [op("move", target=target.id, location=location)])
                for location in LOCATIONS
                if location != board and location not in target.forbidden]})
        effects = [op("mandatory_choice_batch", choices=groups)]
    elif kind == "frenzied_night":
        effects = [op("hsa_frenzied_night")]
    elif kind == "curse_awakening":
        effects = [op("hsa_add_curse", target=board)]
    elif kind == "filth_overflow":
        targets = [target for target in living if target.location == board]
        effects = [op("choice", prompt="污秽溢出：选择不安目标", options=[
            option(f"{target.name}不安 +2", [op("counter", target=target.id,
                                                 counter="paranoia", amount=2),
                                           op("choice", prompt="选择增加尸体的版图", options=[
                                               option(f"{LOCATIONS[location]}增加一具尸体",
                                                      [op("counter", target=location,
                                                          counter="intrigue", amount=1)])
                                               for location in LOCATIONS])])
            for target in targets])]
    elif kind == "dead_apocalypse":
        effects = [op("hsa_apocalypse", board=board)]
    self._queue = effects + [op("incident_done"), op("night")]
    self._return_phase = "day_end"
    self._drain()


def _wm_incident(self, incident):
    kind = incident["kind"]
    culprit = self.state.characters[incident["culprit"]]
    threshold = CHARACTERS[culprit.id].limit - (kind == "funeral")
    if kind == "dagon_whisper":
        incident_score = culprit.intrigue
    else:
        incident_score = culprit.paranoia + (culprit.intrigue if self._has(culprit.id, "sacrifice") else 0)
    happened = culprit.alive and incident_score >= threshold
    self.incident_records.append({"day": self.state.round, "kind": kind,
                                  "happened": happened, "effective": False})
    self._event("incident_status", f"第 {self.state.round} 天「{INCIDENT_NAMES[kind]}」："
                + ("发生。" if happened else "未发生。"), incident=kind, happened=happened)
    if not happened:
        self._begin_night()
        return
    self._incident_before = self._public_board()
    living = self._living()
    effects = []
    if kind == "frenzied_murder":
        effects = [op("choice", prompt="癫狂杀人：选择死亡角色", options=[
            option(f"使{target.name}死亡", [op("kill", target=target.id)])
            for target in living if target.id != culprit.id and target.location == culprit.location])]
    elif kind == "mass_suicide":
        if culprit.intrigue >= 1:
            effects = [op("kill_many", targets=[target.id for target in living
                                                 if target.location == culprit.location])]
    elif kind == "unease":
        choices = []
        for first in living:
            follow = [option(f"{second.name}：密谋 +1",
                             [op("counter", target=second.id, counter="intrigue", amount=1)])
                      for second in living if second.id != first.id]
            choices.append(option(f"{first.name}：不安 +2",
                                  [op("counter", target=first.id, counter="paranoia", amount=2),
                                   op("choice", prompt="选择另一名角色密谋 +1", options=follow)]))
        effects = [op("choice", prompt="结算不安扩散", options=choices)]
    elif kind == "missing":
        effects = [op("choice", prompt="结算失踪", options=[
            option(f"将{culprit.name}移至{LOCATIONS[location]}，随后所在版图密谋 +1",
                   [op("move", target=culprit.id, location=location),
                    op("missing_intrigue", target=culprit.id)])
            for location in LOCATIONS if location not in culprit.forbidden])]
    elif kind == "foul_play":
        effects = [op("counter", target="shrine", counter="intrigue", amount=2)]
    elif kind == "hospital":
        if self.state.locations["hospital"] >= 1:
            effects.append(op("kill_many", targets=[target.id for target in living
                                                     if target.location == "hospital"]))
        if self.state.locations["hospital"] >= 2:
            effects.append(op("heroes_die"))
    elif kind == "riot":
        for board in ("school", "city"):
            if self.state.locations[board] >= 1:
                effects.append(op("kill_many", targets=[target.id for target in living
                                                         if target.location == board]))
    elif kind == "extinction":
        effects = [op("wm_extinction")]
    elif kind == "dagon_whisper":
        effects = [op("wm_dagon_active")]
    elif kind == "discovery":
        effects = [op("ex_gauge", amount=1)]
    elif kind == "funeral":
        effects = [op("choice", actor=self.state.leader, prompt="送葬：领队选择一名角色死亡",
                      options=[option(f"使{target.name}死亡", [op("kill", target=target.id)])
                               for target in living])]
    dagon_kills = self._wm_dagon_active and kind != "dagon_whisper"
    self._queue = effects + [op("incident_done")] \
        + ([op("heroes_die")] if dagon_kills else []) + [op("night")]
    self._return_phase = "day_end"
    self._drain()


def _ahr_incident(self, incident):
    kind = incident["kind"]
    culprit = self.state.characters[incident["culprit"]]
    threshold = CHARACTERS[culprit.id].limit - (kind == "impulsive_murder")
    score = (self._count(culprit, "intrigue") if kind == "imaginary_incident" else
             self._count(culprit, "goodwill")
             if (self.ex_gauge % 2 or kind == "hope_light") else
             self._count(culprit, "paranoia"))
    happened = culprit.alive and (kind == "dimension_swap" or self._has(culprit.id, "obsessive")
                                  or score >= threshold)
    self.incident_records.append({"day": self.state.round, "kind": kind,
                                  "happened": happened, "effective": False})
    self._event("incident_status", f"第 {self.state.round} 天「{INCIDENT_NAMES[kind]}」："
                + ("发生。" if happened else "未发生。"), incident=kind, happened=happened)
    if not happened:
        self._begin_night()
        return
    self._incident_before = self._public_board()
    living = self._living()

    def murder_effects():
        return [op("choice", prompt="冲动杀人：选择同区域另一名角色死亡", options=[
            option(f"使{target.name}死亡", [op("kill", target=target.id)])
            for target in living if target.id != culprit.id and target.location == culprit.location])]

    def distortion_effects():
        return [op("choice", prompt="次元歪曲：是否触发世界线变动", options=[
            option("触发世界线变动", [op("ahr_world_shift", reason="次元歪曲")]),
            option("不触发世界线变动", [])]),
                op("choice", prompt="次元歪曲：选择不安 +2 的角色", options=[
                    option(f"{first.name}不安 +2", [
                        op("counter", target=first.id, counter="paranoia", amount=2),
                        op("choice", prompt="选择另一名角色友好 +2", options=[
                            option(f"{second.name}友好 +2",
                                   [op("counter", target=second.id, counter="goodwill", amount=2)])
                            for second in living if second.id != first.id])])
                    for first in living])]

    def lost_effects():
        choices = []
        for target in living:
            if target.id == culprit.id or target.location != culprit.location:
                continue
            choices.append(option(f"移动{target.name}", [op("choice", prompt="选择目的地", options=[
                option(LOCATIONS[board], [op("move", target=target.id, location=board),
                                          op("move", target=culprit.id,
                                             location=self._loop_initial_locations[culprit.id])])
                for board in LOCATIONS if board not in target.forbidden])]))
        return [op("choice", prompt="遗失之物：选择同区域另一名角色", options=choices)]

    if kind == "impulsive_murder":
        effects = murder_effects()
    elif kind == "dimension_swap":
        effects = [op("ahr_world_shift", reason="次元转换")]
    elif kind == "dimension_distortion":
        effects = distortion_effects()
    elif kind == "dimension_break":
        effects = [op("choice", prompt="次元断层：是否触发世界线变动", options=[
            option("触发世界线变动", [op("ahr_world_shift", reason="次元断层")]),
            option("不触发世界线变动", [])]), op("ahr_dimension_break", target=culprit.id)]
    elif kind == "lost_property":
        effects = lost_effects()
    elif kind == "imaginary_incident":
        effects = [op("choice", prompt="空想事件：选择一种事件效果", options=[
            option("冲动杀人", murder_effects()), option("次元歪曲", distortion_effects()),
            option("遗失之物", lost_effects())])]
    elif kind == "hospital":
        effects = []
        if self.state.locations["hospital"] >= 1:
            effects.append(op("kill_many", targets=[c.id for c in living if c.location == "hospital"]))
        if self.state.locations["hospital"] >= 2:
            effects.append(op("heroes_die"))
    elif kind == "will":
        effects = [op("kill", target=culprit.id), op("ahr_will")]
    elif kind == "singularity":
        if self.ex_gauge % 2 == 0:
            if not self._ahr_singularity_occurred:
                effects = [op("ahr_singularity_first"), op("heroes_die")]
            else:
                effects = [op("ahr_world_shift", reason="奇点再次发生")]
        else:
            effects = [*[op("counter", target=c.id, counter="intrigue", amount=1)
                          for c in living if c.location == culprit.location],
                       op("ahr_singularity_hidden", target=culprit.id)]
    elif kind == "hope_light":
        effects = [op("choice", actor=self.state.leader, prompt="隙间阳光：领队选择希望目标",
                      options=[option(f"{c.name}希望 +1",
                                      [op("counter", target=c.id, counter="hope", amount=1)])
                               for c in living])]
    else:
        effects = [op("choice", prompt="绝望之暗：选择绝望目标", options=[
            option(f"{c.name}绝望 +1", [op("counter", target=c.id, counter="despair", amount=1)])
            for c in living])]
    self._queue = effects + [op("incident_done"), op("night")]
    self._return_phase = "day_end"
    self._drain()


def _ll_incident(self, incident):
    kind = incident["kind"]
    culprit = self.state.characters[incident["culprit"]]
    score = (self._count(culprit, "goodwill") if kind == "hope_light"
             else self._count(culprit, "paranoia"))
    watcher_forces = (culprit.despair >= 1 and any(
        self._has(c.id, "watcher") and c.location == culprit.location for c in self._living()))
    happened = culprit.alive and (watcher_forces or score >= CHARACTERS[culprit.id].limit)
    self.incident_records.append({"day": self.state.round, "kind": kind,
                                  "happened": happened, "effective": False})
    self._event("incident_status", f"第 {self.state.round} 天「{INCIDENT_NAMES[kind]}」："
                + ("发生。" if happened else "未发生。"), incident=kind, happened=happened)
    if not happened:
        self._begin_night()
        return
    self._incident_before = self._public_board()
    living = self._living()
    if kind == "murder":
        effects = [op("choice", prompt="谋杀：选择同区域另一名角色死亡", options=[
            option(f"使{c.name}死亡", [op("kill", target=c.id)]) for c in living
            if c.id != culprit.id and c.location == culprit.location])]
    elif kind == "unease":
        effects = [op("choice", prompt="不安扩散：选择不安目标", options=[
            option(f"{first.name}不安 +2", [op("counter", target=first.id, counter="paranoia", amount=2),
                op("choice", prompt="选择另一名角色密谋 +1", options=[
                    option(f"{second.name}密谋 +1",
                           [op("counter", target=second.id, counter="intrigue", amount=1)])
                    for second in living if second.id != first.id])]) for first in living])]
    elif kind == "missing":
        effects = [op("choice", prompt="失踪：选择当事人的目的地", options=[
            option(f"移至{LOCATIONS[board]}", [op("move", target=culprit.id, location=board),
                op("counter", target=self._loop_initial_locations[culprit.id],
                   counter="intrigue", amount=1)])
            for board in LOCATIONS if board not in culprit.forbidden])]
    elif kind == "hospital":
        effects = []
        if self.state.locations["hospital"] >= 1:
            effects.append(op("kill_many", targets=[c.id for c in living if c.location == "hospital"]))
        if self.state.locations["hospital"] >= 2:
            effects.append(op("heroes_die"))
    elif kind == "executor":
        effects = [op("choice", prompt="执行者：剧作家选择一位主人公", options=[
            option(f"由{ACTOR_NAMES[actor]}选择", [op("choice", actor=actor,
                prompt="执行者：选择一名角色死亡", options=[
                    option(f"使{c.name}死亡", [op("kill", target=c.id)]) for c in living])])
            for actor in PROTAGONISTS])]
    elif kind == "metamorphosis":
        effects = ([op("kill", target=culprit.id)]
                   if self.state.locations[self._loop_initial_locations[culprit.id]] >= 2 else [])
    elif kind == "cocoon":
        board = self._loop_initial_locations[culprit.id]
        effects = ([op("counter", target=board, counter="intrigue", amount=2)]
                   if self.state.locations[board] <= 1 else [])
    elif kind == "will":
        effects = [op("kill", target=culprit.id), op("ll_will")]
    elif kind == "confession":
        effects = [op("reveal", target=culprit.id)]
    elif kind == "spreading":
        effects = [op("choice", prompt="散播：选择移除友好的角色", options=[
            option(f"{first.name}友好 -2", [op("counter", target=first.id, counter="goodwill", amount=-2),
                op("choice", prompt="选择另一名角色友好 +2", options=[
                    option(f"{second.name}友好 +2",
                           [op("counter", target=second.id, counter="goodwill", amount=2)])
                    for second in living if second.id != first.id])]) for first in living])]
    elif kind == "hope_light":
        effects = [op("choice", actor=self.state.leader, prompt="希望之光：领队选择一名角色",
                      options=[option(f"{c.name}希望 +1",
                                      [op("counter", target=c.id, counter="hope", amount=1)])
                               for c in living])]
    else:
        effects = [op("choice", prompt="绝望之暗：选择一名角色", options=[
            option(f"{c.name}绝望 +1", [op("counter", target=c.id, counter="despair", amount=1)])
            for c in living])]
    self._queue = effects + [op("incident_done"), op("night")]
    self._return_phase = "day_end"
    self._drain()


def _mc_incident_location(self, culprit_id):
    location = self.state.characters[culprit_id].location
    if not self._has(culprit_id, "twin"):
        return location
    x, y = COORDS[location]
    return next(board for board, coords in COORDS.items() if coords == (x ^ 1, y ^ 1))


def _mc_incident_effects(self, kind, culprit_id):
    culprit = self.state.characters[culprit_id]
    living = self._living()
    location = self._mc_incident_location(culprit_id)
    same = [c for c in living if c.id == culprit_id or c.location == location]
    if kind == "serial_murder":
        targets = [c for c in same if c.id != culprit_id]
        return [op("choice", prompt="结算连续杀人：选择一名同区域角色",
                   options=[option(f"使{c.name}死亡", [op("kill", target=c.id)]) for c in targets])]
    if kind == "terror_attack":
        effects = []
        if self.state.locations["city"] >= 1:
            effects.append(op("kill_many", targets=[c.id for c in living if c.location == "city"]))
        if self.state.locations["city"] >= 2:
            effects.append(op("heroes_die"))
        return effects
    if kind == "hospital":
        effects = []
        if self.state.locations["hospital"] >= 1:
            effects.append(op("kill_many", targets=[c.id for c in living if c.location == "hospital"]))
        if self.state.locations["hospital"] >= 2:
            effects.append(op("heroes_die"))
        return effects
    if kind == "suicide":
        return [op("kill", target=culprit_id)]
    if kind == "unease":
        choices = []
        for first in living:
            follow = [option(f"{second.name}：密谋 +1",
                             [op("counter", target=second.id, counter="intrigue", amount=1)])
                      for second in living if second.id != first.id]
            choices.append(option(f"{first.name}：不安 +2",
                                  [op("counter", target=first.id, counter="paranoia", amount=2),
                                   op("choice", prompt="选择另一个角色获得密谋 +1", options=follow)]))
        return [op("choice", prompt="结算不安扩散：选择不安目标", options=choices)]
    if kind == "omen":
        return [op("choice", prompt="结算前兆：选择同区域角色获得 1 不安",
                   options=[option(f"{c.name}：不安 +1",
                                   [op("counter", target=c.id, counter="paranoia", amount=1)])
                            for c in same])]
    if kind == "bizarre_murder":
        return (self._mc_incident_effects("serial_murder", culprit_id)
                + self._mc_incident_effects("unease", culprit_id))
    if kind == "fake_suicide":
        return [op("place_ex", target=culprit_id), op("fake_incident_active")]
    if kind == "suspicious_letter":
        choices = []
        for target in same:
            for destination in LOCATIONS:
                if destination in target.forbidden:
                    continue
                choices.append(option(f"将{target.name}移至{LOCATIONS[destination]}",
                                      [op("suspicious_move", target=target.id,
                                          location=destination)]))
        return [op("choice", prompt="结算可疑信件：选择角色及目的地", options=choices)]
    if kind == "lockdown":
        return [op("seal_board", board=location)]
    return []


def _mz_incident_effects(self, kind, culprit_id):
    culprit = self.state.characters[culprit_id]
    living = self._living()
    if kind == "serial_murder":
        targets = [c for c in living if c.id != culprit_id and c.location == culprit.location]
        return [op("choice", prompt="结算连续杀人：选择一名同区域角色",
                   options=[option(f"使{c.name}死亡", [op("kill", target=c.id)]) for c in targets])]
    if kind == "suicide":
        return [op("kill", target=culprit_id)]
    if kind == "unease":
        choices = []
        for first in living:
            follow = [option(f"{second.name}：密谋 +1",
                             [op("counter", target=second.id, counter="intrigue", amount=1)])
                      for second in living if second.id != first.id]
            choices.append(option(f"{first.name}：不安 +2",
                                  [op("counter", target=first.id, counter="paranoia", amount=2),
                                   op("choice", prompt="选择另一个角色获得密谋 +1", options=follow)]))
        return [op("choice", prompt="结算不安扩散：选择不安目标", options=choices)]
    if kind == "missing":
        choices = [option(f"将{culprit.name}移至{LOCATIONS[location]}，随后所在版图密谋 +1",
                          [op("move", target=culprit_id, location=location),
                           op("missing_intrigue", target=culprit_id)])
                   for location in LOCATIONS if location not in culprit.forbidden]
        return [op("choice", prompt="结算失踪：选择目的地", options=choices)]
    if kind == "covert_activity":
        past = []
        for record in self._occurred_incidents:
            if record["kind"] != "covert_activity" and record["kind"] not in past:
                past.append(record["kind"])
        choices = [option(f"复制{INCIDENT_NAMES[past_kind]}的效果",
                          [op("copy_mz_incident", incident=past_kind, culprit=culprit_id)])
                   for past_kind in past]
        return [op("choice", prompt="隐蔽活动：选择此前发生过的事件效果", options=choices)]
    if kind == "hospital":
        effects = []
        if self.state.locations["hospital"] >= 1:
            effects.append(op("kill_many", targets=[c.id for c in living if c.location == "hospital"]))
        if self.state.locations["hospital"] >= 2:
            effects.append(op("heroes_die"))
        return effects
    if kind == "riot":
        victims = [c.id for c in living
                   if ((c.location == "hospital" and self.state.locations["hospital"] >= 1)
                       or (c.location == "school" and self.state.locations["school"] >= 1)
                       or (c.location == "city" and self.state.locations["city"] >= 1))]
        effects = [op("kill_many", targets=victims)] if victims else []
        if self.state.locations["hospital"] >= 2:
            effects.append(op("heroes_die"))
        return effects
    if kind == "confession":
        return [op("reveal", target=culprit_id)]
    if kind == "breakthrough":
        targets = [*LOCATIONS, *(c.id for c in self.state.characters.values())]
        return [op("choice", actor=self.state.leader, prompt="破局：由领队选择移除密谋的目标",
                   options=[option(f"{self.name(target)}：密谋 -2",
                                   [op("counter", target=target, counter="intrigue", amount=-2)])
                            for target in targets])]
    if kind == "fake_suicide":
        return [op("place_ex", target=culprit_id)]
    if kind == "fake_incident":
        effects = [op("place_ex", target=culprit_id), op("fake_incident_active")]
        if culprit.intrigue >= 2:
            effects.append(op("heroes_die"))
        return effects
    return []


def _record_incident_end(self):
    if self._incident_before is not None:
        changed = self._incident_effect or self._incident_before != self._public_board()
        self.incident_records[-1]["effective"] = changed
        self._event("incident_ended", "事件结算完成。" if changed else "事件已经发生，但未产生效果。", effective=changed)
        self._incident_before = None


OPERATIONS = {
    '_incident': _incident,
    '_hsa_incident': _hsa_incident,
    '_wm_incident': _wm_incident,
    '_ahr_incident': _ahr_incident,
    '_ll_incident': _ll_incident,
    '_mc_incident_location': _mc_incident_location,
    '_mc_incident_effects': _mc_incident_effects,
    '_mz_incident_effects': _mz_incident_effects,
    '_record_incident_end': _record_incident_end,
}
