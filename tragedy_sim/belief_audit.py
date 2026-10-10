"""Opt-in, read-only developer evidence deltas and Chinese explanations."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass, field
import json

from .i18n import format_timepoint, label


def describe_witness(witness):
    """Describe a constraint without turning sample frequencies into certainty."""
    character = lambda cid: label("characters", str(cid))
    role = lambda rid: label("roles", str(rid))
    names = lambda cids: "、".join(character(cid) for cid in cids)
    kind, subject, value = witness.kind, witness.subject, witness.value
    if kind == "role_is":
        suffix = "（病毒下还需检查初始平民解释）" if value == "serial" else ""
        return f"{character(subject)}身份约束：{role(value)}{suffix}"
    if kind == "culprit_is":
        return f"第{subject}天事件当事人：{character(value)}"
    if kind == "culprit_in":
        return f"第{subject}天事件当事人位于候选集合：{names(value)}"
    if kind in {"role_in", "role_not_in"}:
        relation = "属于" if kind == "role_in" else "不属于"
        return f"{character(subject)}身份{relation}：{'、'.join(role(r) for r in value)}"
    if kind in {"plot_present", "plot_not_present", "plot_pressure"}:
        relation = {"plot_present": "存在剧情", "plot_not_present": "排除剧情",
                    "plot_pressure": "支持剧情"}[kind]
        return f"{relation}：{label('plots', str(subject))}"
    if kind == "role_pressure":
        return f"{names(value.get('candidates', ()))}中有人为{role(subject)}"
    if kind == "joint_plot_role_pressure":
        return (f"联合支持{label('plots', str(subject))}，以及"
                f"{names(value.get('candidates', ()))}中有人为{role(value.get('role'))}")
    if kind in {"role_route_pressure", "mastermind_ability_route"}:
        routes = value if kind == "role_route_pressure" else value.get("roles", {})
        alternatives = [f"{names(cids)}中有人为{role(rid)}" for rid, cids in routes.items()]
        if kind == "mastermind_ability_route":
            alternatives.extend(f"存在{label('plots', str(plot))}" for plot in value.get("plots", ()))
        return "至少一条来源路线成立：" + "；或 ".join(alternatives)
    if kind == "mandatory_serial_route":
        return (f"强制死亡来源：{names(value.get('serial', ()))}中的杀人狂；"
                f"或病毒使{names(value.get('virus_ordinary', ()))}中的平民转化")
    if kind == "loop_end_plot_explanation":
        boards = "、".join(f"{label('locations', cid)}={amount}" for cid, amount in
                          value.get("location_intrigue", {}).items() if amount)
        characters = "、".join(f"{character(cid)}={amount}" for cid, amount in
                              value.get("character_intrigue", {}).items() if amount)
        return f"普通轮回末失败须有主规则解释；地点密谋[{boards}]，角色密谋[{characters}]"
    if kind in {"incident_happened", "incident_not_happened"}:
        status = "发生" if kind == "incident_happened" else "未发生"
        return f"第{subject}天{label('incidents', value.get('kind', ''))}{status}；核对公开当事人阈值"
    if kind == "day_end_death_companion":
        companion = value.get("character") if isinstance(value, dict) else value
        virus = "，保留病毒平民转化解释" if isinstance(value, dict) and value.get("virus_eligible") else ""
        return f"{character(subject)}日末死亡，支持其同伴{character(companion)}为杀人狂{virus}"
    if kind == "day_end_killer_candidate":
        return f"{character(subject)}日末死亡，支持其为关键人物、同伴{character(value)}为杀手"
    if kind == "loss_after_death":
        factor = "／获得关键能力的不安定因子" if isinstance(value, dict) and value.get("factor_key_possible") else ""
        return f"{character(subject)}死亡后轮回失败，支持关键人物／亲友{factor}等解释，保留歧义"
    return f"{kind}({character(subject)})：{json.dumps(value, ensure_ascii=False, sort_keys=True)}"


def _key(witness):
    value = [witness.kind, witness.subject, witness.value, witness.source, witness.strength]
    # These mirrors describe persistent public knowledge, not a new observation
    # every time the caller advances the day or phase.
    if witness.source not in {"public_role_reveal", "public_culprit_reveal", "public_plot_reveal"}:
        value.extend((witness.loop, witness.day, witness.timing))
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


@dataclass
class BeliefAuditTrail:
    """Independent telemetry: no RNG, hypotheses, evaluator or player output."""
    entries: list[dict] = field(default_factory=list)
    _counts: Counter = field(default_factory=Counter, repr=False)
    _facts: dict = field(default_factory=dict, repr=False)
    _module: str = field(default="", repr=False)

    def observe(self, view, witnesses):
        module = str(view.get("module", ""))
        reset = bool(self._module and module != self._module)
        if reset:
            self._counts.clear()
            self._facts.clear()
        counts = Counter(_key(w) for w in witnesses)
        facts = {_key(w): w for w in witnesses}
        changes = []
        for key in dict.fromkeys((*facts, *self._facts)):
            delta = counts[key] - self._counts[key]
            if delta:
                witness = facts.get(key, self._facts.get(key))
                operation = ("confirmed" if delta > 0 and self._counts[key] else
                             "added" if delta > 0 else "removed")
                changes.append({"operation": operation,
                                "observations": abs(delta), "witness": asdict(witness),
                                "description": describe_witness(witness)})
        if changes or reset:
            self.entries.append({"module": module, "loop": view.get("loop", 1),
                                 "day": view.get("round", 1), "phase": view.get("phase"),
                                 "timing": view.get("timing", view.get("phase", "unknown")),
                                 "event_cursor": len(view.get("events", ())),
                                 "module_reset": reset, "changes": changes})
        self._module, self._counts, self._facts = module, counts, deepcopy(facts)

    def record_samples(self, view, role_counts, culprit_options, world_count, *,
                       culprit_counts=(), dark_counts=(), placement_tendencies=(),
                       witnesses=(), role_assignments=(), sampled_setups=()):
        self.entries.append({"module": str(view.get("module", "")),
                             "loop": view.get("loop", 1), "day": view.get("round", 1),
                             "phase": view.get("phase"), "timing": view.get("timing", "unknown"),
                             "event_cursor": len(view.get("events", ())),
                             "module_reset": False, "changes": [],
                             "sampled_roles": deepcopy(role_counts),
                             "culprit_options": deepcopy(culprit_options),
                             "sampled_culprits": deepcopy(culprit_counts),
                             "sampled_dark_cards": deepcopy(dark_counts),
                             "placement_tendencies": deepcopy(placement_tendencies),
                             "world_count": world_count})
        if view.get("characters") and view.get("module") in {"FS", "BTX"}:
            from .belief_matrix import BeliefMatrixProjection
            try:
                projection = BeliefMatrixProjection.from_view(
                    view, witnesses, role_counts=role_counts,
                    culprit_counts=culprit_counts, dark_counts=dark_counts,
                    role_assignments=role_assignments, sampled_setups=sampled_setups)
            except ValueError as error:
                # Telemetry must not alter a completed AI decision. Record
                # projection failures without loosening inference constraints.
                self.entries[-1]["belief_matrix_error"] = str(error)
                return
            self.entries[-1]["belief_matrix"] = projection.to_dict()
            self.entries[-1]["belief_matrix_text"] = projection.to_text()

    def to_text(self):
        lines = ["AI 信念证据变化（开发日志）", "硬＝确定约束；软＝支持线索，不等于确定身份。"]
        for entry in self.entries:
            point = format_timepoint(str(entry["timing"]), int(entry["loop"]), int(entry["day"]))
            lines.append(f"\n[第{entry['loop']}轮 · {point}] 观察至事件 {entry['event_cursor']}（阶段 {entry['phase']}）")
            if entry["module_reset"]:
                lines.append("规则集变化，清空旧证据比较基线。")
            for change in entry["changes"]:
                witness = change["witness"]
                strength = "硬" if witness["strength"] == "hard" else "软"
                operation = {"added": "新增", "removed": "移除", "confirmed": "再次观察"}[change["operation"]]
                origin = format_timepoint(witness["timing"], witness["loop"], witness["day"])
                lines.append(f"  {operation}{strength} ×{change['observations']}：{change['description']}"
                             f"（证据时间：第{witness['loop']}轮 · {origin}；来源：{witness['source']}）")
            if "sampled_roles" in entry:
                lines.append(f"  采样世界 {entry['world_count']} 个；以下是样本频率，不是完整后验概率：")
                for row in entry["sampled_roles"]:
                    values = "、".join(f"{label('roles', rid)} {count}" for rid, count in row["counts"].items())
                    lines.append(f"    {label('characters', row['character'])}：{values}")
                for day, options in entry["culprit_options"].items():
                    names = "、".join(label("characters", cid) for cid in options) or "无相容候选"
                    lines.append(f"    第{day}天当事人硬约束候选：{names}")
                for row in entry["sampled_culprits"]:
                    values = "、".join(f"{label('characters', cid)} {count}" for cid, count in row["counts"].items())
                    lines.append(f"    第{row['day']}天当事人样本：{values}")
                for row in entry["sampled_dark_cards"]:
                    values = "、".join(f"{label('cards', card)} {count}" for card, count in row["counts"].items())
                    lines.append(f"    暗牌槽{row['slot'] + 1}→{label('characters', row['target'])}：{values}")
                for row in entry["placement_tendencies"]:
                    values = "、".join(f"{label('cards', card)} {weight:.1%}" for card, weight in
                                      row["card_probabilities"].items())
                    lines.append(f"    历史出牌模型→{label('characters', row['target'])}：{values}")
                if "belief_matrix_text" in entry:
                    lines.append(entry["belief_matrix_text"])
                if "belief_matrix_error" in entry:
                    lines.append("信念矩阵投影错误：" + entry["belief_matrix_error"])
        return "\n".join(lines) + "\n"
