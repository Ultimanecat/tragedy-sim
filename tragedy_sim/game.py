"""Complete hotseat match flow. Effects are deterministic; choices belong to humans.

All logs are public. Secret roles, requirements and offered mastermind options are
kept outside the public projection. dispatch() is atomic and is also the replay API.
"""

from copy import deepcopy
from dataclasses import asdict
import json
import hashlib
from pathlib import Path
import random

from .cards import ACTORS, ACTOR_NAMES, COORDS, COUNTER_NAMES, LOCATIONS, PROTAGONISTS, STANDARD_COUNTERS, deck
from .catalog import CHARACTERS, INCIDENT_NAMES, MODULES, MODULE_PLOTS, PLOTS, REFUSAL, ROLE_NAMES, TRAIT_NAMES
from .engine import ActionGame, Character, RuleError, State
from .domain import (ActionOffer, Activation, ActivationMode, ComponentStore, Effect,
                     LegacyEffect, MandatoryWindow, PhaseKey, ResolutionTrace, RuleContext,
                     RuleSource, SourcedEffect, WindowStage, legacy_effect, normalize_effect)
from .effect_resolver import MATCH_EFFECT_HANDLERS
from .effects.vocabulary import op, option
from .flow import MATCH_FLOW, phase_label
from .i18n import format_timepoint, label, normalize_language
from .model import (DecisionRecord, Observation, PhaseCursor, ResolutionStep, SimulationResult,
                    TimingId, timing_for_phase)
from .phases import PHASE_RESOLVERS
from .scenario import example_scenario, validate_scenario
from .rulesets.registry import get_ruleset
from .transcript import describe_decision


class Game(ActionGame):
    def __init__(self, scenario=None):
        self.scenario = validate_scenario(example_scenario() if scenario is None else scenario)
        chars = [Character(cid, CHARACTERS[cid].name, CHARACTERS[cid].start, CHARACTERS[cid].forbidden)
                 for cid in self.scenario["cast"]]
        super().__init__(chars, module=self.scenario["module"])
        self.ruleset = get_ruleset(self.module)
        self.ruleset.initialize(self)

    @property
    def controller(self):
        return self.ruleset.phases.resolve(self.state.phase).controller(self)

    def name(self, target):
        return self.ruleset.operations['name'](self, target)

    def _event(self, kind, message, *, timing=None, **data):
        phase = self.state.phase
        public_phase = phase
        if phase == "decision":
            public_phase = self._decision_public_phase or self._return_phase
        if timing is None:
            timing = (TimingId.LOOP_END if self._at_loop_end else
                      timing_for_phase(public_phase) if public_phase == "resolved" else
                      self.ruleset.phases.resolve(public_phase).timing(self))
        timing = TimingId(timing)
        super()._event(kind, message, timing=timing.value, **data)
        self.state.events[-1]["phase"] = self.state.phase
        if getattr(self, "_trace_observation_stack", None):
            event = self.state.events[-1]
            known = {"loop", "round", "phase", "timing", "kind", "message"}
            self._trace_observation_stack[-1].append(Observation(
                kind=event["kind"], message=event["message"],
                data={key: deepcopy(value) for key, value in event.items() if key not in known},
                timing=TimingId(event["timing"]),
            ))

    def _current_timing(self):
        if self._at_loop_end:
            return TimingId.LOOP_END
        phase = self.state.phase
        if phase == "decision":
            phase = self._decision_public_phase or self._return_phase
        return self.ruleset.phases.resolve(phase).timing(self)

    def dispatch(self, actor, action, **args):
        if actor not in ACTORS:
            raise RuleError("未知玩家、命令或参数")
        try:
            self.ruleset.phases.resolve(self.state.phase).validate_command(action, args)
        except ValueError as exc:
            raise RuleError(str(exc)) from exc
        resolver = self.ruleset.phases.resolve(self.state.phase)
        resolver.authorize(self, actor, action)
        snapshot = deepcopy(self.__dict__)
        before = self.phase_cursor
        decision_timing = self._current_timing()
        event_start = len(self.state.events)
        description = describe_decision(self, actor, action, args)
        try:
            resolver.execute(self, actor, action, args)
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
            before=before, after=self.phase_cursor, timing=decision_timing, steps=steps,
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
        return self.ruleset.phases.resolve(self.state.phase).legal_actions(self, actor)

    def action_offers(self, actor):
        """Typed legal actions for rulesets, network clients, and future MCTS."""
        timing = self._current_timing()
        return [ActionOffer.from_command(command, timing=timing,
                                         source=RuleSource("core.legal_action"))
                for command in self.legal_actions(actor)]

    def simulate(self, actor, action, **args):
        """Apply one action to a detached clone, leaving this world untouched."""
        successor = self.clone()
        successor.dispatch(actor, action, **args)
        return SimulationResult(successor, successor.decisions[-1])

    def clone(self):
        """Explicit search clone; immutable ruleset definitions remain shared."""
        clone = deepcopy(self)
        clone.ruleset = self.ruleset
        return clone

    def rule_context(self, timing=None):
        timing = timing or self._current_timing()
        return RuleContext(self.state, self.scenario, self.module,
                           PhaseKey(f"core.{self.state.phase}"), TimingId(timing), self.components)

    def _open_timing_window(self, timing, queued, source):
        """Freeze a mandatory batch before any member is resolved."""
        effects = tuple(item if isinstance(item, Effect) else legacy_effect(item) for item in queued)
        activation = Activation(RuleSource(source), TimingId(timing),
                                ActivationMode.MANDATORY, "m", effects)
        self._timing_window = MandatoryWindow(self.rule_context(timing), (activation,))
        self._activation_history.append(activation)
        self._timing_window.start()
        self._queue = [SourcedEffect(effect, activation.source) for effect in effects]
        if self._queue:
            self._drain()
        else:
            self._timing_window.finish_mandatory()

    def _timing_optional_ready(self):
        return self._timing_window is None or self._timing_window.stage == WindowStage.OPTIONAL

    def _close_timing_window(self):
        if self._timing_window is not None:
            self._timing_window.close()
            self._timing_window = None

    def _optional_effects(self, selected, actor):
        effects = tuple(item if isinstance(item, Effect) else legacy_effect(item)
                        for item in selected.get("effects", ()))
        identity = str(selected.get("key", selected.get("label", "choice"))).encode("utf-8")
        source = RuleSource(f"{self.module.lower()}.optional.h{hashlib.sha256(identity).hexdigest()[:12]}")
        activation = Activation(source, self._current_timing(), ActivationMode.OPTIONAL,
                                actor, effects)
        self._activation_history.append(activation)
        return [SourcedEffect(effect, source) for effect in effects]

    @property
    def activation_history(self):
        """Private triggered abilities for search/debugging; never part of a player view."""
        return deepcopy(tuple(self._activation_history))

    def next_round(self):
        raise RuleError("完整对局请使用 next 按阶段推进，不能跳过结算")

    def reset_loop(self):
        raise RuleError("完整对局不能随意重置轮回")

    def _living(self):
        return [c for c in self.state.characters.values() if c.alive]

    def _can_target_action(self, actor, target):
        return self.ruleset.operations['_can_target_action'](self, actor, target)

    def play(self, actor, card_id, target):
        return self.ruleset.operations['play'](self, actor, card_id, target)

    def _apply_current_roles(self):
        return self.ruleset.operations['_apply_current_roles'](self)

    def _refresh_mz_ex_roles(self):
        return self.ruleset.operations['_refresh_mz_ex_roles'](self)

    def _movement_is_forbidden(self, target, effects):
        return self.ruleset.operations['_movement_is_forbidden'](self, target, effects)

    def _movement_destination_allowed(self, target, destination):
        return self.ruleset.operations['_movement_destination_allowed'](self, target, destination)

    def _intrigue_forbids_cancel(self, count):
        return self.ruleset.operations['_intrigue_forbids_cancel'](self, count)

    def _has(self, cid, role):
        return self.ruleset.operations['_has'](self, cid, role)

    def _ahr_world_shift(self, reason):
        return self.ruleset.operations['_ahr_world_shift'](self, reason)

    def _ahr_refresh_roles(self):
        return self.ruleset.operations['_ahr_refresh_roles'](self)

    def _ll_traitor_labels(self):
        return self.ruleset.operations['_ll_traitor_labels'](self)

    def _ll_seat_for_secret(self, label):
        return self.ruleset.operations['_ll_seat_for_secret'](self, label)

    def _ll_traitor_seats(self):
        return self.ruleset.operations['_ll_traitor_seats'](self)

    def _count(self, character, counter):
        return self.ruleset.operations['_count'](self, character, counter)

    def _hsa_corpses(self, board):
        return self.ruleset.operations['_hsa_corpses'](self, board)

    def _hsa_curse_total(self):
        return self.ruleset.operations['_hsa_curse_total'](self)

    def _wm_plot_loss(self, plot):
        return self.ruleset.operations['_wm_plot_loss'](self, plot)

    def _counter_mutated(self, target, counter):
        return self.ruleset.operations['_counter_mutated'](self, target, counter)

    def _ignore_forbid(self, counter, target):
        return self.ruleset.operations['_ignore_forbid'](self, counter, target)

    def resolve(self):
        self._reveal_and_move()
        self._ignore_intrigue.clear()
        detail = "移动已结算。请剧作家确认行动结算中的能力，再继续结算计数物。"
        # Always pause here, not only when a relevant role exists; the public phase reveals no role.
        self._event("resolution_window", detail)

    def _available_key(self, key, once=False):
        return self.ruleset.operations['_available_key'](self, key, once)

    def _mark(self, key, once=False):
        return self.ruleset.operations['_mark'](self, key, once)

    def _counter_options(self, source, key, targets, counter, amount, label, once=False):
        return self.ruleset.operations['_counter_options'](self, source, key, targets, counter, amount, label, once)

    def _scoped_targets(self, source, scope):
        return self.ruleset.operations['_scoped_targets'](self, source, scope)

    def _ability_options(self, source, ability, *, private=False):
        return self.ruleset.operations['_ability_options'](self, source, ability, private=private)

    def options(self, actor):
        return self.ruleset.operations['options'](self, actor)

    def _choose(self, actor, index):
        return self.ruleset.operations['_choose'](self, actor, index)

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
        return self.ruleset.operations['_kill'](self, targets)

    def _script_roles(self):
        return self.ruleset.operations['_script_roles'](self)

    def _publish_role(self, target, role):
        return self.ruleset.operations['_publish_role'](self, target, role)

    def _reveal_role(self, target, *, truthful=False):
        return self.ruleset.operations['_reveal_role'](self, target, truthful=truthful)

    def _public_board(self):
        return {"characters": {c.id: asdict(c) for c in self.state.characters.values()},
                "locations": dict(self.state.locations), "guards": dict(self.guards),
                "ex_cards": dict(self.ex_cards), "board_ex": dict(self.board_ex),
                "ex_gauge": self.ex_gauge}

    @property
    def resolution_traces(self):
        """Full private effect causality for diagnostics and deterministic replay checks."""
        return deepcopy(tuple(self._resolution_traces))

    def _record_effect_trace(self, source, resolved_effect, timing, observations):
        self._resolution_traces.append(ResolutionTrace(
            source=source, timing=timing, effect=resolved_effect,
            observations=tuple(observations),
            details={"compatibility_adapter": isinstance(resolved_effect, LegacyEffect)},
        ))

    def _drain(self):
        while self._queue and self.state.phase not in ("loop_end", "final_guess", "game_over"):
            queued = self._queue.pop(0)
            if isinstance(queued, SourcedEffect):
                resolved_effect = queued.effect
                source = queued.source
            elif isinstance(queued, Effect):
                resolved_effect = queued
                namespace = resolved_effect.kind if "." in resolved_effect.kind else f"core.{resolved_effect.kind}"
                source = RuleSource(namespace)
            else:
                resolved_effect = legacy_effect(queued)
                source = RuleSource(f"legacy.{resolved_effect.kind}")
            effect = normalize_effect(resolved_effect)
            trace_timing = self._current_timing()
            observations = []
            self._trace_observation_stack.append(observations)
            kind = effect["kind"]
            before_queue = tuple(self._queue)
            try:
                if kind == "choice":
                    if effect["options"]:
                        self._pending = effect
                        self._pending_source = source
                        self._decision_actor = effect.get("actor", "m")
                        origin = self.state.phase
                        if origin in ("decision", "refusal"):
                            origin = self._return_phase
                        self._decision_public_phase = origin
                        self.state.phase = "decision"
                        return
                    self._event("no_effect", "没有可作用的目标，这部分效果未产生变化。")
                elif self.ruleset.effects.handles(kind):
                    self.ruleset.effects.resolve(self, effect)
                else:
                    raise RuleError("不支持的内部效果；停止结算")
                old_ids = {id(item) for item in before_queue}
                self._queue = [
                    item if isinstance(item, SourcedEffect) or id(item) in old_ids
                    else SourcedEffect(item if isinstance(item, Effect) else legacy_effect(item), source)
                    for item in self._queue
                ]
            finally:
                self._trace_observation_stack.pop()
                self._record_effect_trace(source, resolved_effect, trace_timing, observations)
        if not self._pending and self.state.phase not in ("loop_end", "final_guess", "game_over"):
            self.state.phase = self._return_phase
            self._decision_public_phase = None
            self._decision_actor = None
            if (self._timing_window is not None
                    and self._timing_window.stage == WindowStage.RESOLVING_MANDATORY):
                self._timing_window.finish_mandatory()

    def _incident(self):
        return self.ruleset.operations['_incident'](self)

    def _hsa_incident(self, incident):
        return self.ruleset.operations['_hsa_incident'](self, incident)

    def _wm_incident(self, incident):
        return self.ruleset.operations['_wm_incident'](self, incident)

    def _ahr_incident(self, incident):
        return self.ruleset.operations['_ahr_incident'](self, incident)

    def _ll_incident(self, incident):
        return self.ruleset.operations['_ll_incident'](self, incident)

    def _mc_incident_location(self, culprit_id):
        return self.ruleset.operations['_mc_incident_location'](self, culprit_id)

    def _mc_incident_effects(self, kind, culprit_id):
        return self.ruleset.operations['_mc_incident_effects'](self, kind, culprit_id)

    def _mz_incident_effects(self, kind, culprit_id):
        return self.ruleset.operations['_mz_incident_effects'](self, kind, culprit_id)

    def _record_incident_end(self):
        return self.ruleset.operations['_record_incident_end'](self)

    def _begin_night(self):
        return self.ruleset.operations['_begin_night'](self)

    def _start_master_abilities_forced(self):
        return self.ruleset.operations['_start_master_abilities_forced'](self)

    def _start_loop_placements(self):
        return self.ruleset.operations['_start_loop_placements'](self)

    def _start_day_end_forced(self):
        return self.ruleset.operations['_start_day_end_forced'](self)

    def _queue_day_end_mandatory_batch(self):
        return self.ruleset.operations['_queue_day_end_mandatory_batch'](self)

    def _finish_loop(self, forced=False):
        return self.ruleset.operations['_finish_loop'](self, forced)

    def _resolve_loop_end(self, forced=False):
        return self.ruleset.operations['_resolve_loop_end'](self, forced)

    def _restore_board(self, *, apply_loop_rules=False):
        return self.ruleset.operations['_restore_board'](self, apply_loop_rules=apply_loop_rules)

    def _new_loop(self):
        return self.ruleset.operations['_new_loop'](self)

    def _start_final_guess(self):
        return self.ruleset.operations['_start_final_guess'](self)

    def _guess(self, cid, role):
        return self.ruleset.operations['_guess'](self, cid, role)

    def _win(self, winner, message):
        timing = self._current_timing()
        self.winner = winner
        self.state.phase = "game_over"
        self._queue, self._pending, self._request = [], None, None
        self._decision_public_phase = None
        self._event("game_ended", message, winner=winner, timing=timing)

    def view(self, viewer="spectator", language="zh"):
        return self.ruleset.operations['view'](self, viewer, language)

    def save(self, path):
        # Local trusted replay file contains secrets. Exclusive create prevents overwrite.
        with Path(path).open("x", encoding="utf-8") as stream:
            json.dump({"version": 1, "scenario": self.scenario, "commands": self.history}, stream, ensure_ascii=False, indent=2)

    def save_replay(self, path, language=None):
        """Export a completed match as a readable, deterministic text replay."""
        from .replay import dump
        dump(self, path, language or getattr(self, "language", "zh"))

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
