"""Complete hotseat match flow. Effects are deterministic; choices belong to humans.

All logs are public. Secret roles, requirements and offered mastermind options are
kept outside the public projection. dispatch() is atomic and is also the replay API.
"""

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

from .cards import ACTORS, ACTOR_NAMES, COORDS, COUNTER_NAMES, LOCATIONS, PROTAGONISTS, STANDARD_COUNTERS, deck
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
        if self.module == "AHR":
            for actor in PROTAGONISTS:
                self.state.hands[actor].remove("ahr_h1")
        self.roles = dict(self.scenario["cast"])
        self.ex_cards = dict.fromkeys(self.roles, 0)
        self.ex_gauge = 0
        self.board_ex = dict.fromkeys(LOCATIONS, 0)
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
        self._previous_ex_gauge = None
        self._movement_locks = {}
        self._sealed_boards = []
        self._prevented_incident_culprits = set()
        self._loop_initial_locations = {cid: CHARACTERS[cid].start for cid in self.roles}
        self._distort_next_day = False
        self._night_forced_done = False
        self._hsa_monster_uses = 0
        self._hsa_frenzied_night = False
        self._hsa_frenzied_night_lethal = False
        self._wm_loop_start_ex = 0
        self._wm_replacement_active = False
        self._wm_dagon_active = False
        self._wm_extinction_occurred = False
        self._ahr_world_shift_pending = False
        self._ahr_will_pending = False
        self._ahr_singularity_occurred = False
        self.state.phase = "day_start"
        self._event("loop_started", f"第 1 轮回开始，共 {self.scenario['loops']} 轮，每轮 {self.scenario['days']} 天。")
        self._start_loop_placements()

    @property
    def controller(self):
        if self.state.phase == "decision" and self._decision_actor:
            return self._decision_actor
        return MATCH_FLOW.controller(self.state.phase, leader=self.state.leader, next_actor=self.next_actor)

    def name(self, target):
        if target.endswith("@surface") or target.endswith("@hidden"):
            cid, side = target.rsplit("@", 1)
            return f"{self.state.characters[cid].name}（{'表' if side == 'surface' else '里'}身份）"
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
        if actor == "m" and target in self.roles and self._has(target, "werewolf"):
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
        return super()._intrigue_forbids_cancel(count)

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
        ability_counter = c.paranoia if self.module == "AHR" and self.ex_gauge % 2 else c.goodwill
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
                            card = self._deck(placement.actor)[placement.card]
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
            if "of_blue_cat" in self.scenario["subplots"]:
                result += self._counter_options(None, "plot:of_blue_cat",
                                                [*LOCATIONS, *(c.id for c in self._living())],
                                                "intrigue", 1, "蓝色狸猫的阴谋（每轮一次）", True)
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
                traveler_ready = (all(getattr(c, counter) <= 2 for counter in STANDARD_COUNTERS)
                                  if self.module == "WM" else c.goodwill <= 2)
                if (self._has(c.id, "time_traveler") and self.state.round == self.scenario["days"]
                        and traveler_ready):
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
            if (self.roles[request["source"]] == "puppet"
                    and self.state.characters[request["source"]].goodwill >= 4):
                refusal = "mandatory"
            if (self._has(request["source"], "paper_tiger")
                    and self.state.characters[request["source"]].paranoia >= 2):
                refusal = "mandatory"
            if self.module == "AHR" and self.state.characters[request["source"]].despair:
                refusal = "mandatory"
            if (self.module == "AHR" and "ahr_jekyll" in self.scenario["subplots"]
                    and self._has(request["source"], "ahr_puppet")):
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
                if self.module == "WM":
                    self._change_ex_gauge(1)
                self.state.phase = "goodwill"
                if self.roles[request["source"]] == "puppet":
                    self._return_phase = "goodwill"
                    self._queue = [op("puppet_refusal", target=request["source"])]
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
            if self._has(request["source"], "wizard"):
                selected["effects"] = list(selected["effects"]) + [
                    op("reveal", target=request["source"]),
                    op("choice", actor=self.state.leader,
                       prompt="巫师友好能力已结算：领队是否令 Ex 槽 +1",
                       options=[option("Ex 槽 +1", [op("ex_gauge", amount=1)]),
                                option("不增加 Ex 槽", [])])]
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
            self._start_master_abilities_forced()
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
                self._prevented_incident_culprits.clear()
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

    def _change(self, target, counter, amount, *, silent_noop=False):
        s = self.state
        before = getattr(s.characters[target], counter) if target in s.characters else s.locations[target]
        after = max(0, before + amount)
        if target in s.characters:
            setattr(s.characters[target], counter, after)
        else:
            s.locations[target] = after
        if not (silent_noop and before == after):
            self._event("counter_changed", f"{self.name(target)}：{COUNTER_NAMES[counter]} {before} → {after}。",
                        target=target, counter=counter, before=before, after=after)
        self._counter_mutated(target, counter)

    def _change_ex_gauge(self, amount):
        before = self.ex_gauge
        self.ex_gauge = max(0, before + amount)
        if self.ex_gauge != before:
            self._ahr_refresh_roles()
            self._incident_effect = True
            self._event("ex_gauge_changed", f"Ex 槽 {before} → {self.ex_gauge}。",
                        before=before, after=self.ex_gauge)

    def _kill(self, targets):
        # Snapshot simultaneous deaths (e.g. Hospital or two Serial Killers); no order bias.
        killed = []
        key_death = False
        dying_magicians = []
        dying_wm_conspirators = []
        dying_preachers = []
        for target in dict.fromkeys(targets):
            c = self.state.characters[target]
            if not c.alive:
                continue
            if (self._has(target, "time_traveler") or self._has(target, "immortal")
                    or self._has(target, "detective") or self._has(target, "vampire")
                    or self._has(target, "nightmare") or self._has(target, "paper_tiger")
                    or self._has(target, "sacrifice") or self._has(target, "faceless")
                    or self._has(target, "narrator")):
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
                killed.append(target)
        for target in killed:
            self.state.characters[target].alive = False
            if (self.scenario["main_plot"] == "hsa_ancient_dead"
                    and self.roles[target] in ("ordinary", "paper_tiger")):
                self.roles[target] = "zombie"
            if self.roles[target] == "puppet":
                self._permanent_dead.add(target)
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
                "ex_cards": dict(self.ex_cards), "board_ex": dict(self.board_ex),
                "ex_gauge": self.ex_gauge}

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
                self._change(effect["target"], effect["counter"], effect["amount"],
                             silent_noop=effect.get("silent_noop", False))
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
                if (destination not in c.forbidden
                        and self._movement_destination_allowed(c.id, destination)
                        and self._movement_locks.get(c.id) != self.state.round):
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
            elif kind == "hsa_add_curse":
                target = effect["target"]
                if target in LOCATIONS:
                    self.board_ex[target] += 1
                    count = self.board_ex[target]
                else:
                    self.ex_cards[target] += 1
                    count = self.ex_cards[target]
                self._incident_effect = True
                self._event("curse_added", f"{self.name(target)}获得一张诅咒牌（现有 {count} 张）。",
                            target=target, count=count)
            elif kind == "hsa_attach_curse":
                board, target = effect["board"], effect["target"]
                self.board_ex[board] -= 1
                self.ex_cards[target] += 1
                self._event("curse_attached", f"{LOCATIONS[board]}的一张诅咒牌附身于{self.name(target)}。",
                            board=board, target=target)
            elif kind == "hsa_resolve_curse":
                target = effect["target"]
                board = self.state.characters[target].location
                self.ex_cards[target] -= 1
                self._kill([target])
                self.board_ex[board] += 1
                self._event("curse_returned", f"{self.name(target)}身上的诅咒牌移至{LOCATIONS[board]}。",
                            target=target, board=board)
            elif kind == "hsa_curse_batch":
                remaining = list(effect["remaining"])
                if remaining:
                    choices = []
                    for index, source in enumerate(remaining):
                        rest = remaining[:index] + remaining[index + 1:]
                        if source in self.roles:
                            choices.append(option(
                                f"结算{self.name(source)}身上的诅咒牌",
                                [op("hsa_resolve_curse", target=source),
                                 op("hsa_curse_batch", remaining=rest)]))
                            continue
                        targets = [c.id for c in self._living()
                                   if c.location == source and not self.ex_cards[c.id]]
                        choices += [option(
                            f"{LOCATIONS[source]}的诅咒附身于{self.name(target)}",
                            [op("hsa_attach_curse", board=source, target=target),
                             op("hsa_curse_batch", remaining=rest)])
                            for target in targets]
                        if not targets:
                            choices.append(option(
                                f"结算{LOCATIONS[source]}无目标的诅咒牌",
                                [op("hsa_curse_no_target", board=source),
                                 op("hsa_curse_batch", remaining=rest)]))
                    self._queue.insert(0, op("choice", prompt="选择下一张诅咒牌及其结算方式",
                                             options=choices))
            elif kind == "hsa_curse_no_target":
                board = effect["board"]
                self._event("curse_no_target", f"{LOCATIONS[board]}的诅咒牌没有可附身的角色。",
                            board=board)
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
            elif kind == "hsa_monster_used":
                self._hsa_monster_uses += 1
            elif kind == "hsa_frenzied_night":
                self._hsa_frenzied_night = True
                self._hsa_frenzied_night_lethal = (
                    sum(self._hsa_corpses(board) for board in LOCATIONS) >= 6)
                self._incident_effect = True
                self._event("frenzied_night_active", "疯狂之夜已经发生；将在日末检查尸体总数。")
            elif kind == "hsa_apocalypse":
                board = effect["board"]
                self._kill([c.id for c in self._living() if c.location == board])
                if self.state.phase not in ("loop_end", "final_guess", "game_over") \
                        and self._hsa_corpses(board) >= 5:
                    self._queue.insert(0, op("heroes_die"))
            elif kind == "wm_extinction":
                if self._wm_extinction_occurred:
                    self._event("extinction_repeated", "灭绝之灾此前已经发生过，本次不产生效果。")
                else:
                    self._wm_extinction_occurred = True
                    self._incident_effect = True
                    self._event("extinction_first", "灭绝之灾首次发生：所有角色与主人公死亡。")
                    self._queue = [op("kill_many", targets=[c.id for c in self._living()]),
                                   op("heroes_die")] + self._queue
            elif kind == "wm_dagon_active":
                self._wm_dagon_active = True
                self._incident_effect = True
                self._event("dagon_whisper_active",
                            "达贡黑井之息已经发生：本轮之后若有其他事件发生，主人公在该事件阶段结束时死亡。")
            elif kind == "ahr_world_shift":
                self._ahr_world_shift(effect["reason"])
            elif kind == "ahr_puppet_check":
                c = self.state.characters[effect["target"]]
                if sum(getattr(c, counter) > 0 for counter in COUNTER_NAMES) >= 2:
                    self._ahr_world_shift("提线木偶友好能力结算后具有两种以上指示物")
            elif kind == "ahr_alice":
                source = self.state.characters[effect["source"]]
                if self.ex_gauge >= 1 and self._available_key(f"alice:{source.id}", True):
                    self._mark(f"alice:{source.id}", True)
                    choices = [option(f"{c.name}希望 +1",
                                      [op("counter", target=c.id, counter="hope", amount=1)])
                               for c in self._living()
                               if c.id != source.id and c.location == source.location]
                    if choices:
                        self._queue.insert(0, op("choice", prompt="爱丽丝：选择同区域另一名角色希望 +1",
                                                 options=choices))
            elif kind == "ahr_corpse_intrigue_check":
                if sum(c.intrigue for c in self.state.characters.values() if not c.alive) >= 3:
                    self._queue.insert(0, op("heroes_die"))
            elif kind == "ahr_dimension_break":
                c = self.state.characters[effect["target"]]
                if sum(getattr(c, counter) > 0 for counter in COUNTER_NAMES) >= 3:
                    self._queue.insert(0, op("heroes_die"))
            elif kind == "ahr_will":
                self._ahr_will_pending = True
                self._event("hope_card_scheduled", "遗言已发生：下一轮开始主人公获得一张「希望 +1」。")
            elif kind == "ahr_singularity_first":
                self._ahr_singularity_occurred = True
            elif kind == "ahr_singularity_hidden":
                cid = effect["target"]
                if self.state.locations[self._loop_initial_locations[cid]] >= 1:
                    self._queue.insert(0, op("heroes_die"))
            elif kind == "move_corpse":
                target, location = effect["target"], effect["location"]
                self.state.characters[target].location = location
                self._event("corpse_moved", f"{self.name(target)}的尸体移至{LOCATIONS[location]}。",
                            target=target, location=location)
            elif kind == "ex_gauge":
                self._change_ex_gauge(effect["amount"])
            elif kind == "clear_paranoia":
                target = effect["target"]
                self._change(target, "paranoia", -self.state.characters[target].paranoia,
                             silent_noop=True)
            elif kind == "suspicious_move":
                c = self.state.characters[effect["target"]]
                destination = effect["location"]
                moved = (destination != c.location and destination not in c.forbidden
                         and self._movement_destination_allowed(c.id, destination)
                         and self._movement_locks.get(c.id) != self.state.round)
                if moved:
                    c.location = destination
                    self._event("character_moved", f"{c.name}移动到{LOCATIONS[destination]}。",
                                target=c.id, location=destination)
                    self._movement_locks[c.id] = self.state.round + 1
                    self._event("movement_restricted", f"{c.name}在第 {self.state.round + 1} 天不能移动。",
                                target=c.id, day=self.state.round + 1)
                elif destination != c.location:
                    self._event("movement_blocked", f"{c.name}未能移动到{LOCATIONS[destination]}。")
            elif kind == "seal_board":
                board = effect["board"]
                through = self.state.round + 2
                self._sealed_boards.append((board, through))
                self._incident_effect = True
                self._event("board_sealed", f"{LOCATIONS[board]}从今天起至第 {through} 天封锁；角色不能通过移动进入或离开。",
                            board=board, through=through)
            elif kind == "finish_loop":
                self.loss_reasons.append(effect.get("reason", "事件使轮回结束"))
                self._finish_loop(forced=True)
            elif kind == "mc_psychiatrist_batch":
                remaining = list(effect["sources"])
                choices = []
                for source in remaining:
                    c = self.state.characters[source]
                    targets = [target.id for target in self._living()
                               if target.id != source and target.location == c.location]
                    rest = [cid for cid in remaining if cid != source]
                    choices += [option(f"{c.name}（心理医生·强制）：移除{self.name(target)}的 1 不安",
                                       [op("counter", target=target, counter="paranoia", amount=-1,
                                           silent_noop=True),
                                        op("mc_psychiatrist_batch", sources=rest)])
                                for target in targets]
                if choices:
                    self._queue.insert(0, op("choice", prompt="选择心理医生强制能力的结算顺序及目标",
                                             options=choices))
                elif remaining:
                    self._event("no_effect", "心理医生的强制能力已触发，但没有合法目标。")
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
            elif kind == "prevent_incident":
                target = effect["target"]
                self._prevented_incident_culprits.add(target)
                self._event("incident_prevented", f"{self.name(target)}担任当事人的今日事件不会发生。",
                            target=target)
            elif kind == "set_loop_initial_location":
                target, location = effect["target"], effect["location"]
                self.state.characters[target].location = location
                self._loop_initial_locations[target] = location
                self._event("initial_location_chosen", f"{self.name(target)}本轮从{LOCATIONS[location]}开始。",
                            target=target, location=location)
            elif kind == "recover":
                actor, card = effect["actor"], effect["card"]
                self.state.discarded[actor].remove(card)
                self.state.hands[actor].append(card)
                self._event("card_recovered", f"{ACTOR_NAMES[actor]}收回{self._deck(actor)[card].name}。")
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
                            f"「{self._deck(placement.actor)[placement.card].name}」被无效化。",
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
            elif kind == "mandatory_poison_mark":
                self._mandatory_victims.append(effect["target"])
            elif kind == "mandatory_choice_batch":
                groups = []
                for group in effect["choices"]:
                    available = [item for item in group["options"] if not any(
                        nested.get("kind") == "trickster_mark"
                        and nested.get("target") in self._trickster_targets
                        for nested in item["effects"])]
                    if available:
                        groups.append({**group, "options": available})
                choices = []
                for group_index, group in enumerate(groups):
                    remaining = groups[:group_index] + groups[group_index + 1:]
                    for item in group["options"]:
                        choices.append(option(item["label"],
                                              list(item["effects"])
                                              + [op("mandatory_choice_batch", choices=remaining)]))
                if choices:
                    self._queue.insert(0, op("choice", prompt="选择已触发强制能力的结算顺序及目标",
                                             options=choices))
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
        if self.module == "HSA":
            self._hsa_incident(incident)
            return
        if self.module == "WM":
            self._wm_incident(incident)
            return
        if self.module == "AHR":
            self._ahr_incident(incident)
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
        score = (culprit.intrigue if kind == "imaginary_incident" else
                 culprit.goodwill if (self.ex_gauge % 2 or kind == "hope_light") else
                 culprit.paranoia)
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

    def _begin_night(self):
        s = self.state
        s.leader = PROTAGONISTS[(PROTAGONISTS.index(s.leader) + 1) % 3]
        self._event("leader_changed", f"领队轮换为{ACTOR_NAMES[s.leader]}。")
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
        if queue:
            self._return_phase = "master_abilities"
            self._queue = queue
            self._drain()

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
        self._queue = ([op("hsa_curse_batch", remaining=curses)] if curses else [])
        if self.module == "AHR" and self._ahr_world_shift_pending:
            self._ahr_world_shift_pending = False
            self._queue.insert(0, op("ex_gauge", amount=1))
        self._queue.append(op("next_day_end_mandatory"))
        self._drain()

    def _queue_day_end_mandatory_batch(self):
        """Activate every mandatory effect on one snapshot, then resolve the batch."""
        living = self._living()
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
                target_choices.append({
                    "prompt": "捣蛋鬼已触发：选择一名同区域角色死亡",
                    "options": [option(f"{c.name}（捣蛋鬼·强制）：使{target.name}死亡",
                                       [op("trickster_mark", source=c.id, target=target.id)])
                                for target in others if target.id not in self._trickster_targets],
                })
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
        if ex_gain:
            follow.append(op("ex_gauge", amount=ex_gain))
        if loss_reasons:
            follow.append(op("loop_loss", reason="；".join(loss_reasons)))
        follow.append(op("next_day_end_mandatory"))
        choice_batch = [op("mandatory_choice_batch", choices=target_choices)] if target_choices else []
        self._queue = choice_batch + follow + self._queue

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
        if self.module == "WM" and self._wm_replacement_active:
            main = self.scenario["wm_replacement_plot"]
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
                     (main == "mc_event_web" and self.ex_gauge >= 3) or
                     (main == "mc_tightrope" and self.ex_gauge <= 1) or
                     (main == "mc_dark_school"
                      and s.locations["school"] >= s.loop - 1) or
                     ("mc_gunpowder" in self.scenario["subplots"]
                      and sum(c.intrigue for c in self._living()) >= 12) or
                     ("of_delorean" in self.scenario["subplots"]
                      and any(c.goodwill >= 3 and self.roles[c.id] == "loved" for c in s.characters.values())) or
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
                             self.roles[c.id] == "obsessive" and c.intrigue + self.ex_gauge >= 3
                             for c in self.state.characters.values())))) or
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
        self._returner_carry = {
            c.id: {**{counter: getattr(c, counter) for counter in STANDARD_COUNTERS},
                   "guard": self.guards[c.id]}
            for c in s.characters.values()
            if c.alive and c.goodwill >= 3
            and self.roles[c.id] in ("returner_enemy", "returner_friend")
        }
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
        self.ex_gauge = 0
        if self.module == "AHR":
            for actor in PROTAGONISTS:
                self.state.hands[actor].remove("ahr_h1")
            if old.loop >= 1:
                self.state.hands["m"].remove("ahr_d1")
            self._ahr_world_shift_pending = False
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
        carry = deepcopy(self._returner_carry)
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
        self._event("loop_started", f"第 {s.loop} 轮回开始：位置、存活、计数物、手牌、护卫及本轮效果已重置；历史日志和已公开信息保留。")
        if self.module == "AHR":
            give_despair = bool(getattr(self, "_previous_fragment_dead", set()))
            give_despair |= ("ahr_beyond_worldline" in self.scenario["subplots"] and s.loop % 2 == 0)
            give_hope = bool(getattr(self, "_previous_fragment_friendly", set())) or self._ahr_will_pending
            give_hope |= ("ahr_beyond_worldline" in self.scenario["subplots"]
                          and s.loop == self.scenario["loops"])
            if give_despair and "ahr_d1" not in self.state.hands["m"]:
                self.state.hands["m"].append("ahr_d1")
                self._event("special_card_gained", "剧作家获得「绝望 +1」。")
            if give_hope and "ahr_h1" not in self.state.hands[s.leader]:
                self.state.hands[s.leader].append("ahr_h1")
                self._event("special_card_gained", f"{ACTOR_NAMES[s.leader]}获得「希望 +1」。")
            self._ahr_will_pending = False
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
                        passive=definition.passive,
                        initial_location=self._loop_initial_locations.get(cid, definition.start),
                        ex_cards=self.ex_cards.get(cid, 0))
        result.update(title=self.scenario["title"], days=self.scenario["days"], loops=self.scenario["loops"],
                      table_talk=self.scenario["table_talk"], controller=self.controller, winner=self.winner,
                      module_name=spec.name,
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
        if viewer == "m":
            result["secret"] = {"roles": dict(self.roles), "initial_roles": dict(self.scenario["cast"]),
                                "main_plot": self.scenario["main_plot"], "subplots": list(self.scenario["subplots"]),
                                "incidents": deepcopy(self.scenario["incidents"]), "loss_reasons": list(self.loss_reasons),
                                "current_loop_days": self._current_loop_days(),
                                "ability_day_used": sorted(self.day_used), "ability_loop_used": sorted(self.loop_used)}
            if self.module == "AHR":
                result["secret"]["hidden_roles"] = dict(self.scenario["hidden_cast"])
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
