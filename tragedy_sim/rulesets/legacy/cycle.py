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

def _begin_night(self):
    s = self.state
    s.leader = PROTAGONISTS[(PROTAGONISTS.index(s.leader) + 1) % 3]
    self._event("leader_changed", f"领队轮换为{ACTOR_NAMES[s.leader]}。",
                timing=TimingId.LEADER_CHANGE)
    s.phase = "day_end"
    self._event("phase_changed", "进入日末结算：先结算强制效果，再由剧作家选择可选效果。")
    self._start_day_end_forced()


def _start_master_abilities_forced(self):
    """Activate compulsory mastermind-phase abilities before optional ones."""
    queue = []
    if self.module == "MC" and self.ex_gauge >= 1:
        sources = [c.id for c in self._living() if self._has(c.id, "psychiatrist")]
        if sources:
            queue.append(op("mc_psychiatrist_batch", sources=sources))
    if self.module == "HSA":
        groups = []
        for c in self.state.characters.values():
            if not c.alive and self._has(c.id, "ghost"):
                targets = [target.id for target in self._living()
                           if target.location in {c.location, self._loop_initial_locations[c.id]}]
                if targets:
                    groups.append({"prompt": "鬼魂强制能力：选择不安目标", "options": [
                        option(f"{c.name}（鬼魂）：{self.name(target)}不安 +1",
                               [op("counter", target=target, counter="paranoia", amount=1)])
                        for target in targets]})
            if c.alive and self._has(c.id, "chicken") and c.paranoia >= 2:
                x, y = COORDS[c.location]
                destinations = [location for location, coords in COORDS.items()
                                if abs(x - coords[0]) + abs(y - coords[1]) == 1]
                groups.append({"prompt": "胆小鬼强制能力：选择移动目的地", "options": [
                    option(f"{c.name}（胆小鬼）：移动至{LOCATIONS[location]}",
                           [op("move", target=c.id, location=location)])
                    for location in destinations]})
        if groups:
            queue.append(op("mandatory_choice_batch", choices=groups))
    self._return_phase = "master_abilities"
    self._open_timing_window(TimingId.MASTERMIND_ABILITY, queue,
                             "core.mastermind_mandatory")


def _start_loop_placements(self):
    queue = []
    if self.module == "MC" and "henchman" in self.state.characters:
        queue.append(op(
            "choice", prompt="轮回开始：剧作家决定手下的初始区域",
            options=[option(f"手下从{LOCATIONS[location]}开始",
                            [op("set_loop_initial_location", target="henchman", location=location)])
                     for location in LOCATIONS]))
    if self.module == "HSA":
        curse_sources = []
        if self.scenario["main_plot"] == "hsa_cursed_land":
            curse_sources += [c.id for c in self.state.characters.values() if self._has(c.id, "ghost")]
        if "hsa_witch_curse" in self.scenario["subplots"]:
            curse_sources += [c.id for c in self.state.characters.values() if self._has(c.id, "witch")]
        for source in curse_sources:
            board = self._loop_initial_locations[source]
            queue.append(op("choice", prompt=f"轮回开始：是否发动{self.name(source)}的诅咒放置能力",
                            options=[option(f"在{LOCATIONS[board]}放置诅咒牌",
                                            [op("hsa_add_curse", target=board)]),
                                     option("不发动此能力", [])]))
    if self.module == "WM" and self.ex_gauge >= 1:
        queue.append(op(
            "choice", actor=self.state.leader,
            prompt="旧日魔术·感应咒文：领队选择一名角色获得 2 友好",
            options=[option(f"{c.name}友好 +2",
                            [op("counter", target=c.id, counter="goodwill", amount=2)])
                     for c in self._living()]))
    if queue:
        self._return_phase = "day_start"
        self._queue = queue
        self._drain()


def _start_day_end_forced(self):
    if self._night_forced_done:
        return
    self._night_forced_done = True
    self._return_phase = "day_end"
    curses = ([target for target, count in (*self.ex_cards.items(), *self.board_ex.items())
               for _ in range(count)] if self.module == "HSA" else [])
    queue = ([op("hsa_curse_batch", remaining=curses)] if curses else [])
    if self.module == "AHR" and self._ahr_world_shift_pending:
        self._ahr_world_shift_pending = False
        queue.insert(0, op("ex_gauge", amount=1))
    queue.append(op("next_day_end_mandatory"))
    self._open_timing_window(TimingId.DAY_END, queue, "core.day_end_mandatory")


def _queue_day_end_mandatory_batch(self):
    """Activate every mandatory effect on one snapshot, then resolve the batch."""
    living = self._living()
    if (self.module == "LL" and "ll_true_monster" in self.scenario["subplots"]
            and len(self._ll_dead_once) >= 5 and self._ll_seat_for_secret("A")):
        self._win(f"traitor:{self._ll_seat_for_secret('A')}",
                  "主人公 A 达成真正的怪物特殊胜利条件。")
        return
    victims = []
    target_choices = []
    loss_reasons = []
    ex_gain = 0
    for c in living:
        others = [target for target in living if target.id != c.id and target.location == c.location]
        serial_key = f"mandatory:serial:{c.id}"
        if self._has(c.id, "serial") and serial_key not in self.day_used and len(others) == 1:
            self.day_used.add(serial_key)
            victims.append(others[0].id)
        poison_key = f"mandatory:poisoner:{c.id}"
        if (self._has(c.id, "poisoner") and self.ex_gauge >= 2
                and self._available_key(poison_key, True)):
            self._mark(poison_key, True)
            poison_targets = [target.id for target in living if target.location == c.location]
            target_choices.append({
                "prompt": "投毒者强制能力已触发：选择同区域一名角色死亡",
                "options": [option(f"{c.name}（投毒者·强制）：使{self.name(target)}死亡",
                                   [op("mandatory_poison_mark", source=c.id, target=target)])
                            for target in poison_targets],
            })
        if self._has(c.id, "poisoner") and self.ex_gauge >= 4:
            loss_reasons.append("投毒者使主人公死亡")
        witness_key = f"mandatory:witness:{c.id}"
        if (self._has(c.id, "witness") and c.paranoia >= 4
                and witness_key not in self.day_used):
            self.day_used.add(witness_key)
            victims.append(c.id)
            ex_gain += 1

    if self.module == "HSA" and "zombie:kill" not in self.day_used:
        zombie_options = []
        for board in LOCATIONS:
            zombies = [c for c in self.state.characters.values()
                       if c.location == board and self._has(c.id, "zombie")]
            non_zombies = [c for c in living
                           if c.location == board and not self._has(c.id, "zombie")]
            if len(zombies) > len(non_zombies) and non_zombies:
                zombie_options += [option(
                    f"丧尸强制能力：使{target.name}死亡",
                    [op("mandatory_poison_mark", source="zombie", target=target.id)])
                    for target in non_zombies]
        if zombie_options:
            self.day_used.add("zombie:kill")
            target_choices.append({"prompt": "丧尸强制能力已触发：选择一名角色死亡",
                                   "options": zombie_options})

    if self.module == "HSA" and self._hsa_frenzied_night_lethal:
        loss_reasons.append("疯狂之夜使主人公死亡")
    if self.module == "WM" and self.ex_gauge >= 4:
        loss_reasons.append("旧日魔术·发狂使主人公死亡")
    if self.module == "LL":
        for cid, known in self.known_roles.items():
            c = self.state.characters[cid]
            if (known["role"] == "secret_key" and (c.hope >= 1 or c.despair >= 2)
                    and self.state.round == self.scenario["days"]):
                loss_reasons.append("公开的秘钥在最终日使主人公死亡")

    if not victims and not target_choices and not loss_reasons:
        return
    self._mandatory_victims.extend(victims)
    follow = [op("resolve_mandatory_deaths")]
    if ex_gain:
        follow.append(op("ex_gauge", amount=ex_gain))
    if loss_reasons:
        follow.append(op("loop_loss", reason="；".join(loss_reasons)))
    follow.append(op("next_day_end_mandatory"))
    choice_batch = [op("mandatory_choice_batch", choices=target_choices)] if target_choices else []
    self._queue = choice_batch + follow + self._queue


def _finish_loop(self, forced=False):
    self._record_incident_end()
    self._at_loop_end = True
    try:
        self._resolve_loop_end(forced)
    finally:
        self._at_loop_end = False


def _resolve_loop_end(self, forced=False):
    s = self.state
    loss = forced
    for c in s.characters.values():
        if self.roles[c.id] == "friend" and not c.alive:
            self._reveal_role(c.id)
            loss = True
            self.loss_reasons.append("亲友死亡")
    main = self.scenario["main_plot"]
    if self.module == "WM" and self._wm_replacement_active:
        main = self.scenario["wm_replacement_plot"]
    plot_loss = ((main == "protect" and s.locations["school"] >= 2) or
                 (main == "sealed" and s.locations["shrine"] >= 2) or
                 (main == "mz_secret_record"
                  and bool(self._announced_roles & {"brain", "factor", "magician"})) or
                 (main == "mz_battle" and any(
                     self.roles[c.id] == "ninja" and c.intrigue >= 2
                     for c in s.characters.values())) or
                 (main == "sign" and any(c.intrigue >= 2 and self.roles[c.id] == "key" for c in s.characters.values())) or
                 (main == "change" and any(r["kind"] == "butterfly" and r["happened"] for r in self.incident_records)) or
                 (main == "mc_event_web" and self.ex_gauge >= 3) or
                 (main == "mc_tightrope" and self.ex_gauge <= 1) or
                 (main == "mc_dark_school"
                  and s.locations["school"] >= s.loop - 1) or
                 ("mc_gunpowder" in self.scenario["subplots"]
                  and sum(c.intrigue for c in self._living()) >= 12) or
                 ("mz_death_show" in self.scenario["subplots"]
                  and len(self._living()) <= 6) or
                 (self.module == "WM" and self._wm_plot_loss(main)) or
                 (self.module == "AHR" and (
                     (main == "ahr_closed_future" and self.ex_gauge % 2 == 0)
                     or (main == "ahr_legendary_killer"
                         and len(self.state.characters) - len(self._living()) >= min(s.loop, 3))
                     or (main == "ahr_fusion" and any(
                         record["kind"] in ("will", "lost_property") and record["happened"]
                         for record in self.incident_records))
                     or (main == "ahr_illusory_world" and any(
                         self.roles[c.id] == "obsessive"
                         and self._count(c, "intrigue") + self.ex_gauge >= 3
                         for c in self.state.characters.values())))) or
                 (self.module == "LL" and (
                     (main == "ll_sealed_end" and
                      s.locations["shrine"] + sum(
                          c.hope + c.despair for c in s.characters.values()
                          if c.location == "shrine") >= 2)
                     or (main == "ll_treacherous_world" and any(
                         self.roles[c.id] == "key" and self._count(c, "intrigue") >= 2
                         for c in s.characters.values()))
                     or (main == "ll_malicious_script" and (
                         any(record["kind"] in ("will", "executor") and record["happened"]
                             for record in self.incident_records)
                         or (s.loop == self.scenario["loops"] and any(
                             self.roles[c.id] == "watcher"
                             and sum(getattr(c, counter) for counter in COUNTER_NAMES) <= 1
                             for c in s.characters.values()))))
                     or (main == "ll_bomb_z" and any(
                         self.roles[c.id] == "witch"
                         and s.locations[self._loop_initial_locations[c.id]] >= 2
                         for c in s.characters.values())))) or
                 (main in ("avenger", "bomb") and any(s.locations[CHARACTERS[c.id].start] >= 2
                    for c in s.characters.values() if self.roles[c.id] == ("brain" if main == "avenger" else "witch"))))
    if plot_loss:
        self.loss_reasons.append("规则 Y 失败条件")
    loss |= plot_loss
    if self.module == "WM" and any(
            self.roles[c.id] == "wizard" and not c.alive for c in s.characters.values()):
        loss = True
        self.loss_reasons.append("巫师死亡")
    if self.module == "WM" and self.ex_gauge >= 2 and self.scenario["subplots"][0] not in self.known_plots:
        plot = self.scenario["subplots"][0]
        self.known_plots.append(plot)
        self._event("plot_revealed", f"旧日魔术·先祖记忆：公开规则 X「{PLOTS[plot][0]}」。")
    if self.module == "AHR" and any(
            self.roles[c.id] == "alice" for c in s.characters.values()) and self.ex_gauge % 2:
        loss = True
        self.loss_reasons.append("爱丽丝位于里世界")
    self._queue, self._pending, self._request = [], None, None
    self._decision_actor = None
    self._decision_public_phase = None
    self._previous_dead = {c.id for c in s.characters.values() if not c.alive}
    self._previous_ex_gauge = self.ex_gauge
    self._previous_goodwill = {c.id for c in s.characters.values() if c.goodwill > 0}
    self._previous_fragment_dead = {c.id for c in s.characters.values()
                                    if self.roles[c.id] == "fragment" and not c.alive}
    self._previous_fragment_friendly = {c.id for c in s.characters.values()
                                        if self.roles[c.id] == "fragment" and c.alive
                                        and c.goodwill >= 2}
    if not loss:
        self._win("protagonists", "本轮全部日期已结束，未触发失败条件。主人公获胜！")
    else:
        self._event("loop_lost", f"第 {s.loop} 轮回失败。", remaining=self.scenario["loops"] - s.loop)
        if self.module == "WM" and self.ex_gauge >= 4:
            self._start_final_guess()
        elif s.loop < self.scenario["loops"]:
            s.phase = "loop_end"
            self._event("loop_waiting", f"还剩 {self.scenario['loops'] - s.loop} 轮。可自由讨论，确认后开始下一轮。")
        elif MODULES[self.module].final_guess:
            self._start_final_guess()
        else:
            self._win("mastermind", f"{self.module} 没有最终猜测；轮回已耗尽，剧作家获胜。")


def _restore_board(self, *, apply_loop_rules=False):
    old = self.state
    self.state = State(characters=deepcopy(self._initial), leader=old.leader,
                       loop=old.loop, events=old.events)
    self.state.hands = {actor: list(self._deck(actor)) for actor in ACTORS}
    self.roles = dict(self.scenario["cast"])
    if apply_loop_rules:
        self._apply_current_roles()
    self.guards = dict.fromkeys(self.roles, 0)
    self.protected = False
    self.day_used.clear()
    self.loop_used.clear()
    self.public_day_used.clear()
    self.public_loop_used.clear()
    self._ignore_intrigue.clear()
    self._ignored_placement_indexes.clear()
    self._mandatory_victims.clear()
    self.mastermind_plays = 3
    self.protagonist_order = self._protagonists_from(self.state.leader)
    self._night_forced_done = False
    self._fake_incident_active = False
    self.ex_gauge = 0
    if self.module == "AHR":
        for actor in PROTAGONISTS:
            self.state.hands[actor].remove("ahr_h1")
        if old.loop >= 1:
            self.state.hands["m"].remove("ahr_d1")
        self._ahr_world_shift_pending = False
    if self.module == "LL":
        self.state.hands["m"].remove("ahr_d1")
        for actor in PROTAGONISTS:
            self.state.hands[actor].remove("ahr_h1")
        self._ll_restricted_day = None
    self._movement_locks.clear()
    self._sealed_boards.clear()
    self._prevented_incident_culprits.clear()
    self._loop_initial_locations = {cid: CHARACTERS[cid].start for cid in self.roles}
    if self.module == "MC":
        self.ex_cards = dict.fromkeys(self.ex_cards, 0)
    if self.module == "HSA":
        self.ex_cards = dict.fromkeys(self.ex_cards, 0)
        self.board_ex = dict.fromkeys(self.board_ex, 0)
        self._hsa_monster_uses = 0
        self._hsa_frenzied_night = False
        self._hsa_frenzied_night_lethal = False
    self._announced_roles.clear()
    self.incident_records = []


def _new_loop(self):
    wm_ex = self.ex_gauge
    self._restore_board(apply_loop_rules=True)
    if self.module == "WM":
        self.ex_gauge = wm_ex
        self._wm_loop_start_ex = wm_ex
        self._wm_replacement_active = (wm_ex >= 2 and "wm_mad_truth" in self.scenario["subplots"])
        self._wm_dagon_active = False
    s = self.state
    s.loop += 1
    s.phase = "day_start"
    self._event("loop_started", f"第 {s.loop} 轮回开始：位置、存活、计数物、手牌、护卫及本轮效果已重置；历史日志和已公开信息保留。",
                timing=TimingId.LOOP_START)
    if self.module == "AHR":
        give_despair = bool(getattr(self, "_previous_fragment_dead", set()))
        give_despair |= ("ahr_beyond_worldline" in self.scenario["subplots"] and s.loop % 2 == 0)
        give_hope = bool(getattr(self, "_previous_fragment_friendly", set())) or self._ahr_will_pending
        give_hope |= ("ahr_beyond_worldline" in self.scenario["subplots"]
                      and s.loop == self.scenario["loops"])
        if give_despair and "ahr_d1" not in self.state.hands["m"]:
            self.state.hands["m"].append("ahr_d1")
            self._event("special_card_gained", "剧作家获得「绝望 +1」。")
        if give_hope:
            for actor in PROTAGONISTS:
                if "ahr_h1" not in self.state.hands[actor]:
                    self.state.hands[actor].append("ahr_h1")
            self._event("special_card_gained", "三位主人公各获得一张「希望 +1」。")
        self._ahr_will_pending = False
    if self.module == "LL":
        give_despair = bool(getattr(self, "_previous_fragment_dead", set()))
        give_despair |= ("ll_beyond_worldline" in self.scenario["subplots"] and s.loop % 2 == 0)
        give_hope = bool(getattr(self, "_previous_fragment_friendly", set())) or self._ll_will_pending
        give_hope |= ("ll_beyond_worldline" in self.scenario["subplots"]
                      and s.loop == self.scenario["loops"])
        if give_despair:
            self.state.hands["m"].append("ahr_d1")
            self._event("special_card_gained", "剧作家获得「绝望 +1」。")
        if give_hope:
            for actor in PROTAGONISTS:
                self.state.hands[actor].append("ahr_h1")
            self._event("special_card_gained", "三位主人公各获得一张「希望 +1」。")
        self._ll_will_pending = False
    if ("mc_isolation" in self.scenario["subplots"]
            and self._previous_ex_gauge is not None and self._previous_ex_gauge <= 2):
        self._change_ex_gauge(1)
    if "threads" in self.scenario["subplots"]:
        for cid in self.roles:
            if cid in self._previous_goodwill:
                self._change(cid, "paranoia", 2)
    for cid, role in self.scenario["cast"].items():
        if role == "friend" and self.known_roles.get(cid, {}).get("role") == "friend":
            self._change(cid, "goodwill", 1)
    if (self.module == "MZ" and self._previous_dead
            and (self.scenario["main_plot"] in ("mz_approaching", "mz_causal")
                 or "mz_gods_dice" in self.scenario["subplots"])):
        self._return_phase = "day_start"
        self._queue = [op("choice", prompt="轮回开始：选择一名上轮死亡角色放置 Ex 牌",
                          options=[option(f"{self.name(cid)}获得一张 Ex 牌",
                                          [op("place_ex", target=cid)])
                                   for cid in self._previous_dead])]
        self._drain()
    self._start_loop_placements()


def _start_final_guess(self):
    final_incidents = self.incident_records
    # Final deduction uses the restored initial board; Ex history remains in
    # the log/decision records, but no Ex card or transformed role remains.
    self.ex_cards = dict.fromkeys(self.ex_cards, 0)
    self._restore_board()
    self.incident_records = final_incidents  # Keep the last loop's public event results readable.
    self._queue, self._pending, self._request = [], None, None
    self._decision_public_phase = None
    self.state.phase = "final_guess"
    self._guess_remaining = ([f"{cid}@{side}" for cid in self.roles
                              for side in ("surface", "hidden")]
                             if self.module == "AHR" else list(self.roles))
    detail = "；AHR 必须分别猜中每名角色的表、里身份" if self.module == "AHR" else ""
    self._event("final_guess_started", "进入最终猜测：棋盘还原，身份恢复剧本初始分配。"
                f"领队逐个声明角色身份，全部正确才获胜，答错即失败{detail}。")
    if self.module == "LL":
        self._return_phase = "final_guess"
        self.state.phase = "decision"
        self._queue = [op("ll_declare_traitor")]
        self._drain()


def _guess(self, cid, role):
    if self.state.phase != "final_guess" or cid not in self._guess_remaining or role not in ROLE_NAMES:
        raise RuleError("当前不能猜测这个角色或身份；使用 rules 查看身份 ID")
    if self.module == "AHR":
        character, side = cid.rsplit("@", 1)
        source = self.scenario["cast"] if side == "surface" else self.scenario["hidden_cast"]
        correct = role == source[character]
    else:
        character = cid
        correct = role == self.scenario["cast"][cid]
    self._event("guess_result", f"最终猜测：{self.name(cid)}是{ROLE_NAMES[role]}——{'正确' if correct else '错误'}。", correct=correct)
    if not correct:
        self._win("mastermind", "最终猜测失败，剧作家获胜。")
    else:
        if self.module != "AHR":
            self._reveal_role(cid, truthful=True)
        self._guess_remaining.remove(cid)
        if not self._guess_remaining:
            self._win("protagonists", "所有身份猜测正确，主人公获胜！")


OPERATIONS = {
    '_begin_night': _begin_night,
    '_start_master_abilities_forced': _start_master_abilities_forced,
    '_start_loop_placements': _start_loop_placements,
    '_start_day_end_forced': _start_day_end_forced,
    '_queue_day_end_mandatory_batch': _queue_day_end_mandatory_batch,
    '_finish_loop': _finish_loop,
    '_resolve_loop_end': _resolve_loop_end,
    '_restore_board': _restore_board,
    '_new_loop': _new_loop,
    '_start_final_guess': _start_final_guess,
    '_guess': _guess,
}
