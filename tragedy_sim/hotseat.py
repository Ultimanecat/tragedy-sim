"""Display-independent hotseat controller and public text formatting.

The engine remains the only rules authority. A seat must explicitly open its
private panel; handoff, hiding and loading invalidate all old UI callbacks.
This is a local privacy curtain, not authentication against a malicious user.
"""

from .cards import ACTOR_NAMES, LOCATIONS, deck
from .catalog import INCIDENT_NAMES, INCIDENT_RULES, MODULES, PLOTS, PLOT_RULES, ROLE_NAMES, ROLE_RULES
from .engine import RuleError
from .game import Game


PHASE_NAMES = {
    "day_start": "日初", "mastermind": "剧作家出牌", "protagonists": "主人公出牌",
    "reveal": "统一揭示", "action_counters": "行动结算", "master_abilities": "剧作家能力",
    "goodwill": "友好能力", "refusal": "确认友好能力", "incident": "事件结算",
    "decision": "必要目标选择", "day_end": "日末结算", "loop_end": "轮回之间",
    "final_guess": "最终猜测", "game_over": "对局结束",
}
NEXT_LABELS = {
    "day_start": "开始今天的行动", "action_counters": "结束能力窗口，结算行动牌",
    "master_abilities": "结束剧作家能力阶段", "goodwill": "结束友好能力阶段",
    "incident": "检查并结算今日事件", "day_end": "结束今天，检查胜负",
    "loop_end": "开始下一轮回",
}


class HotseatSession:
    def __init__(self, game=None):
        self.game = game if game is not None else Game()
        self.seat = None
        self.intent = None
        self.token = 0
        self.saved_commands = len(self.game.history)

    @property
    def expected_seat(self):
        return self.game.state.leader if self.intent == "final" else self.game.controller

    @property
    def dirty(self):
        return len(self.game.history) != self.saved_commands

    def hide(self):
        self.seat = None
        self.token += 1

    def unlock(self, seat):
        if seat is None or seat != self.expected_seat:
            raise RuleError("只能由当前等待的座位打开操作区")
        self.seat = seat
        self.token += 1

    def public_view(self):
        # Never use the open private seat to render the shared board or journal.
        return self.game.view("spectator")

    def private_view(self):
        if self.seat is None or self.seat != self.expected_seat:
            return None
        return self.game.view(self.seat)

    def options(self):
        if self.private_view() is None or self.intent:
            return []
        return self.game.options(self.seat)

    def legal_targets(self):
        view = self.private_view()
        if view is None or view["phase"] not in ("mastermind", "protagonists"):
            return []
        occupied = {p["target"] for p in view["pending"] if (p["actor"] == "m") == (self.seat == "m")}
        return [t for t in [*view["characters"], *LOCATIONS]
                if t not in occupied and (t in LOCATIONS or view["characters"][t]["alive"])]

    def act(self, token, action, **args):
        if token != self.token or self.private_view() is None:
            raise RuleError("操作区已经遮挡或状态已改变，请重新确认当前座位")
        if (self.intent == "final") != (action == "final"):
            raise RuleError("请先完成或取消当前交接")
        previous_seat = self.seat
        self.game.dispatch(self.seat, action, **args)
        self.intent = None
        self.token += 1
        if self.game.controller != previous_seat:
            self.hide()

    def request_final_guess(self):
        view = self.public_view()
        if not module_capability(view, "early_final_guess") or view["phase"] != "loop_end":
            raise RuleError("当前规则集或阶段不允许提前最终猜测")
        self.intent = "final"
        self.hide()

    def cancel_final_guess(self):
        self.intent = None
        self.hide()

    def replace(self, game):
        self.game = game
        self.intent = None
        self.saved_commands = len(game.history)
        self.hide()

    def save(self, path):
        self.game.save(path)
        self.saved_commands = len(self.game.history)


def target_name(view, target):
    return view["characters"][target]["name"] if target in view["characters"] else LOCATIONS[target]


def module_capability(view, name):
    """Read public engine capabilities, with catalog fallback for old saves."""
    capabilities = view.get("capabilities", {})
    if name in capabilities:
        return bool(capabilities[name])
    if name in view:
        return bool(view[name])
    return bool(getattr(MODULES[view["module"]], name))


def module_roles(module):
    """Return exactly the identities players know may appear in a module."""
    spec = MODULES[module]
    roles = {"ordinary"}
    for plot in spec.plots:
        roles.update(PLOTS[plot][2])
    if "hideous" in spec.plots:
        roles.add("curmudgeon")
    return tuple(role for role in ROLE_NAMES if role in roles)


def public_log(view):
    lines = []
    for event in view["events"]:
        lines.append(f"轮回 {event['loop']} · 第 {event['round']} 天   {event['message']}")
        if event["kind"] == "cards_revealed":
            for p in event["cards"]:
                lines.append(f"    {ACTOR_NAMES[p['actor']]}：{deck(p['actor'])[p['card']].name} → {target_name(view, p['target'])}")
    return "\n".join(lines)


def public_knowledge(view):
    lines = ["已公开的信息会跨轮回保留；历史身份不一定等于当前身份。", ""]
    for cid, fact in view["known_roles"].items():
        lines.append(f"{target_name(view, cid)}：{ROLE_NAMES[fact['role']]}（轮回 {fact['loop']} / 第 {fact['day']} 天确认）")
    for day, cid in view["known_culprits"].items():
        lines.append(f"第 {day} 天事件当事人：{target_name(view, cid)}")
    for plot in view["known_plots"]:
        lines.append(f"已公开规则 X：{PLOTS[plot][0]}")
    if len(lines) == 2:
        lines.append("尚未公开身份、当事人或实际规则。")
    lines += ["", "公开留置的限次牌"]
    for actor, cards in view["discarded"].items():
        lines.append(f"{ACTOR_NAMES[actor]}：" + ("、".join(deck(actor)[c].name for c in cards) or "无"))
    lines += ["", "能力使用记录（只列公开声明）"]
    used = sorted(set(view["ability_day_used"]) | set(view["ability_loop_used"]))
    for key in used:
        _, cid, aid = key.split(":")
        a = next(a for a in view["characters"][cid]["abilities"] if a["id"] == aid)
        limit = "本轮限次已使用" if key in view["ability_loop_used"] else "今日已使用"
        lines.append(f"{target_name(view, cid)}：{a['text']}（{limit}）")
    if not used:
        lines.append("暂无。")
    if view["protected"]:
        lines += ["", "保护：本轮主人公不会死亡，但仍可能触发其他失败条件。"]
    return "\n".join(lines)


def character_details(view, cid):
    c = view["characters"][cid]
    lines = [f"{c['name']}  ·  {' / '.join(c['traits'])}",
             f"初始：{LOCATIONS[c['initial_location']]}　当前：{LOCATIONS[c['location']]}",
             f"禁行：{'、'.join(LOCATIONS[t] for t in c['forbidden']) or '无'}",
             f"{'存活' if c['alive'] else '尸体'}　友好 {c['goodwill']}　不安临界 {c['paranoia']}/{c['paranoia_limit']}　密谋 {c['intrigue']}　护卫 {c['guard']}", ""]
    for a in c["abilities"]:
        limit = "每轮一次" if a["once"] else "每日一次"
        lines.append(f"友好 ≥{a['threshold']} · {limit}\n{a['text']}\n")
    if not c["abilities"]:
        lines.append("没有友好能力。")
    if c["passive"]:
        lines.append("被动特性：" + c["passive"])
    return "\n".join(lines)


def public_rules(module):
    spec = MODULES[module]
    lines = [f"{module} / {spec.name} 公开速查表 · 列出所有可能项，不是剧本答案", "",
             f"剧本结构：1 个规则 Y + {spec.subplot_count} 个规则 X · "
             f"可用角色 {len(spec.characters)} 名 · 可用事件 {len(spec.incidents)} 种", "",
             "每日：出牌 → 揭示与移动 → 其余行动 → 剧作家能力 → 友好能力 → 事件 → 换领队 → 日末。",
             "友好不消耗；被拒绝也计次数。禁止牌不限制能力/事件；两张以上禁止密谋全场失效。",
             "角色或主人公死亡可能立即结束轮回，但亲友等轮回结束效果仍须结算。"]
    if spec.final_guess:
        extra = "，也可在轮回之间提前进入" if spec.early_final_guess else ""
        lines += [f"轮回耗尽后猜全部初始身份{extra}；全部正确才获胜，错误一次即失败。", ""]
    else:
        lines += ["不使用最终猜测；轮回全部失败时剧作家获胜。", ""]
    roles = set(module_roles(module))
    for plot in spec.plots:
        name, group, counts = PLOTS[plot]
        lines += [f"规则 {group} · {name}", "身份：" + ("、".join(f"{ROLE_NAMES[r]} ×{n}" for r, n in counts.items()) or "无固定身份"), PLOT_RULES[plot], ""]
    lines += ["多个规则的身份数量相加，再按身份上限截断。"]
    if spec.role_caps:
        lines.append("身份人数上限：" + "、".join(f"{ROLE_NAMES[r]} ×{n}" for r, n in spec.role_caps.items()) + "。")
    if spec.friend_gender_split:
        lines.append("两名亲友同时登场时，必须一名男性、一名女性。")
    lines.append("")
    for role in module_roles(module):
        lines += [ROLE_NAMES[role] + "：" + ROLE_RULES[role], ""]
    lines += ["事件：当事人存活且不安达临界时发生；没有有效目标也算发生。", ""]
    for kind in spec.incidents:
        lines += [INCIDENT_NAMES[kind] + "：" + INCIDENT_RULES[kind], ""]
    for actor, name in (("m", "剧作家"), ("a", "每位主人公")):
        lines.append(name + "固定初始牌组（不是当前手牌）")
        lines.extend(c.name + (" · 每轮一次" if c.once_per_loop else "") for c in deck(actor).values())
        lines.append("")
    return "\n".join(lines)


def secret_dossier(view):
    if "secret" not in view:
        raise RuleError("该视角没有剧作家资料")
    s = view["secret"]
    lines = ["只供剧作家阅读 · 换人前请遮挡", "", "规则 Y：" + PLOTS[s["main_plot"]][0],
             PLOT_RULES[s["main_plot"]], ""]
    for p in s["subplots"]:
        lines += ["规则 X：" + PLOTS[p][0], PLOT_RULES[p], ""]
    for cid, role in s["roles"].items():
        lines += [f"{target_name(view, cid)}：{ROLE_NAMES[role]}（初始 {ROLE_NAMES[s['initial_roles'][cid]]}）", ROLE_RULES[role], ""]
    lines.append("事件当事人")
    for item in s["incidents"]:
        lines.append(f"第 {item['day']} 天 · {INCIDENT_NAMES[item['kind']]}：{target_name(view, item['culprit'])}")
    if s["loss_reasons"]:
        lines += ["", "累计失败诊断：" + "；".join(s["loss_reasons"])]
    if s["ability_day_used"]:
        lines += ["", "完整日内使用记录：" + "、".join(s["ability_day_used"])]
    if s["ability_loop_used"]:
        lines += ["", "完整轮内限次记录：" + "、".join(s["ability_loop_used"])]
    return "\n".join(lines)
