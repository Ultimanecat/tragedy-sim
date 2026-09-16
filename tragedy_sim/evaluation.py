"""Scenario-conditioned position evaluation for FS and BTX search.

The evaluator compiles immutable script facts once, then evaluates mutable game
state without parsing UI text.  Its contribution report is private AI
diagnostics and must never be projected into player views or replays.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any

from .catalog import CHARACTERS
from .search import MastermindEvaluator, SearchGame


@dataclass(frozen=True)
class ScenarioEvaluationContext:
    key: str
    module: str
    days: int
    loops: int
    main_plot: str
    subplots: tuple[str, ...]
    roles: tuple[tuple[str, str], ...]
    incidents: tuple[tuple[int, str, str], ...]
    initial_locations: tuple[tuple[str, str], ...]

    @classmethod
    def compile(cls, scenario: dict[str, Any]) -> "ScenarioEvaluationContext":
        canonical = json.dumps(scenario, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"))
        roles = tuple(sorted(scenario["cast"].items()))
        return cls(
            key=hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16],
            module=scenario["module"], days=scenario["days"],
            loops=scenario["loops"], main_plot=scenario["main_plot"],
            subplots=tuple(scenario["subplots"]), roles=roles,
            incidents=tuple((item["day"], item["kind"], item["culprit"])
                            for item in scenario.get("incidents", ())),
            initial_locations=tuple(
                (cid, CHARACTERS[cid].start) for cid, _ in roles),
        )


@dataclass(frozen=True)
class EvaluationContribution:
    key: str
    value: float
    progress: float
    detail: str


@dataclass(frozen=True)
class PositionFeatures:
    loop: int
    day: int
    phase: str
    locations: tuple[tuple[str, int], ...]
    characters: tuple[tuple[str, bool, bool, str, int, int, int], ...]
    known_roles: int
    known_culprits: int
    known_plots: int

    @classmethod
    def extract(cls, game: SearchGame) -> "PositionFeatures":
        return cls(
            loop=game.state.loop, day=game.state.round, phase=game.state.phase,
            locations=tuple(sorted(game.state.locations.items())),
            characters=tuple(sorted(
                (cid, c.present, c.alive, c.location, c.paranoia,
                 c.goodwill, c.intrigue)
                for cid, c in game.state.characters.items())),
            known_roles=len(getattr(game, "known_roles", {})),
            known_culprits=len(getattr(game, "known_culprits", {})),
            known_plots=len(getattr(game, "known_plots", ())),
        )


@dataclass(frozen=True)
class PositionEvaluation:
    value: float
    context_key: str
    stable: bool
    contributions: tuple[EvaluationContribution, ...]


def _threshold_progress(value: float, threshold: float) -> float:
    if threshold <= 0 or value >= threshold:
        return 1.0
    if value <= 0:
        return 0.0
    ratio = value / threshold
    return 0.12 + 0.55 * ratio * ratio


class ScenarioConditionedEvaluator:
    """Composable full-information value model, initially for FS and BTX."""

    SUPPORTED_MODULES = frozenset({"FS", "BTX"})
    _UNSTABLE_PHASES = frozenset({
        "mastermind", "protagonists", "reveal", "action_counters", "decision",
    })

    def __init__(self, fallback: MastermindEvaluator | None = None):
        self.fallback = fallback or MastermindEvaluator()
        self._contexts: dict[str, ScenarioEvaluationContext] = {}
        self._scenario_contexts: dict[tuple[Any, ...], ScenarioEvaluationContext] = {}
        self.last_report: PositionEvaluation | None = None

    def context_for(self, scenario: dict[str, Any]) -> ScenarioEvaluationContext:
        signature = (
            scenario["id"], scenario["module"], scenario["days"], scenario["loops"],
            scenario["main_plot"], tuple(scenario["subplots"]),
            tuple(sorted(scenario["cast"].items())),
            tuple((item["day"], item["kind"], item["culprit"],
                   item.get("public_kind")) for item in scenario.get("incidents", ())),
        )
        cached = self._scenario_contexts.get(signature)
        if cached is not None:
            return cached
        context = ScenarioEvaluationContext.compile(scenario)
        context = self._contexts.setdefault(context.key, context)
        self._scenario_contexts[signature] = context
        return context

    @staticmethod
    def _add(items: list[EvaluationContribution], key: str, weight: float,
             progress: float, detail: str) -> None:
        progress = max(0.0, min(1.0, progress))
        value = weight * progress
        if value:
            items.append(EvaluationContribution(key, value, progress, detail))

    def _main_plot(self, game: SearchGame, context: ScenarioEvaluationContext,
                   items: list[EvaluationContribution]) -> None:
        state = game.state
        roles = dict(context.roles)
        locations = dict(context.initial_locations)
        main = context.main_plot
        if main == "protect":
            value = state.locations["school"]
            self._add(items, "plot:protect", 0.62,
                      _threshold_progress(value, 2),
                      f"学校密谋 {value}/2")
        elif main == "sealed":
            value = state.locations["shrine"]
            self._add(items, "plot:sealed", 0.62,
                      _threshold_progress(value, 2),
                      f"神社密谋 {value}/2")
        elif main in {"avenger", "bomb"}:
            role = "brain" if main == "avenger" else "witch"
            for cid, assigned in roles.items():
                if assigned != role:
                    continue
                board = locations[cid]
                value = state.locations[board]
                self._add(items, f"plot:{main}:{cid}", 0.62,
                          _threshold_progress(value, 2),
                          f"{cid} 初始区域 {board} 密谋 {value}/2")
        elif main == "sign":
            for cid, role in roles.items():
                if role == "key":
                    value = state.characters[cid].intrigue
                    self._add(items, f"plot:sign:{cid}", 0.62,
                              _threshold_progress(value, 2),
                              f"关键人物 {cid} 密谋 {value}/2")
        elif main == "change":
            happened = any(record.get("kind") == "butterfly"
                           and record.get("happened")
                           for record in getattr(game, "incident_records", ()))
            self._add(items, "plot:change", 0.78, float(happened),
                      "本轮蝴蝶效应已经发生" if happened else "蝴蝶效应尚未发生")

    def _role_routes(self, game: SearchGame, context: ScenarioEvaluationContext,
                     items: list[EvaluationContribution]) -> None:
        state = game.state
        roles = game.roles
        living = [c for c in state.characters.values() if c.present and c.alive]
        protection = 0.55 if getattr(game, "protected", False) else 1.0
        keys = [c for c in living if game._has(c.id, "key")]

        for cid, role in roles.items():
            character = state.characters.get(cid)
            if character is None or not character.present:
                continue
            if role == "key" and not character.alive:
                self._add(items, f"role:key_dead:{cid}", 0.88, 1.0,
                          f"关键人物 {cid} 已死亡")
            if role == "friend" and not character.alive:
                self._add(items, f"role:friend_dead:{cid}", 0.82, 1.0,
                          f"亲友 {cid} 已死亡")
            if not character.alive:
                continue
            if game._has(cid, "killer"):
                self._add(items, f"role:killer_direct:{cid}", 0.72,
                          _threshold_progress(character.intrigue, 4) * protection,
                          f"杀手 {cid} 密谋 {character.intrigue}/4")
                for key in keys:
                    same = key.location in game._ability_locations(cid)
                    progress = _threshold_progress(key.intrigue, 2)
                    progress *= (1.0 if same else 0.22) * protection
                    self._add(items, f"role:killer_key:{cid}:{key.id}", 0.70,
                              progress,
                              f"杀手与关键人物{'可接触' if same else '不同区域'}；关键人物密谋 {key.intrigue}/2")
            if game._has(cid, "serial"):
                others = [other for other in living
                          if other.id != cid and other.location == character.location]
                dangerous = [other for other in others
                             if game._has(other.id, "key") or roles[other.id] == "friend"]
                self._add(items, f"role:serial:{cid}", 0.68,
                          1.0 if len(others) == 1 and dangerous else 0.0,
                          f"杀人狂 {cid} 同区域其他存活角色 {len(others)} 名")
            if role == "lover":
                progress = min(_threshold_progress(character.paranoia, 3),
                               _threshold_progress(character.intrigue, 1))
                self._add(items, f"role:lover:{cid}", 0.68, progress,
                          f"求爱者 {cid} 不安 {character.paranoia}/3、密谋 {character.intrigue}/1")
            if role == "time_traveler":
                ready = 1.0 if character.goodwill <= 2 else max(
                    0.0, 1.0 - (character.goodwill - 2) / 3)
                urgency = 0.18 + 0.82 * state.round / context.days
                self._add(items, f"role:time_traveler:{cid}", 0.70,
                          ready * urgency,
                          f"时间旅行者 {cid} 友好 {character.goodwill}；第 {state.round}/{context.days} 天")
            if role == "factor":
                city = _threshold_progress(state.locations["city"], 2)
                school = _threshold_progress(state.locations["school"], 2)
                self._add(items, f"role:factor_key:{cid}", 0.20, city,
                          f"都市密谋 {state.locations['city']}/2，可获得关键人物能力")
                self._add(items, f"role:factor_conspiracy:{cid}", 0.10, school,
                          f"学校密谋 {state.locations['school']}/2，可获得传谣人能力")

    def _incident_routes(self, game: SearchGame,
                         context: ScenarioEvaluationContext,
                         items: list[EvaluationContribution]) -> None:
        state = game.state
        roles = game.roles
        resolved_days = {record["day"] for record in getattr(game, "incident_records", ())}
        for day, kind, culprit_id in context.incidents:
            if day < state.round or day in resolved_days:
                continue
            culprit = state.characters.get(culprit_id)
            if culprit is None or not culprit.present or not culprit.alive:
                continue
            limit = max(1, CHARACTERS[culprit_id].limit)
            progress = _threshold_progress(culprit.paranoia, limit)
            deadline = 1.0 / (1.0 + 0.18 * max(0, day - state.round))
            impact = 0.18
            if kind in {"murder", "faraway"}:
                victims = [c for c in state.characters.values()
                           if c.present and c.alive and c.id != culprit_id
                           and (c.location == culprit.location if kind == "murder"
                                else c.intrigue >= 2)]
                if any(game._has(c.id, "key") or roles[c.id] == "friend"
                       for c in victims):
                    impact = 0.52
            elif kind == "suicide":
                impact = 0.62 if (game._has(culprit_id, "key")
                                  or roles[culprit_id] == "friend") else 0.16
            elif kind == "hospital":
                board = state.locations["hospital"]
                impact = 0.70 if board >= 2 else 0.38 if board >= 1 else 0.18
            elif kind == "butterfly" and context.main_plot == "change":
                impact = 0.76
            self._add(items, f"incident:{day}:{kind}:{culprit_id}", impact,
                      progress * deadline,
                      f"第 {day} 天事件；当事人不安 {culprit.paranoia}/{limit}")

    def evaluate(self, game: SearchGame) -> PositionEvaluation:
        if game.winner is not None:
            value = 1.0 if game.winner == "mastermind" else -1.0
            report = PositionEvaluation(
                value, self.context_for(game.scenario).key, True,
                (EvaluationContribution("terminal", value, 1.0,
                                        f"胜者：{game.winner}"),))
            self.last_report = report
            return report
        context = self.context_for(game.scenario)
        if context.module not in self.SUPPORTED_MODULES:
            value = self.fallback(game)
            report = PositionEvaluation(value, context.key, True, (
                EvaluationContribution("fallback", value, 1.0,
                                       f"{context.module} 尚未迁移到剧本条件化估值"),))
            self.last_report = report
            return report

        items: list[EvaluationContribution] = []
        features = PositionFeatures.extract(game)
        self._main_plot(game, context, items)
        self._role_routes(game, context, items)
        self._incident_routes(game, context, items)

        if "rumor" in context.subplots and "plot:rumor" not in game.loop_used:
            self._add(items, "plot:rumor_available", 0.06, 1.0,
                      "流言四起本轮尚可使用")
        if "virus" in context.subplots:
            best = max((_threshold_progress(c.paranoia, 3)
                        for cid, c in game.state.characters.items()
                        if game.roles[cid] == "ordinary" and c.alive), default=0.0)
            self._add(items, "plot:virus", 0.20, best,
                      "平民接近转化为杀人狂")
        if "threads" in context.subplots and game.state.loop < context.loops:
            friendly = sum(c.goodwill > 0 for c in game.state.characters.values()
                           if c.present)
            self._add(items, "plot:threads", 0.08,
                      min(1.0, friendly / 2),
                      f"若本轮失败，下轮有 {friendly} 名角色获得不安")

        protagonist_resources = sum(
            c.goodwill for c in game.state.characters.values()
            if c.present and c.alive)
        if protagonist_resources:
            items.append(EvaluationContribution(
                "defense:goodwill", -min(0.14, protagonist_resources * 0.012),
                min(1.0, protagonist_resources / 12),
                f"主人公共有友好 {protagonist_resources}"))
        if getattr(game, "protected", False):
            items.append(EvaluationContribution(
                "defense:protection", -0.10, 1.0, "主人公保护效果生效"))
        if context.loops > 1 and features.loop > 1:
            self._add(items, "match:loops_spent", 0.14,
                      (features.loop - 1) / (context.loops - 1),
                      f"已进入第 {features.loop}/{context.loops} 轮")
        if features.phase == "loop_end" and getattr(game, "loss_reasons", ()):
            self._add(items, "match:current_loop_lost", 0.18, 1.0,
                      "当前轮回已经失败")
        knowledge = features.known_roles + features.known_culprits + features.known_plots
        if knowledge:
            items.append(EvaluationContribution(
                "defense:knowledge", -min(0.15, knowledge * 0.025),
                min(1.0, knowledge / 6), f"主人公已确认 {knowledge} 项隐藏信息"))

        raw = sum(item.value for item in items)
        value = max(-0.92, min(0.92, math.tanh(raw)))
        report = PositionEvaluation(
            value=value, context_key=context.key,
            stable=features.phase not in self._UNSTABLE_PHASES,
            contributions=tuple(sorted(items, key=lambda item: abs(item.value),
                                       reverse=True)),
        )
        self.last_report = report
        return report

    def __call__(self, game: SearchGame) -> float:
        return self.evaluate(game).value
