"""Complete FS/BTX match flow. Effects are deterministic; choices belong to humans.

All logs are public. Secret roles, requirements and offered mastermind options are
kept outside the public projection. dispatch() is atomic and is also the replay API.
"""

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

from .cards import ACTORS, ACTOR_NAMES, COUNTER_NAMES, LOCATIONS, PROTAGONISTS, deck
from .catalog import CHARACTERS, INCIDENT_NAMES, MODULE_PLOTS, PLOTS, REFUSAL, ROLE_NAMES, TRAIT_NAMES
from .engine import ActionGame, Character, RuleError, State
from .scenario import example_scenario, validate_scenario


def op(kind, **kwargs):
    return {"kind": kind, **kwargs}


def option(label, effects=(), **kwargs):
    return {"label": label, "effects": list(effects), **kwargs}


class Game(ActionGame):
    def __init__(self, scenario=None):
        self.scenario = validate_scenario(example_scenario() if scenario is None else scenario)
        chars = [Character(cid, CHARACTERS[cid].name, CHARACTERS[cid].start, CHARACTERS[cid].forbidden)
                 for cid in self.scenario["cast"]]
        super().__init__(chars, module=self.scenario["module"])
        self.roles = dict(self.scenario["cast"])
        self.known_roles = {}
        self.known_culprits = {}
        self.known_plots = []
        self.day_used = set()
        self.loop_used = set()
        self.public_day_used = set()
        self.public_loop_used = set()
        self.guards = dict.fromkeys(self.roles, 0)
        self.protected = False
        self.incident_records = []
        self.winner = None
        self.history = []
        self.loss_reasons = []  # private diagnostic information
        self._queue = []
        self._pending = None
        self._return_phase = None
        self._request = None
        self._ignore_intrigue = set()
        self._previous_goodwill = set()
        self._incident_before = None
        self._incident_effect = False
        self._guess_remaining = []
        self.state.phase = "day_start"
        self._event("loop_started", f"第 1 轮回开始，共 {self.scenario['loops']} 轮，每轮 {self.scenario['days']} 天。")

    @property
    def controller(self):
        if self.state.phase == "game_over":
            return None
        if self.next_actor:
            return self.next_actor
        if self.state.phase in ("goodwill", "final_guess"):
            return self.state.leader
        return "m"

    def name(self, target):
        return self.state.characters[target].name if target in self.state.characters else LOCATIONS.get(target, target)

    def _event(self, kind, message, **data):
        super()._event(kind, message, **data)
        self.state.events[-1]["phase"] = self.state.phase

    def dispatch(self, actor, action, **args):
        shapes = {"play": {"card", "target"}, "resolve": set(), "next": set(),
                  "choose": {"index"}, "guess": {"character", "role"}, "final": set()}
        if actor not in ACTORS or action not in shapes or set(args) != shapes[action]:
            raise RuleError("未知玩家、命令或参数")
        if action == "final":
            if self.module != "BTX" or self.state.phase != "loop_end" or actor != self.state.leader:
                raise RuleError("只有 BTX 轮回之间，领队才能选择提前进入最终猜测")
        elif actor != self.controller:
            raise RuleError(f"当前需要 {ACTOR_NAMES.get(self.controller, '无人')} 操作")
        snapshot = deepcopy(self.__dict__)
        try:
            if action == "play":
                super().play(actor, args["card"], args["target"])
            elif action == "resolve":
                self.resolve()
            elif action == "next":
                self._advance()
            elif action == "choose":
                self._choose(actor, args["index"])
            elif action == "guess":
                self._guess(args["character"], args["role"])
            else:
                self._start_final_guess()
        except Exception:
            self.__dict__.clear()
            self.__dict__.update(snapshot)
            raise
        self.history.append({"actor": actor, "action": action, **deepcopy(args)})

    def next_round(self):
        raise RuleError("完整对局请使用 next 按阶段推进，不能跳过结算")

    def reset_loop(self):
        raise RuleError("完整对局不能随意重置轮回")

    def _living(self):
        return [c for c in self.state.characters.values() if c.alive]

    def _has(self, cid, role):
        if not self.state.characters[cid].alive:
            return False
        return self.roles[cid] == role or (self.roles[cid] == "factor" and
                ((role == "key" and self.state.locations["city"] >= 2) or
                 (role == "conspiracy" and self.state.locations["school"] >= 2)))

    def _counter_mutated(self, target, counter):
        if "virus" in self.scenario["subplots"]:
            for c in self._living():
                if self.roles[c.id] == "ordinary" and c.paranoia >= 3:
                    self.roles[c.id] = "serial"  # Mandatory, permanent until the next loop; not announced.

    def _ignore_forbid(self, counter, target):
        location = self.state.characters[target].location if target in self.state.characters else target
        return ((counter == "intrigue" and location in self._ignore_intrigue) or
                (counter == "goodwill" and target in self.roles and self._has(target, "time_traveler")))

    def resolve(self):
        self._reveal_and_move()
        self._ignore_intrigue.clear()
        # Always pause here, not only when a Cultist exists; the public phase reveals no role.
        self._event("resolution_window", "移动已结算。请剧作家确认行动结算中的能力，再继续结算计数物。")

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
        if not c.alive or c.goodwill < ability.threshold or key in used_day or (ability.once and key in used_loop):
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
        elif ability.kind == "recover":
            results = [option(f"{label} → {deck(self.state.leader)[card].name}",
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
                    for counter in (*COUNTER_NAMES, "guard"):
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
                if c.id == "doctor" and self.roles[c.id] in REFUSAL:
                    # Same daily limit as the Doctor's protagonist ability.
                    for choice in self._ability_options(c.id, CHARACTERS[c.id].abilities[0], private=True):
                        choice["goodwill"] = False
                        result.append(choice)
            if "rumor" in self.scenario["subplots"]:
                result += self._counter_options(None, "plot:rumor", list(LOCATIONS), "intrigue", 1,
                                                "流言四起（每轮一次）", True)
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
                            if self.roles[t.id] == "key" and t.location == c.location and t.intrigue >= 2:
                                result.append(option(f"{c.name}（杀手）：使{t.name}死亡", [op("kill", target=t.id)], key=key))
                    key = f"killer:heroes:{c.id}"
                    if c.intrigue >= 4 and self._available_key(key):
                        result.append(option(f"{c.name}（杀手）：使主人公死亡", [op("heroes_die")], key=key))
                if self._has(c.id, "lover") and c.paranoia >= 3 and c.intrigue >= 1:
                    key = f"lover:{c.id}"
                    if self._available_key(key):
                        result.append(option(f"{c.name}（求爱者）：使主人公死亡", [op("heroes_die")], key=key))
                if self._has(c.id, "time_traveler") and self.state.round == self.scenario["days"] and c.goodwill <= 2:
                    key = f"time_traveler:{c.id}"
                    if self._available_key(key):
                        result.append(option(f"{c.name}（时间旅行者）：使主人公失败", [op("lose")], key=key))
        elif phase == "refusal":
            request = self._request
            if request.get("already_used"):
                return [option("本日已结算此能力；公开宣布本次没有效果", refuse=True)]
            refusal = None if request["unrefusable"] else REFUSAL.get(self.roles[request["source"]])
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
            self._pending = None
            self._queue = selected["effects"] + self._queue
            self._drain()
            return
        if selected.get("finish"):
            self._advance()
            return
        already_used = "key" in selected and selected["key"] in self.day_used
        if "key" in selected:
            self._mark(selected["key"], selected.get("once", False))
        if selected.get("goodwill"):
            selected["already_used"] = already_used
            self.public_day_used.add(selected["key"])
            if selected.get("once"):
                self.public_loop_used.add(selected["key"])
            self._request = selected
            self.state.phase = "refusal"
            self._event("goodwill_requested", f"领队声明：{selected['label']}。")
            return
        if self.state.phase == "refusal":
            self._request = None
            if selected.get("refuse"):
                self._event("ability_no_effect", "这项友好能力没有效果；次数已使用，友好不消耗。")
                self.state.phase = "goodwill"
                return
            self._return_phase = "goodwill"
        else:
            self._return_phase = self.state.phase
        self._queue = list(selected["effects"])
        self._drain()

    def _advance(self):
        if self._pending:
            raise RuleError("当前有必须完成的目标选择，请使用 options 和 choose")
        s = self.state
        if s.phase == "day_start":
            s.phase = "mastermind"
            self._event("day_started", f"第 {s.round} 天开始，领队为{ACTOR_NAMES[s.leader]}。")
        elif s.phase == "action_counters":
            self._resolve_counters()
            s.phase = "master_abilities"
            s.events[-1]["message"] = "行动牌结算完毕，普通牌回手，限次牌公开留置。进入剧作家能力阶段。"
        elif s.phase == "master_abilities":
            s.phase = "goodwill"
            self._event("phase_changed", "进入友好能力阶段，由当日领队选择；友好值不消耗。")
        elif s.phase == "goodwill":
            s.phase = "incident"
            self._event("phase_changed", "友好能力阶段结束，进入事件阶段。")
        elif s.phase == "incident":
            self._incident()
        elif s.phase == "day_end":
            self._event("day_ended", f"第 {s.round} 天结束。")
            if s.round == self.scenario["days"]:
                self._finish_loop()
            else:
                s.round += 1
                self.day_used.clear()
                self.public_day_used.clear()
                self._ignore_intrigue.clear()
                s.phase = "day_start"
        elif s.phase == "loop_end":
            self._new_loop()
        else:
            raise RuleError("本阶段不能直接跳过：请出牌、resolve、choose 或 guess")

    def _change(self, target, counter, amount):
        s = self.state
        before = getattr(s.characters[target], counter) if target in s.characters else s.locations[target]
        after = max(0, before + amount)
        if target in s.characters:
            setattr(s.characters[target], counter, after)
        else:
            s.locations[target] = after
        self._event("counter_changed", f"{self.name(target)}：{COUNTER_NAMES[counter]} {before} → {after}。",
                    target=target, counter=counter, before=before, after=after)
        self._counter_mutated(target, counter)

    def _kill(self, targets):
        # Snapshot simultaneous deaths (e.g. Hospital or two Serial Killers); no order bias.
        killed = []
        key_death = False
        for target in dict.fromkeys(targets):
            c = self.state.characters[target]
            if not c.alive:
                continue
            if self._has(target, "time_traveler"):
                self._event("death_prevented", f"{c.name}没有死亡。", target=target)
            elif self.guards[target]:
                self.guards[target] -= 1
                self._event("guard_spent", f"{c.name}的一个护卫标记被移除，替代这次死亡。", target=target)
            else:
                key_death |= self._has(target, "key")
                killed.append(target)
        for target in killed:
            self.state.characters[target].alive = False
            self._event("character_died", f"{self.name(target)}死亡；尸体留在原地，计数物保留。", target=target)
        for target in killed:
            partner = {"lover": "loved", "loved": "lover"}.get(self.roles[target])
            if partner:
                for c in self._living():
                    if self.roles[c.id] == partner:
                        self._change(c.id, "paranoia", 6)
        if key_death:
            self.loss_reasons.append("关键人物（或持有该能力的因子）死亡")
            self._finish_loop(forced=True)

    def _reveal_role(self, target):
        self.known_roles[target] = {"role": self.roles[target], "loop": self.state.loop, "day": self.state.round}
        self._event("role_revealed", f"公开信息：{self.name(target)}的身份为{ROLE_NAMES[self.roles[target]]}。",
                    character=target, role=self.roles[target])

    def _public_board(self):
        return {"characters": {c.id: asdict(c) for c in self.state.characters.values()},
                "locations": dict(self.state.locations), "guards": dict(self.guards)}

    def _drain(self):
        while self._queue and self.state.phase not in ("loop_end", "final_guess", "game_over"):
            effect = self._queue.pop(0)
            kind = effect["kind"]
            if kind == "choice":
                if effect["options"]:
                    self._pending = effect
                    self.state.phase = "decision"
                    return
                self._event("no_effect", "没有可作用的目标，这部分效果未产生变化。")
            elif kind == "counter":
                self._change(effect["target"], effect["counter"], effect["amount"])
            elif kind == "kill":
                self._kill([effect["target"]])
            elif kind == "kill_many":
                self._kill(effect["targets"])
            elif kind == "heroes_die":
                if self.protected:
                    self._event("heroes_protected", "主人公的死亡被本轮保护效果阻止。")
                else:
                    self._event("heroes_died", "主人公死亡。")
                    self._incident_effect = True
                    self.loss_reasons.append("主人公死亡")
                    self._finish_loop(forced=True)
            elif kind == "lose":
                self.loss_reasons.append("时间旅行者日末能力")
                self._finish_loop(forced=True)
            elif kind == "move":
                c = self.state.characters[effect["target"]]
                destination = effect["location"]
                if destination not in c.forbidden:
                    c.location = destination
                    self._event("character_moved", f"{c.name}移动到{LOCATIONS[destination]}。", target=c.id, location=destination)
                else:
                    self._event("movement_blocked", f"{c.name}未能移动到禁行区域。")
            elif kind == "missing_intrigue":
                self._change(self.state.characters[effect["target"]].location, "intrigue", 1)
            elif kind == "reveal":
                self._reveal_role(effect["target"])
            elif kind == "revive":
                c = self.state.characters[effect["target"]]
                c.alive = True
                self._event("revived", f"{c.name}在原位置复活，保留计数物。", target=c.id)
                self._counter_mutated(c.id, "paranoia")
            elif kind == "guard":
                self.guards[effect["target"]] += 1
                self._event("guard_added", f"{self.name(effect['target'])}获得一个护卫标记。")
            elif kind == "release":
                self.state.characters["patient"].forbidden = ()
                self._event("patient_released", "本轮住院患者的所有禁行区域被取消。")
            elif kind == "protect":
                self.protected = True
                self._event("heroes_protected", "本轮主人公不会死亡（不阻止其他失败条件）。")
            elif kind == "recover":
                actor, card = effect["actor"], effect["card"]
                self.state.discarded[actor].remove(card)
                self.state.hands[actor].append(card)
                self._event("card_recovered", f"{ACTOR_NAMES[actor]}收回{deck(actor)[card].name}。")
            elif kind == "culprit":
                incident = next(i for i in self.scenario["incidents"] if i["day"] == effect["day"])
                self.known_culprits[str(effect["day"])] = incident["culprit"]
                self._event("culprit_revealed", f"公开信息：第 {effect['day']} 天事件的当事人为{self.name(incident['culprit'])}。")
            elif kind == "informer":
                choices = [option(f"公开规则 X：{PLOTS[p][0]}", [op("plot_reveal", plot=p)])
                           for p in self.scenario["subplots"] if p != effect["excluded"]]
                self._queue.insert(0, op("choice", prompt="选择公开的规则 X", options=choices))
            elif kind == "plot_reveal":
                if effect["plot"] not in self.known_plots:
                    self.known_plots.append(effect["plot"])
                self._event("plot_revealed", f"公开信息：本剧本包含规则 X「{PLOTS[effect['plot']][0]}」。")
            elif kind == "transfer":
                a, b, counter = effect["source"], effect["target"], effect["counter"]
                if counter == "guard":
                    self.guards[a] -= 1
                    self.guards[b] += 1
                    self._event("guard_moved", f"一个护卫标记从{self.name(a)}移至{self.name(b)}。")
                else:
                    self._change(a, counter, -1)
                    self._change(b, counter, 1)
            elif kind == "ignore_intrigue":
                self._ignore_intrigue.add(effect["location"])  # private; announce only the resulting counters
            elif kind == "incident_done":
                self._record_incident_end()
            elif kind == "night":
                self._begin_night()
            else:
                raise RuleError("不支持的内部效果；停止结算")
        if not self._pending and self.state.phase not in ("loop_end", "final_guess", "game_over"):
            self.state.phase = self._return_phase

    def _incident(self):
        incident = next((i for i in self.scenario["incidents"] if i["day"] == self.state.round), None)
        if incident is None:
            self._event("no_incident", "今日没有预定事件。")
            self._begin_night()
            return
        culprit = self.state.characters[incident["culprit"]]
        kind = incident["kind"]
        happened = culprit.alive and culprit.paranoia >= CHARACTERS[culprit.id].limit
        record = {"day": self.state.round, "kind": kind, "happened": happened, "effective": False}
        self.incident_records.append(record)
        self._event("incident_status", f"第 {self.state.round} 天「{INCIDENT_NAMES[kind]}」："
                    + ("发生。" if happened else "未发生。"), incident=kind, happened=happened)
        if not happened:
            self._begin_night()
            return
        self._incident_before = self._public_board()
        self._incident_effect = False
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
                       for c in living if c.location == culprit.location for counter in COUNTER_NAMES]
        if kind in ("murder", "faraway", "missing", "unease", "spreading", "butterfly"):
            effects = [op("choice", prompt=f"结算{INCIDENT_NAMES[kind]}：选择合法目标", options=choices)]
        self._queue = effects + [op("incident_done"), op("night")]
        self._return_phase = "day_end"
        self._drain()

    def _record_incident_end(self):
        if self._incident_before is not None:
            changed = self._incident_effect or self._incident_before != self._public_board()
            self.incident_records[-1]["effective"] = changed
            self._event("incident_ended", "事件结算完成。" if changed else "事件已经发生，但未产生效果。", effective=changed)
            self._incident_before = None

    def _begin_night(self):
        s = self.state
        s.leader = PROTAGONISTS[(PROTAGONISTS.index(s.leader) + 1) % 3]
        self._event("leader_changed", f"领队轮换为{ACTOR_NAMES[s.leader]}。")
        s.phase = "day_end"
        self._event("phase_changed", "进入日末结算：先结算强制效果，再由剧作家选择可选效果。")
        victims = []
        for c in self._living():
            if self._has(c.id, "serial"):
                others = [t.id for t in self._living() if t.id != c.id and t.location == c.location]
                if len(others) == 1:
                    victims += others
        self._kill(victims)

    def _finish_loop(self, forced=False):
        s = self.state
        self._record_incident_end()
        loss = forced
        for c in s.characters.values():
            if self.roles[c.id] == "friend" and not c.alive:
                self._reveal_role(c.id)
                loss = True
                self.loss_reasons.append("亲友死亡")
        main = self.scenario["main_plot"]
        plot_loss = ((main == "protect" and s.locations["school"] >= 2) or
                     (main == "sealed" and s.locations["shrine"] >= 2) or
                     (main == "sign" and any(c.intrigue >= 2 and self.roles[c.id] == "key" for c in s.characters.values())) or
                     (main == "change" and any(r["kind"] == "butterfly" and r["happened"] for r in self.incident_records)) or
                     (main in ("avenger", "bomb") and any(s.locations[CHARACTERS[c.id].start] >= 2
                        for c in s.characters.values() if self.roles[c.id] == ("brain" if main == "avenger" else "witch"))))
        if plot_loss:
            self.loss_reasons.append("规则 Y 失败条件")
        loss |= plot_loss
        self._queue, self._pending, self._request = [], None, None
        self._previous_goodwill = {c.id for c in s.characters.values() if c.goodwill > 0}
        if not loss:
            self._win("protagonists", "本轮全部日期已结束，未触发失败条件。主人公获胜！")
        else:
            self._event("loop_lost", f"第 {s.loop} 轮回失败。", remaining=self.scenario["loops"] - s.loop)
            if s.loop < self.scenario["loops"]:
                s.phase = "loop_end"
                self._event("loop_waiting", f"还剩 {self.scenario['loops'] - s.loop} 轮。可自由讨论，确认后开始下一轮。")
            elif self.module == "BTX":
                self._start_final_guess()
            else:
                self._win("mastermind", "FS 没有最终猜测；轮回已耗尽，剧作家获胜。")

    def _restore_board(self):
        old = self.state
        self.state = State(characters=deepcopy(self._initial), leader=old.leader,
                           loop=old.loop, events=old.events)
        self.roles = dict(self.scenario["cast"])
        self.guards = dict.fromkeys(self.roles, 0)
        self.protected = False
        self.day_used.clear()
        self.loop_used.clear()
        self.public_day_used.clear()
        self.public_loop_used.clear()
        self._ignore_intrigue.clear()
        self.incident_records = []

    def _new_loop(self):
        self._restore_board()
        s = self.state
        s.loop += 1
        s.phase = "day_start"
        self._event("loop_started", f"第 {s.loop} 轮回开始：位置、存活、计数物、手牌、护卫及本轮效果已重置；历史日志和已公开信息保留。")
        if "threads" in self.scenario["subplots"]:
            for cid in self.roles:
                if cid in self._previous_goodwill:
                    self._change(cid, "paranoia", 2)
        for cid, role in self.roles.items():
            if role == "friend" and self.known_roles.get(cid, {}).get("role") == "friend":
                self._change(cid, "goodwill", 1)

    def _start_final_guess(self):
        final_incidents = self.incident_records
        self._restore_board()
        self.incident_records = final_incidents  # Keep the last loop's public event results readable.
        self._queue, self._pending, self._request = [], None, None
        self.state.phase = "final_guess"
        self._guess_remaining = list(self.roles)
        self._event("final_guess_started", "进入最终猜测：棋盘还原，身份恢复剧本初始分配。领队逐个声明角色身份，全部正确才获胜，答错即失败。")

    def _guess(self, cid, role):
        if self.state.phase != "final_guess" or cid not in self._guess_remaining or role not in ROLE_NAMES:
            raise RuleError("当前不能猜测这个角色或身份；使用 rules 查看身份 ID")
        correct = role == self.scenario["cast"][cid]
        self._event("guess_result", f"最终猜测：{self.name(cid)}是{ROLE_NAMES[role]}——{'正确' if correct else '错误'}。", correct=correct)
        if not correct:
            self._win("mastermind", "最终猜测失败，剧作家获胜。")
        else:
            self._reveal_role(cid)
            self._guess_remaining.remove(cid)
            if not self._guess_remaining:
                self._win("protagonists", "所有身份猜测正确，主人公获胜！")

    def _win(self, winner, message):
        self.winner = winner
        self.state.phase = "game_over"
        self._queue, self._pending, self._request = [], None, None
        self._event("game_ended", message, winner=winner)

    def view(self, viewer="spectator"):
        result = super().view(viewer)
        for cid, char in result["characters"].items():
            definition = CHARACTERS[cid]
            char.update(paranoia_limit=definition.limit, traits=[TRAIT_NAMES[t] for t in definition.traits],
                        guard=self.guards[cid], abilities=[asdict(a) for a in definition.abilities],
                        passive=definition.passive, initial_location=definition.start)
        result.update(title=self.scenario["title"], days=self.scenario["days"], loops=self.scenario["loops"],
                      table_talk=self.scenario["table_talk"], controller=self.controller, winner=self.winner,
                      known_roles=deepcopy(self.known_roles), known_culprits=dict(self.known_culprits),
                      known_plots=list(self.known_plots), protected=self.protected,
                      ability_day_used=sorted(self.public_day_used),
                      ability_loop_used=sorted(self.public_loop_used),
                      schedule=[{"day": i["day"], "kind": i["kind"]} for i in self.scenario["incidents"]],
                      incidents=deepcopy(self.incident_records), guess_remaining=list(self._guess_remaining))
        if viewer == "m":
            result["secret"] = {"roles": dict(self.roles), "initial_roles": dict(self.scenario["cast"]),
                                "main_plot": self.scenario["main_plot"], "subplots": list(self.scenario["subplots"]),
                                "incidents": deepcopy(self.scenario["incidents"]), "loss_reasons": list(self.loss_reasons),
                                "ability_day_used": sorted(self.day_used), "ability_loop_used": sorted(self.loop_used)}
        return result

    def save(self, path):
        # Local trusted replay file contains secrets. Exclusive create prevents overwrite.
        with Path(path).open("x", encoding="utf-8") as stream:
            json.dump({"version": 1, "scenario": self.scenario, "commands": self.history}, stream, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if (not isinstance(data, dict) or set(data) != {"version", "scenario", "commands"}
                or type(data["version"]) is not int or data["version"] != 1 or not isinstance(data["commands"], list)):
            raise RuleError("无效或不支持的存档")
        game = cls(data["scenario"])
        for command in data["commands"]:
            if not isinstance(command, dict) or "actor" not in command or "action" not in command:
                raise RuleError("存档包含非法命令")
            command = dict(command)
            game.dispatch(command.pop("actor"), command.pop("action"), **command)
        return game
