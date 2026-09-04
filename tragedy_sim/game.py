"""Complete hotseat match flow. Effects are deterministic; choices belong to humans.

All logs are public. Secret roles, requirements and offered mastermind options are
kept outside the public projection. dispatch() is atomic and is also the replay API.
"""

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

from .cards import ACTORS, ACTOR_NAMES, COORDS, COUNTER_NAMES, LOCATIONS, PROTAGONISTS, deck
from .catalog import CHARACTERS, INCIDENT_NAMES, MODULES, MODULE_PLOTS, PLOTS, REFUSAL, ROLE_NAMES, TRAIT_NAMES
from .engine import ActionGame, Character, RuleError, State
from .flow import MATCH_FLOW
from .model import DecisionRecord, PhaseCursor, ResolutionStep, SimulationResult
from .scenario import example_scenario, validate_scenario
from .transcript import describe_decision


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
        self.ex_cards = dict.fromkeys(self.roles, 0)
        self._apply_current_roles()
        self.known_roles = {}
        self.role_announcements = []
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
        self.decisions = []
        self.loss_reasons = []  # private diagnostic information
        self._queue = []
        self._pending = None
        self._decision_actor = None
        self._decision_public_phase = None
        self._return_phase = None
        self._request = None
        self._ignore_intrigue = set()
        self._previous_goodwill = set()
        self._incident_before = None
        self._incident_effect = False
        self._guess_remaining = []
        self._permanent_dead = set()
        self._returner_carry = {}
        self._trickster_targets = set()
        self._mandatory_victims = []
        self._previous_dead = set()
        self._occurred_incidents = []
        self._announced_roles = set()
        self._fake_incident_active = False
        self._distort_next_day = False
        self._night_forced_done = False
        self.state.phase = "day_start"
        self._event("loop_started", f"第 1 轮回开始，共 {self.scenario['loops']} 轮，每轮 {self.scenario['days']} 天。")

    @property
    def controller(self):
        if self.state.phase == "decision" and self._decision_actor:
            return self._decision_actor
        return MATCH_FLOW.controller(self.state.phase, leader=self.state.leader, next_actor=self.next_actor)

    def name(self, target):
        return self.state.characters[target].name if target in self.state.characters else LOCATIONS.get(target, target)

    def _event(self, kind, message, **data):
        super()._event(kind, message, **data)
        self.state.events[-1]["phase"] = self.state.phase

    def dispatch(self, actor, action, **args):
        if actor not in ACTORS:
            raise RuleError("未知玩家、命令或参数")
        try:
            MATCH_FLOW.validate_command(self.state.phase, action, args)
        except ValueError as exc:
            raise RuleError(str(exc)) from exc
        if action == "final":
            if (not MODULES[self.module].early_final_guess or self.state.phase != "loop_end"
                    or actor != self.state.leader):
                raise RuleError("当前规则集或阶段不允许领队提前进入最终猜测")
        elif actor != self.controller:
            raise RuleError(f"当前需要 {ACTOR_NAMES.get(self.controller, '无人')} 操作")
        snapshot = deepcopy(self.__dict__)
        before = self.phase_cursor
        event_start = len(self.state.events)
        description = describe_decision(self, actor, action, args)
        try:
            if action == "play":
                self.play(actor, args["card"], args["target"])
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
        command = {"actor": actor, "action": action, **deepcopy(args)}
        self.history.append(command)
        steps = tuple(ResolutionStep.from_event(event) for event in self.state.events[event_start:])
        self.decisions.append(DecisionRecord(
            number=len(self.history), actor=actor, action=action,
            arguments=deepcopy(args), description=description,
            before=before, after=self.phase_cursor, steps=steps,
        ))

    @property
    def phase_cursor(self):
        return PhaseCursor.from_state(self.state)

    def state_key(self, viewer="spectator"):
        """Canonical information-state key for replay checks and future search."""
        projection = self.view(viewer)
        projection.pop("events", None)
        return json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def legal_actions(self, actor):
        """Enumerate complete command dictionaries without exposing other seats' secrets."""
        if actor not in ACTORS:
            raise RuleError("未知玩家")
        phase = self.state.phase
        if phase == "loop_end" and actor == self.state.leader and MODULES[self.module].early_final_guess:
            return [{"actor": actor, "action": "final"}]
        if actor != self.controller:
            return []
        if phase in ("mastermind", "protagonists"):
            view = self.view(actor)
            occupied = {p["target"] for p in view["pending"]
                        if (p["actor"] == "m") == (actor == "m")}
            targets = [target for target in (*view["characters"], *LOCATIONS)
                       if target not in occupied and
                       (target in LOCATIONS or view["characters"][target]["alive"])
                       and self._can_target_action(actor, target)]
            return [{"actor": actor, "action": "play", "card": card, "target": target}
                    for card in view["hand"] for target in targets]
        if phase in ("action_counters", "master_abilities", "goodwill", "day_end", "decision", "refusal"):
            available = self.options(actor)
            choices = [{"actor": actor, "action": "choose", "index": index}
                       for index, choice in enumerate(available, 1) if not choice.get("finish")]
            if phase not in ("decision", "refusal"):
                choices.append({"actor": actor, "action": "next"})
            return choices
        if phase == "final_guess":
            roles = {"ordinary"}
            for plot in MODULES[self.module].plots:
                roles.update(PLOTS[plot][2])
            if "hideous" in MODULES[self.module].plots:
                roles.add("curmudgeon")
            return [{"actor": actor, "action": "guess", "character": character, "role": role}
                    for character in self._guess_remaining for role in ROLE_NAMES if role in roles]
        action = "resolve" if phase == "reveal" else "next"
        if action in MATCH_FLOW.definition(phase).actions:
            return [{"actor": actor, "action": action}]
        return []

    def simulate(self, actor, action, **args):
        """Apply one action to a detached clone, leaving this world untouched."""
        successor = deepcopy(self)
        successor.dispatch(actor, action, **args)
        return SimulationResult(successor, successor.decisions[-1])

    def next_round(self):
        raise RuleError("完整对局请使用 next 按阶段推进，不能跳过结算")

    def reset_loop(self):
        raise RuleError("完整对局不能随意重置轮回")

    def _living(self):
        return [c for c in self.state.characters.values() if c.alive]

    def _can_target_action(self, actor, target):
        if target not in self.state.characters:
            return True
        if actor == "m" and self._has(target, "prophet"):
            return False
        if actor != "m" and self._fake_incident_active and self.ex_cards.get(target, 0):
            return False
        return True

    def play(self, actor, card_id, target):
        if target in self.state.characters and not self._can_target_action(actor, target):
            if actor == "m":
                raise RuleError("预言家在场时，剧作家不能向其放置行动牌")
            raise RuleError("伪造事件生效后，主人公本轮不能向有 Ex 牌的角色放置行动牌")
        super().play(actor, card_id, target)

    def _apply_current_roles(self):
        if "of_truman" in self.scenario["subplots"]:
            for cid, role in self.scenario["cast"].items():
                if role == "ordinary":
                    self.roles[cid] = "puppet"
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
        return (super()._movement_is_forbidden(target, effects)
                or ("mz_clear_mind" in self.scenario["subplots"] and "forbid_goodwill" in effects))

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
        if self.module == "OF":
            # The Returner Enemy cancels a revealed card before that card can move its target.
            self._reveal_cards()
        else:
            self._reveal_and_move()
        self._ignore_intrigue.clear()
        detail = ("行动牌已揭示。请剧作家确认行动结算中的能力，再继续结算移动和计数物。"
                  if self.module == "OF" else
                  "移动已结算。请剧作家确认行动结算中的能力，再继续结算计数物。")
        # Always pause here, not only when a relevant role exists; the public phase reveals no role.
        self._event("resolution_window", detail)

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
                key = f"returner_enemy:{c.id}"
                if self._has(c.id, "returner_enemy") and self._available_key(key, True):
                    for index, placement in enumerate(self.state.pending):
                        if placement.actor == "m" or index in self._ignored_placement_indexes:
                            continue
                        location = (self.state.characters[placement.target].location
                                    if placement.target in self.state.characters else placement.target)
                        if location == c.location:
                            card = deck(placement.actor)[placement.card]
                            result.append(option(
                                f"{c.name}（归来者·敌）：无效化{ACTOR_NAMES[placement.actor]}在"
                                f"{self.name(placement.target)}的「{card.name}」",
                                [op("ignore_card", index=index)], key=key, once=True,
                                source=c.id, ability="cancel_card"))
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
            if "of_blue_cat" in self.scenario["subplots"]:
                result += self._counter_options(None, "plot:of_blue_cat",
                                                [*LOCATIONS, *(c.id for c in self._living())],
                                                "intrigue", 1, "蓝色狸猫的阴谋（每轮一次）", True)
            if "mz_factor" in self.scenario["subplots"]:
                factor_locations = sorted({c.location for c in self._living() if self._has(c.id, "factor")})
                result += self._counter_options(None, "plot:mz_factor", factor_locations,
                                                "intrigue", 1, "X 异因子（每轮一次）", True)
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
                            if self.roles[t.id] == "key" and t.location == c.location and t.intrigue >= 2:
                                result.append(option(f"{c.name}（杀手）：使{t.name}死亡", [op("kill", target=t.id)], key=key))
                    key = f"killer:heroes:{c.id}"
                    if c.intrigue >= 4 and self._available_key(key):
                        result.append(option(f"{c.name}（杀手）：使主人公死亡", [op("heroes_die")], key=key))
                if self._has(c.id, "lover") and c.paranoia >= 3 and c.intrigue >= 1:
                    key = f"lover:{c.id}"
                    if self._available_key(key):
                        result.append(option(f"{c.name}（求爱者）：使主人公死亡",
                                             [op("heroes_die", hidden=self.module == "OF")], key=key))
                if self._has(c.id, "time_traveler") and self.state.round == self.scenario["days"] and c.goodwill <= 2:
                    key = f"time_traveler:{c.id}"
                    if self._available_key(key):
                        result.append(option(f"{c.name}（时间旅行者）：使主人公失败", [op("lose")], key=key))
                if self._has(c.id, "puppet"):
                    key = f"puppet:{c.id}"
                    if self._available_key(key):
                        for target in self._living():
                            if target.location == c.location and target.goodwill >= 4:
                                result.append(option(f"{c.name}（傀儡）：使{target.name}死亡",
                                                     [op("kill", target=target.id)], key=key))
                if self._has(c.id, "assassin") and c.intrigue >= 3:
                    key = f"assassin:{c.id}"
                    if self._available_key(key):
                        result.append(option(f"{c.name}（刺客）：使主人公死亡",
                                             [op("heroes_die", hidden=True)], key=key))
                if self._has(c.id, "terrorist"):
                    board_intrigue = self.state.locations[c.location]
                    key = f"terrorist:heroes:{c.id}"
                    if board_intrigue >= 3 and self._available_key(key):
                        result.append(option(f"{c.name}（恐怖分子）：使主人公死亡",
                                             [op("heroes_die", hidden=True)], key=key))
                    key = f"terrorist:character:{c.id}"
                    if board_intrigue >= 2 and self._available_key(key):
                        for target in self._living():
                            if target.location == c.location:
                                result.append(option(f"{c.name}（恐怖分子）：使{target.name}死亡",
                                                     [op("kill", target=target.id)], key=key))
                if self._has(c.id, "ninja"):
                    key = f"ninja:{c.id}"
                    if self._available_key(key):
                        for target in self._living():
                            if target.location == c.location and target.intrigue >= 2:
                                result.append(option(f"{c.name}（忍者）：使{target.name}死亡",
                                                     [op("kill", target=target.id)], key=key))
        elif phase == "refusal":
            request = self._request
            if request.get("already_used"):
                return [option("本日已结算此能力；公开宣布本次没有效果", refuse=True)]
            refusal = None if request["unrefusable"] else REFUSAL.get(self.roles[request["source"]])
            if (self.roles[request["source"]] == "puppet"
                    and self.state.characters[request["source"]].goodwill >= 4):
                refusal = "mandatory"
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
            self._decision_actor = None
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
            request = self._request
            self._request = None
            if selected.get("refuse"):
                self._event("ability_no_effect", "这项友好能力没有效果；次数已使用，友好不消耗。")
                self.state.phase = "goodwill"
                if self.roles[request["source"]] == "puppet":
                    self._return_phase = "goodwill"
                    self._queue = [op("puppet_refusal", target=request["source"])]
                    self._drain()
                return
            self._return_phase = "goodwill"
        else:
            self._return_phase = self.state.phase
        self._queue = list(selected["effects"])
        self._drain()

    def _advance(self):
        if self._pending:
            raise RuleError("当前有必须完成的目标或效果选择，请使用 options 和 choose")
        s = self.state
        if s.phase == "day_start":
            order = self._protagonists_from(s.leader)
            if self._distort_next_day:
                self.configure_actions(mastermind=4,
                                       protagonists=tuple(actor for actor in order if actor != s.leader))
                self._distort_next_day = False
                self._event("time_distortion_active",
                            "时空扭曲生效：剧作家放置 4 张牌；主人公合计放置 2 张，领队不能放置。")
            else:
                self.configure_actions(mastermind=3, protagonists=order)
            s.phase = "mastermind"
            self._event("day_started", f"第 {s.round} 天开始，领队为{ACTOR_NAMES[s.leader]}。")
        elif s.phase == "action_counters":
            if self.module == "OF":
                self._resolve_movements()
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
            if not self._night_forced_done:
                self._start_day_end_forced()
                if self.state.phase != "day_end" or self._pending:
                    return
                s = self.state
            self._event("day_ended", f"第 {s.round} 天结束。")
            if s.round >= self._current_loop_days():
                self._finish_loop()
            else:
                s.round += 1
                self.day_used.clear()
                self.public_day_used.clear()
                self._ignore_intrigue.clear()
                self._night_forced_done = False
                s.phase = "day_start"
        elif s.phase == "loop_end":
            self._new_loop()
        else:
            raise RuleError("本阶段不能直接跳过：请出牌、resolve、choose 或 guess")

    def _current_loop_days(self):
        return self.scenario["days"]

    def _scheduled_day(self):
        return self.state.round

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
        dying_magicians = []
        for target in dict.fromkeys(targets):
            c = self.state.characters[target]
            if not c.alive:
                continue
            if self._has(target, "time_traveler") or self._has(target, "immortal"):
                self._event("death_prevented", f"{c.name}没有死亡。", target=target)
            elif self.guards[target]:
                self.guards[target] -= 1
                self._event("guard_spent", f"{c.name}的一个护卫标记被移除，替代这次死亡。", target=target)
            else:
                key_death |= self._has(target, "key")
                if self._has(target, "magician"):
                    dying_magicians.append(target)
                killed.append(target)
        for target in killed:
            self.state.characters[target].alive = False
            if self.roles[target] == "puppet":
                self._permanent_dead.add(target)
            self._event("character_died", f"{self.name(target)}死亡；尸体留在原地，计数物保留。", target=target)
        for target in dying_magicians:
            goodwill = self.state.characters[target].goodwill
            if goodwill:
                self._change(target, "goodwill", -goodwill)
        for target in killed:
            partner = {"lover": "loved", "loved": "lover"}.get(self.roles[target])
            if partner:
                for c in self._living():
                    if self.roles[c.id] == partner:
                        self._change(c.id, "paranoia", 6)
        if key_death:
            self.loss_reasons.append("关键人物（或持有该能力的因子）死亡")
            self._finish_loop(forced=True)

    def _script_roles(self):
        roles = set()
        for plot in (self.scenario["main_plot"], *self.scenario["subplots"]):
            roles.update(PLOTS[plot][2])
        return roles

    def _publish_role(self, target, role):
        # Knowledge changes are an observable incident result even when no board
        # counter or character state changes (notably Old Fashion's Confession).
        if self._incident_before is not None:
            self._incident_effect = True
        self.known_roles[target] = {"role": role, "loop": self.state.loop, "day": self.state.round}
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

    def _public_board(self):
        return {"characters": {c.id: asdict(c) for c in self.state.characters.values()},
                "locations": dict(self.state.locations), "guards": dict(self.guards),
                "ex_cards": dict(self.ex_cards)}

    def _drain(self):
        while self._queue and self.state.phase not in ("loop_end", "final_guess", "game_over"):
            effect = self._queue.pop(0)
            kind = effect["kind"]
            if kind == "choice":
                if effect["options"]:
                    self._pending = effect
                    self._decision_actor = effect.get("actor", "m")
                    origin = self.state.phase
                    if origin in ("decision", "refusal"):
                        origin = self._return_phase
                    self._decision_public_phase = origin
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
                    if not effect.get("hidden"):
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
            elif kind == "announce_role":
                self._publish_role(effect["target"], effect["role"])
            elif kind == "add_ex":
                target = effect["target"]
                self.ex_cards[target] += 1
                self._refresh_mz_ex_roles()
                self._event("ex_added", f"{self.name(target)}获得一张 Ex 牌（现有 {self.ex_cards[target]} 张）。",
                            target=target, count=self.ex_cards[target])
            elif kind == "place_ex":
                target = effect["target"]
                sources = [cid for cid, count in self.ex_cards.items() if count]
                if sources:
                    choices = [option(f"使用未放置的 Ex 牌 → {self.name(target)}",
                                      [op("add_ex", target=target)])]
                    choices += [option(f"移动 Ex：{self.name(source)} → {self.name(target)}",
                                       [op("move_ex", source=source, target=target)])
                                for source in sources]
                    self._queue.insert(0, op("choice", prompt="选择使用新 Ex 牌或移动一张已有 Ex 牌",
                                             options=choices))
                else:
                    self._queue.insert(0, op("add_ex", target=target))
            elif kind == "move_ex":
                source, target = effect["source"], effect["target"]
                self.ex_cards[source] -= 1
                self.ex_cards[target] += 1
                self._refresh_mz_ex_roles()
                self._event("ex_moved", f"一张 Ex 牌从{self.name(source)}移至{self.name(target)}。",
                            source=source, target=target)
            elif kind == "fake_incident_active":
                self._fake_incident_active = True
                self._incident_effect = True
                self._event("action_restriction", "本轮余下时间，主人公不能在有 Ex 牌的角色上放置行动牌。")
            elif kind == "copy_mz_incident":
                copied = self._mz_incident_effects(effect["incident"], effect["culprit"])
                self._queue = copied + self._queue
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
            elif kind == "ignore_card":
                index = effect["index"]
                self._ignored_placement_indexes.add(index)
                placement = self.state.pending[index]
                self._event("card_ignored", f"{ACTOR_NAMES[placement.actor]}在{self.name(placement.target)}的"
                            f"「{deck(placement.actor)[placement.card].name}」被无效化。",
                            actor=placement.actor, card=placement.card, target=placement.target)
            elif kind == "puppet_refusal":
                target = effect["target"]
                self._kill([target])
                if not self.state.characters[target].alive:
                    self._permanent_dead.add(target)
            elif kind == "time_distortion":
                self._distort_next_day = True
                self._incident_effect = True
                self._event("time_distortion_set", "时空扭曲将在下一日的行动阶段生效。")
            elif kind == "trickster_mark":
                self._trickster_targets.add(effect["target"])
                self._mandatory_victims.append(effect["target"])
            elif kind == "mandatory_trickster_choice":
                choices = [option(f"{self.name(effect['source'])}（捣蛋鬼·强制）：使{self.name(target)}死亡",
                                  [op("trickster_mark", source=effect["source"], target=target)])
                           for target in effect["targets"] if target not in self._trickster_targets]
                if choices:
                    self._queue.insert(0, op("choice", prompt="捣蛋鬼已触发：选择一名同区域角色死亡",
                                             options=choices))
                else:
                    self._event("no_effect", "已触发的强制效果没有合法目标，未产生变化。")
            elif kind == "resolve_mandatory_deaths":
                victims, self._mandatory_victims = self._mandatory_victims, []
                self._kill(victims)
            elif kind == "next_day_end_mandatory":
                self._queue_day_end_mandatory_batch()
            elif kind == "loop_loss":
                self.loss_reasons.append(effect["reason"])
                self._finish_loop(forced=True)
            elif kind == "incident_done":
                self._record_incident_end()
            elif kind == "night":
                self._begin_night()
            else:
                raise RuleError("不支持的内部效果；停止结算")
        if not self._pending and self.state.phase not in ("loop_end", "final_guess", "game_over"):
            self.state.phase = self._return_phase
            self._decision_public_phase = None
            self._decision_actor = None

    def _incident(self):
        scheduled_day = self._scheduled_day()
        incident = next((i for i in self.scenario["incidents"] if i["day"] == scheduled_day), None)
        if incident is None:
            self._event("no_incident", "今日没有预定事件。")
            self._begin_night()
            return
        culprit = self.state.characters[incident["culprit"]]
        kind = incident["kind"]
        threshold = CHARACTERS[culprit.id].limit
        prophet_alive = any(self._has(c.id, "prophet") for c in self.state.characters.values())
        if ("mz_doom_song" in self.scenario["subplots"] and self.roles[culprit.id] == "ordinary"
                and prophet_alive):
            threshold -= 1
        prophet_blocks = any(self._has(c.id, "prophet") and c.id != culprit.id
                             and c.location == culprit.location for c in self.state.characters.values())
        forced = self._has(culprit.id, "obsessive")
        happened = culprit.alive and (forced or (not prophet_blocks and culprit.paranoia >= threshold))
        public_kind = incident.get("public_kind", kind)
        record = {"day": self.state.round, "kind": public_kind, "happened": happened, "effective": False}
        self.incident_records.append(record)
        self._event("incident_status", f"第 {self.state.round} 天「{INCIDENT_NAMES[public_kind]}」："
                    + ("发生。" if happened else "未发生。"), incident=public_kind, happened=happened)
        if not happened:
            self._begin_night()
            return
        self._incident_before = self._public_board()
        self._incident_effect = False
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
        elif kind == "time_distortion":
            effects = [op("time_distortion")]
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
                       for c in living if c.location == culprit.location for counter in COUNTER_NAMES]
        if kind in ("murder", "faraway", "missing", "unease", "spreading", "butterfly",
                    "poison_gas", "exposure"):
            effects = [op("choice", prompt=f"结算{INCIDENT_NAMES[kind]}：选择合法目标", options=choices)]
        self._queue = effects + [op("incident_done"), op("night")]
        self._return_phase = "day_end"
        self._drain()

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

    def _begin_night(self):
        s = self.state
        s.leader = PROTAGONISTS[(PROTAGONISTS.index(s.leader) + 1) % 3]
        self._event("leader_changed", f"领队轮换为{ACTOR_NAMES[s.leader]}。")
        s.phase = "day_end"
        self._event("phase_changed", "进入日末结算：先结算强制效果，再由剧作家选择可选效果。")
        self._start_day_end_forced()

    def _start_day_end_forced(self):
        if self._night_forced_done:
            return
        self._night_forced_done = True
        self._return_phase = "day_end"
        self._queue = [op("next_day_end_mandatory")]
        self._drain()

    def _queue_day_end_mandatory_batch(self):
        """Activate every mandatory effect on one snapshot, then resolve the batch."""
        living = self._living()
        victims = []
        target_choices = []
        loss_reasons = []
        for c in living:
            others = [target for target in living if target.id != c.id and target.location == c.location]
            serial_key = f"mandatory:serial:{c.id}"
            if self._has(c.id, "serial") and serial_key not in self.day_used and len(others) == 1:
                self.day_used.add(serial_key)
                victims.append(others[0].id)
            doom_key = f"mandatory:doomsday:{c.id}"
            if ("of_doomsday" in self.scenario["subplots"] and c.paranoia >= 4
                    and doom_key not in self.day_used):
                self.day_used.add(doom_key)
                victims.append(c.id)
            isolated_key = f"mandatory:trickster-alone:{c.id}"
            if (self._has(c.id, "trickster") and not others and isolated_key not in self.day_used):
                self.day_used.add(isolated_key)
                victims.append(c.id)
            trickster_key = f"trickster:{c.id}"
            if (self._has(c.id, "trickster") and len(others) >= 3
                    and self._available_key(trickster_key, True)):
                # Activation is mandatory and fixed now; only its target still
                # requires human input. A later death of the source cannot undo it.
                self._mark(trickster_key, True)
                target_choices.append(op("mandatory_trickster_choice", source=c.id,
                                         targets=[target.id for target in others]))

        grandfather_key = "mandatory:plot:of_grandfather"
        enemies = [c.id for c in living if self._has(c.id, "returner_enemy")]
        if ("of_grandfather" in self.scenario["subplots"] and grandfather_key not in self.day_used
                and enemies and any(self.roles[c.id] == "friend" and not c.alive
                                    for c in self.state.characters.values())):
            self.day_used.add(grandfather_key)
            victims.extend(enemies)

        if self.scenario["main_plot"] == "of_dream_beauty":
            brain_alive = any(self._has(c.id, "brain") for c in self.state.characters.values())
            key_ready = any(self._has(c.id, "key") and c.intrigue >= 2
                            for c in self.state.characters.values())
            if brain_alive and key_ready:
                loss_reasons.append("规则 Y 失败条件")
        if (self.scenario["main_plot"] == "of_retry"
                and self.state.round >= self._current_loop_days()):
            loss_reasons.append("规则 Y 最终日强制主人公死亡")

        if not victims and not target_choices and not loss_reasons:
            return
        self._mandatory_victims.extend(victims)
        follow = [op("resolve_mandatory_deaths")]
        if loss_reasons:
            follow.append(op("loop_loss", reason="；".join(loss_reasons)))
        follow.append(op("next_day_end_mandatory"))
        self._queue = target_choices + follow + self._queue

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
                     (main == "mz_secret_record"
                      and bool(self._announced_roles & {"brain", "factor", "magician"})) or
                     (main == "mz_battle" and any(
                         self.roles[c.id] == "ninja" and c.intrigue >= 2
                         for c in s.characters.values())) or
                     (main == "of_endless" and s.locations["shrine"] >= 2) or
                     (main == "sign" and any(c.intrigue >= 2 and self.roles[c.id] == "key" for c in s.characters.values())) or
                     (main == "change" and any(r["kind"] == "butterfly" and r["happened"] for r in self.incident_records)) or
                     (main == "of_time_patrol" and any(c.intrigue >= 2 and self.roles[c.id] == "terrorist"
                                                       for c in s.characters.values())) or
                     ("of_delorean" in self.scenario["subplots"]
                      and any(c.goodwill >= 3 and self.roles[c.id] == "loved" for c in s.characters.values())) or
                     ("mz_death_show" in self.scenario["subplots"]
                      and len(self._living()) <= 6) or
                     (main in ("avenger", "bomb") and any(s.locations[CHARACTERS[c.id].start] >= 2
                        for c in s.characters.values() if self.roles[c.id] == ("brain" if main == "avenger" else "witch"))))
        if plot_loss:
            self.loss_reasons.append("规则 Y 失败条件")
        loss |= plot_loss
        self._queue, self._pending, self._request = [], None, None
        self._decision_actor = None
        self._decision_public_phase = None
        self._previous_dead = {c.id for c in s.characters.values() if not c.alive}
        self._previous_goodwill = {c.id for c in s.characters.values() if c.goodwill > 0}
        self._returner_carry = {
            c.id: {**{counter: getattr(c, counter) for counter in COUNTER_NAMES},
                   "guard": self.guards[c.id]}
            for c in s.characters.values()
            if c.alive and c.goodwill >= 3
            and self.roles[c.id] in ("returner_enemy", "returner_friend")
        }
        if not loss:
            self._win("protagonists", "本轮全部日期已结束，未触发失败条件。主人公获胜！")
        else:
            self._event("loop_lost", f"第 {s.loop} 轮回失败。", remaining=self.scenario["loops"] - s.loop)
            if s.loop < self.scenario["loops"]:
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
        self.roles = dict(self.scenario["cast"])
        if apply_loop_rules:
            self._apply_current_roles()
            for cid in self._permanent_dead:
                self.state.characters[cid].alive = False
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
        self._distort_next_day = False
        self._night_forced_done = False
        self._fake_incident_active = False
        self._announced_roles.clear()
        self.incident_records = []

    def _new_loop(self):
        carry = deepcopy(self._returner_carry)
        self._restore_board(apply_loop_rules=True)
        s = self.state
        s.loop += 1
        s.phase = "day_start"
        self._event("loop_started", f"第 {s.loop} 轮回开始：位置、存活、计数物、手牌、护卫及本轮效果已重置；历史日志和已公开信息保留。")
        if "threads" in self.scenario["subplots"]:
            for cid in self.roles:
                if cid in self._previous_goodwill:
                    self._change(cid, "paranoia", 2)
        for cid, role in self.scenario["cast"].items():
            if role == "friend" and self.known_roles.get(cid, {}).get("role") == "friend":
                self._change(cid, "goodwill", 1)
        for cid, counters in carry.items():
            if cid in self.roles and self.roles[cid] in ("returner_enemy", "returner_friend"):
                for counter, amount in counters.items():
                    if amount:
                        if counter == "guard":
                            self.guards[cid] = amount
                            self._event("guard_inherited", f"{self.name(cid)}继承 {amount} 个护卫标记。",
                                        target=cid, amount=amount)
                        else:
                            self._change(cid, counter, amount)
        if (self.module == "MZ" and self._previous_dead
                and (self.scenario["main_plot"] in ("mz_approaching", "mz_causal")
                     or "mz_gods_dice" in self.scenario["subplots"])):
            self._return_phase = "day_start"
            self._queue = [op("choice", prompt="轮回开始：选择一名上轮死亡角色放置 Ex 牌",
                              options=[option(f"{self.name(cid)}获得一张 Ex 牌",
                                              [op("place_ex", target=cid)])
                                       for cid in self._previous_dead])]
            self._drain()

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
            self._reveal_role(cid, truthful=True)
            self._guess_remaining.remove(cid)
            if not self._guess_remaining:
                self._win("protagonists", "所有身份猜测正确，主人公获胜！")

    def _win(self, winner, message):
        self.winner = winner
        self.state.phase = "game_over"
        self._queue, self._pending, self._request = [], None, None
        self._decision_public_phase = None
        self._event("game_ended", message, winner=winner)

    def view(self, viewer="spectator"):
        result = super().view(viewer)
        # `decision` is an internal pause. Showing it publicly can reveal that
        # several hidden abilities are simultaneously applicable. Other seats
        # continue to see the surrounding public rules phase instead.
        if viewer != "m" and result["phase"] == "decision" and self._decision_public_phase:
            result["phase"] = self._decision_public_phase
        spec = MODULES[self.module]
        for cid, char in result["characters"].items():
            definition = CHARACTERS[cid]
            char.update(paranoia_limit=definition.limit, traits=[TRAIT_NAMES[t] for t in definition.traits],
                        guard=self.guards[cid], abilities=[asdict(a) for a in definition.abilities],
                        passive=definition.passive, initial_location=definition.start,
                        ex_cards=self.ex_cards.get(cid, 0))
        result.update(title=self.scenario["title"], days=self.scenario["days"], loops=self.scenario["loops"],
                      table_talk=self.scenario["table_talk"], controller=self.controller, winner=self.winner,
                      module_name=spec.name,
                      capabilities={"final_guess": spec.final_guess,
                                    "early_final_guess": spec.early_final_guess},
                      known_roles=deepcopy(self.known_roles), known_culprits=dict(self.known_culprits),
                      role_announcements=deepcopy(self.role_announcements),
                      known_plots=list(self.known_plots), protected=self.protected,
                      ability_day_used=sorted(self.public_day_used),
                      ability_loop_used=sorted(self.public_loop_used),
                      schedule=[{"day": i["day"], "kind": i.get("public_kind", i["kind"])}
                                for i in self.scenario["incidents"]],
                      incidents=deepcopy(self.incident_records), guess_remaining=list(self._guess_remaining))
        if viewer == "m":
            result["secret"] = {"roles": dict(self.roles), "initial_roles": dict(self.scenario["cast"]),
                                "main_plot": self.scenario["main_plot"], "subplots": list(self.scenario["subplots"]),
                                "incidents": deepcopy(self.scenario["incidents"]), "loss_reasons": list(self.loss_reasons),
                                "current_loop_days": self._current_loop_days(),
                                "ability_day_used": sorted(self.day_used), "ability_loop_used": sorted(self.loop_used)}
        return result

    def save(self, path):
        # Local trusted replay file contains secrets. Exclusive create prevents overwrite.
        with Path(path).open("x", encoding="utf-8") as stream:
            json.dump({"version": 1, "scenario": self.scenario, "commands": self.history}, stream, ensure_ascii=False, indent=2)

    def save_replay(self, path):
        """Export a completed match as a readable, deterministic text replay."""
        from .replay import dump
        dump(self, path)

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
