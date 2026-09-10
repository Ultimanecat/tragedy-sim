"""Human-operated matches and an independent action-card practice mode."""

import argparse
import shlex
import sys

from .cards import ACTOR_NAMES, LOCATIONS, deck
from .catalog import MODULES
from .engine import ActionGame, RuleError

PHASES = {"mastermind": "剧作家出牌", "protagonists": "主人公出牌",
          "reveal": "等待揭示", "resolved": "行动结算完成"}


def _supported_modules(capability: str) -> tuple[str, ...]:
    return tuple(module for module, spec in MODULES.items() if getattr(spec, capability))


HELP = """
board                         公开棋盘、暗牌目标、限次牌留置区
hand <玩家>                   该玩家手牌（m 剧作家，a/b/c 主人公）
play <玩家> <牌> <目标>        例如 play m i2 doctor
view <玩家|spectator>         查看该玩家自己的暗牌；不显示他人的暗牌
resolve                       本日双方牌数齐全后统一揭示并结算
log                           查看本次练习的公开日志
next                          练习控制：保留棋盘，轮换领队，开始下一次出牌
reset                         练习控制：恢复初始棋盘和所有牌，开始新轮回
help                          显示命令
quit                          退出

地图：hospital 医院 | shrine 神社
      city     都市 | school 学校
角色：student 男学生、doctor 医生、maiden 巫女、worker 职员、patient 住院患者

练习模式仅实现基础行动牌。没有能力、身份、事件、胜负或机器人。
本地热座/调试模式：允许操作者查看各方手牌，终端历史不提供安全隔离。
"""


def _report_gui_error(message):
    """Report startup failures even when a Windows GUI launcher has no console."""
    stream = sys.stderr or sys.stdout
    if stream is not None:
        print(message, file=stream)
        return
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "悲剧轮回", 0x10)
        except (AttributeError, OSError):
            pass


def _load_gui_main():
    # Keep tkinter out of the console CLI and the installed GUI bootstrap.
    from .gui import main as entrypoint
    return entrypoint


def gui_main(argv=None):
    try:
        entrypoint = _load_gui_main()
    except ImportError as exc:
        if exc.name not in ("tkinter", "_tkinter"):
            raise
        _report_gui_error("此 Python 没有安装 Tk，无法启动 GUI。请安装包含 Tcl/Tk 的 Python，或继续使用命令行。")
        return 1
    return entrypoint(argv, error_reporter=_report_gui_error)


def board(game: ActionGame, viewer: str = "spectator") -> None:
    view = game.view(viewer)
    print(f"\n{view['module']} 出牌练习 | 轮回 {view['loop']} | 第 {view['round']} 次出牌 | "
          f"{PHASES[view['phase']]} | 领队 {view['leader']}")
    for loc, name in LOCATIONS.items():
        print(f"  {loc} {name}（密谋 {view['locations'][loc]}）")
        for char in view["characters"].values():
            if char["location"] == loc:
                mind = f" / 希望 {char['hope']} / 绝望 {char['despair']}" if game.module in ("AHR", "LL") else ""
                print(f"    {char['id']:<9} {char['name']}：友好 {char['goodwill']} / "
                      f"不安 {char['paranoia']} / 密谋 {char['intrigue']}{mind}"
                      + (" [死亡]" if not char["alive"] else ""))
    for p in view["pending"]:
        label = deck(p["actor"], game.module)[p["card"]].name if p["card"] else "暗牌"
        print(f"  {ACTOR_NAMES[p['actor']]} → {p['target']}：{label}")
    for actor, discarded in view["discarded"].items():
        if discarded:
            print(f"  {actor} 公开留置：" + ", ".join(discarded))
    if game.next_actor:
        print(f"  下一位：{ACTOR_NAMES[game.next_actor]} ({game.next_actor})")


def events(game: ActionGame, start: int = 0) -> None:
    for event in game.view(language=getattr(game, "language", "zh"))["events"][start:]:
        print(f"  [{event['timepoint']}] {event['message']}")
        if event["kind"] == "cards_revealed":
            for p in event["cards"]:
                print(f"    {ACTOR_NAMES[p['actor']]}：{deck(p['actor'])[p['card']].name} → {game.name(p['target'])}")


def demo(module: str, language="zh") -> int:
    game = ActionGame(module=module)
    game.language = language
    print("演示：相同方向只移动一次；一张禁止密谋有效；友好直接增加。")
    placements = [("m", "h", "student"), ("m", "i2", "hospital"),
                  ("m", "p1a", "doctor"), ("a", "h", "student"),
                  ("b", "fi", "hospital"), ("c", "g2", "doctor")]
    for actor, card, target in placements:
        game.play(actor, card, target)
    board(game)
    start = len(game.state.events)
    game.resolve()
    events(game, start)
    board(game)
    if (game.state.characters["student"].location != "city" or game.state.locations["hospital"] != 0
            or game.state.characters["doctor"].goodwill != 2):
        raise RuntimeError("演示结果与预期不一致")
    print("\n演示完成，停在行动结算完成阶段。")
    return 0


def practice_main(argv: list[str] | None = None) -> int:
    # Windows redirected stdout otherwise uses the legacy code page and garbles Chinese.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="悲剧轮回基础出牌练习器")
    parser.add_argument("--module", choices=_supported_modules("cli_supported"), default="FS",
                        help="选择规则集；练习模式只结算各规则集共用的基础行动牌")
    parser.add_argument("--lang", choices=("zh", "en", "ja"), default="zh", help="术语与时间点语言")
    parser.add_argument("--demo", action="store_true", help="自动演示一次双方出牌及结算")
    args = parser.parse_args(argv)
    if args.demo:
        return demo(args.module, args.lang)
    game = ActionGame(module=args.module)
    game.language = args.lang
    print(HELP)
    board(game)
    while True:
        try:
            parts = input(f"\n[{game.next_actor or game.state.phase}] > ").split()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            return 0
        if not parts:
            continue
        command, *values = parts
        try:
            counts = {"board": 0, "hand": 1, "play": 3, "view": 1, "resolve": 0,
                      "log": 0, "next": 0, "reset": 0, "help": 0, "quit": 0}
            if command not in counts or len(values) != counts[command]:
                raise RuleError("命令或参数数量错误，请输入 help")
            start = len(game.state.events)
            if command == "quit":
                return 0
            if command == "help":
                print(HELP)
            elif command == "board":
                board(game)
            elif command == "view":
                board(game, values[0])
            elif command == "hand":
                for cid in game.view(values[0])["hand"]:
                    card = deck(values[0])[cid]
                    print(f"  {cid:<4} {card.name}" + (" [每轮回限一次]" if card.once_per_loop else ""))
            elif command == "play":
                game.play(*values)
            elif command == "resolve":
                game.resolve()
            elif command == "next":
                game.next_round()
            elif command == "reset":
                game.reset_loop()
            elif command == "log":
                events(game)
            if command in ("play", "resolve", "next", "reset"):
                events(game, start)
                print("当前阶段：" + PHASES[game.state.phase])
                if game.next_actor:
                    print("下一位：" + ACTOR_NAMES[game.next_actor])
        except ValueError as exc:
            print(f"无法执行：{exc}")


MATCH_PHASES = {**PHASES, "day_start": "日初", "action_counters": "行动结算能力窗口",
                "master_abilities": "剧作家能力", "goodwill": "友好能力", "refusal": "确认友好能力结算",
                "incident": "事件", "decision": "等待必要选择", "day_end": "日末可选能力",
                "loop_end": "轮回之间", "final_guess": "最终猜测", "game_over": "游戏结束"}
MATCH_HELP = """
board / status                公开棋盘、事件日程、历史确认信息、保护及能力使用情况
hand <m|a|b|c>                查看指定座位手牌（m 的手牌属于私密信息）
play <座位> <牌ID> <目标ID>    暗置行动牌；本日所需牌数和主人公顺序显示在棋盘提示中
resolve                       统一揭示，先结算移动，进入行动能力窗口
options <座位>                当前合法能力/选择；options m 是剧作家私密窗口
choose <座位> <编号>          执行 options 中的选择（编号随状态变化）
next [座位]                   按顺序进入下一阶段；有必要选择时不能跳过
inspect <角色ID>              查看角色全部公开属性、能力及合法使用条件
rules                         查看当前模组的所有可能规则/身份/事件（不是剧本答案）
view <座位|spectator>         棋盘视角；view m 会显示剧本秘密，仅剧作家查看
log                           回看完整公开结算日志
guess <座位> <角色> <身份ID>   支持最终猜测的规则集：为每个角色回答初始身份
final <领队>                  规则集允许时，在轮回之间放弃余下轮回并最终猜测
save <新文件路径>             保存完整对局（含秘密，不要在对局中分享）
replay <新文件路径>           对局结束后导出纯文本完整信息回放（推荐 .tlr）
help / quit                   帮助 / 退出；恢复存档用 --load <路径>

本地热座/裁判工具，不是 AI 对手：由真人控制 m/a/b/c，单人也可调试全部座位。
默认界面只显示公开信息。私密命令和终端历史仍可能泄露秘密，换人时请隔离屏幕。
"""


def match_board(game, viewer="spectator"):
    from .catalog import PLOTS, ROLE_NAMES
    v = game.view(viewer)
    print(f"\n【{v['title']} / {v['module']}】轮回 {v['loop']}/{v['loops']}，"
          f"第 {v['round']}/{v['days']} 天 · {MATCH_PHASES[v['phase']]}")
    print(f"领队：{ACTOR_NAMES[v['leader']]}；桌面讨论：{'允许' if v['table_talk'] else '出牌中不允许（真人遵守）'}")
    if v["module"] in ("MC", "WM", "AHR"):
        detail = ("本轮已发生事件计数；猎奇杀人 +2，银色子弹 +0"
                  if v["module"] == "MC" else
                  "跨轮回保留；驱动旧日支配者与规则能力" if v["module"] == "WM" else
                  f"偶数为表世界、奇数为里世界；当前为{'表' if v['world'] == 'surface' else '里'}世界")
        print(f"Ex 槽：{v['ex_gauge']}（{detail}）")
    if v["winner"]:
        winner = ("主人公" if v["winner"] == "protagonists" else "剧作家"
                  if v["winner"] == "mastermind" else
                  f"背叛者（{ACTOR_NAMES[v['winner'].split(':')[1]]}）")
        print("胜方：" + winner)
    for loc, label in LOCATIONS.items():
        board_counter = "尸体标记" if v["module"] == "HSA" else "密谋"
        curse = (f" · 诅咒牌={v['board_ex'][loc]}"
                 if v["module"] == "HSA" and v["board_ex"][loc] else "")
        print(f"  {label} [{loc}] {board_counter}={v['locations'][loc]}{curse}")
        for c in v["characters"].values():
            if c["location"] == loc:
                panic = " 达临界" if c["alive"] and c["paranoia"] >= c["paranoia_limit"] else ""
                special = "诅咒牌" if v["module"] == "HSA" else "Ex牌"
                ex = f" · {special} {c.get('ex_cards', 0)}" if c.get("ex_cards", 0) else ""
                mind = f" · 希望 {c['hope']} · 绝望 {c['despair']}" if v["module"] in ("AHR", "LL") else ""
                tokens = ((" · 交友完毕" if c.get("friended_token") else "")
                          + (" · 死亡完毕" if c.get("death_token") else ""))
                print(f"    {c['name']} [{c['id']}] {'存活' if c['alive'] else '尸体'} | "
                      f"友好 {c['goodwill']} · 不安 {c['paranoia']}/{c['paranoia_limit']}{panic} · "
                      f"密谋 {c['intrigue']}{mind} · 护卫 {c['guard']}{ex}{tokens}")
    for p in v["pending"]:
        label = deck(p["actor"], game.module)[p["card"]].name if p["card"] else "暗牌"
        print(f"  {ACTOR_NAMES[p['actor']]} → {game.name(p['target'])}：{label}")
    for actor, cards in v["discarded"].items():
        if cards:
            print(f"  {ACTOR_NAMES[actor]}公开留置：" + "、".join(
                f"{deck(actor, game.module)[c].name}[{c}]" for c in cards))
    records = {r["day"]: r for r in v["incidents"]}
    from .catalog import INCIDENT_NAMES
    print("事件日程：")
    for day in range(1, v["days"] + 1):
        item = next((i for i in v["schedule"] if i["day"] == day), None)
        if item:
            r = records.get(day)
            status = "未结算" if r is None else ("发生" if r["happened"] else "未发生")
            if r and r["happened"] and not r["effective"]:
                status += "；结算中" if game.state.phase == "decision" and day == v["round"] else "；无效果"
            board = f"·{LOCATIONS[item['board']]}" if "board" in item else ""
            print(f"  第 {day} 天：{INCIDENT_NAMES[item['kind']]}{board}（{status}）")
        else:
            print(f"  第 {day} 天：无预定事件")
    for cid, fact in v["known_roles"].items():
        verb = "公开宣称" if v["module"] == "MZ" else "历史确认"
        print(f"{verb}：{game.name(cid)} → {ROLE_NAMES[fact['role']]}（轮回 {fact['loop']} / 第 {fact['day']} 天）")
    for day, cid in v["known_culprits"].items():
        print(f"已公开：第 {day} 天事件当事人是{game.name(cid)}。")
    for plot in v["known_plots"]:
        print(f"已公开规则 X：{PLOTS[plot][0]}")
    if v["protected"]:
        print("公开保护：本轮主人公不会死亡，但仍可能因其他条件失败。")
    for lock in v.get("sealed_boards", []):
        print(f"公开封锁：{LOCATIONS[lock['board']]}至第 {lock['through']} 天不能通过移动进入或离开。")
    for cid, day in v.get("movement_locks", {}).items():
        if day == v["round"]:
            print(f"公开限制：{game.name(cid)}今天不能移动。")
    for key in sorted(set(v["ability_day_used"]) | set(v["ability_loop_used"])):
        _, cid, aid = key.split(":")
        when = "今日已声明" if key in v["ability_day_used"] else "本轮已声明"
        print(f"{when}能力：{game.name(cid)} / {aid}" + ("（本轮限次已使用）" if key in v["ability_loop_used"] else ""))
    if "secret" in v:
        print("【剧作家私密信息 · 请勿向主人公展示】")
        secret = v["secret"]
        print("规则 Y：" + PLOTS[secret["main_plot"]][0])
        print("规则 X：" + "、".join(PLOTS[p][0] for p in secret["subplots"]))
        for cid, role in secret["roles"].items():
            print(f"  {game.name(cid)}：{ROLE_NAMES[role]}（初始 {ROLE_NAMES[secret['initial_roles'][cid]]}）")
        for i in secret["incidents"]:
            public_name = f"，公开名 {INCIDENT_NAMES[i['public_kind']]}" if "public_kind" in i else ""
            print(f"  第 {i['day']} 天{INCIDENT_NAMES[i['kind']]}{public_name}当事人：{game.name(i['culprit'])}")
        if secret["ability_day_used"]:
            print("  私密完整日内使用记录：" + "、".join(secret["ability_day_used"]))
        if secret["ability_loop_used"]:
            print("  私密完整轮内限次记录：" + "、".join(secret["ability_loop_used"]))
    hint(game)


def hint(game):
    phase, actor = game.state.phase, game.controller
    if phase in ("mastermind", "protagonists"):
        view = game.view()
        if phase == "mastermind":
            played = sum(p.actor == "m" for p in game.state.pending)
            progress = f"剧作家本日 {played}/{view['action_counts']['mastermind']} 张"
        else:
            played = sum(p.actor != "m" for p in game.state.pending)
            order = " → ".join(ACTOR_NAMES[seat] for seat in view["protagonist_order"])
            progress = f"主人公本日 {played}/{view['action_counts']['protagonists']} 张；顺序 {order}"
        print(f"下一步：{ACTOR_NAMES[actor]}出牌（{progress}）；hand {actor} / play {actor} <牌> <目标>")
    elif phase == "reveal":
        counts = game.view()["action_counts"]
        total = counts["mastermind"] + counts["protagonists"]
        print(f"下一步：resolve，统一揭示 {total} 张牌。")
    elif phase == "final_guess":
        print(f"待猜角色：{', '.join(game.view()['guess_remaining'])}；guess {actor} <角色> <身份ID>")
    elif phase == "game_over":
        print("对局已结束，可查看 log、保存存档或 quit。")
    elif phase in ("refusal", "decision"):
        print("下一步：剧作家在私密窗口查看 options m，再 choose m <编号>。此处不能跳过。")
    elif phase in ("action_counters", "master_abilities", "goodwill", "day_end"):
        print(f"下一步：options {actor} 查看可选能力；choose {actor} <编号>，或 next {actor} 结束本阶段。")
    else:
        print(f"下一步：next {actor}，按流程继续。")


def show_rules(game):
    from .catalog import INCIDENT_NAMES, INCIDENT_RULES, PLOTS, PLOT_RULES, ROLE_NAMES, ROLE_RULES
    spec = MODULES[game.module]
    print(f"{game.module} 模组公开资料 / {spec.name}（列出全部可能项，不披露剧本选择）：")
    print(f"剧本结构：1 个规则 Y + {spec.subplot_count} 个规则 X；"
          f"可用角色 {len(spec.characters)} 名；可用事件 {len(spec.incidents)} 种。")
    print("每日：出牌 → 揭示及移动 → 其余行动结算 → 剧作家能力 → 领队友好能力 → 事件 → 换领队 → 日末。")
    print("能力通常每日一次，标注每轮一次的另有限制；友好不消耗，被拒绝也计次数。拒绝只针对能力来源，不针对目标。")
    print("禁止牌只限制同行动结算的牌，不限制能力或事件；两张以上禁止密谋全场失效。计数物先加后减，不低于零。")
    print("本轮顺利结束即可获胜。关键人物死亡/主人公死亡等会立即结束轮回，但仍须执行轮回结束的强制结算。")
    roles = {"ordinary"}
    for plot in spec.plots:
        name, group, required = PLOTS[plot]
        roles.update(required)
        print(f"  {group} {name} [{plot}]：" + ("、".join(f"{ROLE_NAMES[r]}×{n}" for r, n in required.items()) or "无固定身份"))
        print("    " + PLOT_RULES[plot])
    if "hideous" in spec.plots:
        roles.add("curmudgeon")
        print("最黑暗的剧本另可加入 0–2 名暴徒。")
    if spec.final_guess:
        timing = "；也可在轮回之间提前进入" if spec.early_final_guess else ""
        print(f"{game.module}：轮回耗尽进入最终猜测{timing}；猜对所有初始身份才获胜，错误一次即失败。")
    else:
        print(f"{game.module}：不使用最终猜测；轮回全部失败时剧作家获胜。")
    if spec.role_caps:
        print("身份人数上限：" + "、".join(f"{ROLE_NAMES[r]}×{n}" for r, n in spec.role_caps.items()) + "。")
    if spec.friend_gender_split:
        print("两名亲友同时登场时，必须一名男性、一名女性。")
    print("多个规则的身份槽位相加，再按身份上限截断；未分配身份的角色为平民。")
    for role in ROLE_NAMES:
        if role in roles:
            print(f"  {ROLE_NAMES[role]} [{role}]：{ROLE_RULES[role]}")
    print("事件通常要求当事人存活且不安达到临界；模组能力可能改变判定。发生/未发生均公开；发生但无有效目标也算发生。目标由规则指定的玩家选择。")
    for kind in spec.incidents:
        print(f"  {INCIDENT_NAMES[kind]} [{kind}]：{INCIDENT_RULES[kind]}")
    print("角色能力和被动特性请用 inspect <角色ID> 查看；护卫消耗一枚替代一次死亡，军人的保护持续整轮。")
    for actor, label in (("m", "剧作家"), ("a", "每位主人公")):
        print(label + "初始牌组（公开固定清单，不是当前私密手牌）：")
        print("  " + "；".join(f"{c.name}[{c.id}]" + ("（每轮一次）" if c.once_per_loop else "")
                                 for c in deck(actor, game.module).values()))


def match_demo(module, language="zh"):
    from .game import Game
    from .scenario import example_scenario
    game = Game(example_scenario(module))
    game.language = language
    print("完整对局演示：自动走完出牌、事件、轮回与最终胜负。固定演示行动，不是 AI 对手。")
    for _ in range(1000):
        if game.winner is not None:
            break
        start = len(game.state.events)
        phase, actor = game.state.phase, game.controller
        if phase == "mastermind":
            required = game.view()["action_counts"]["mastermind"]
            plays = (("p1a", "school"), ("p1b", "city"), ("h", "shrine"), ("v", "hospital"))[:required]
            if required == 3 and game.state.loop == 1:
                plays = (("p1a", "doctor"), ("p1b", "patient"),
                         ("d", "girl") if game.state.round == 1 else ("h", "shrine"))
            for card, target in plays:
                legal = game.legal_actions("m")
                command = next((item for item in legal
                                if item.get("card") == card and item.get("target") == target), None)
                if command is None:
                    command = next(item for item in legal if item.get("card") == card)
                game.dispatch(command.pop("actor"), command.pop("action"), **command)
        elif phase == "protagonists":
            count = sum(p.actor != "m" for p in game.state.pending)
            game.dispatch(actor, "play", card="g1", target=("school", "city", "shrine")[count])
        elif phase == "reveal":
            game.dispatch("m", "resolve")
        elif phase in ("decision", "refusal"):
            opts = game.options(actor)
            index = next((i for i, c in enumerate(opts, 1) if any(e.get("target") == "girl" for e in c["effects"])), 1)
            game.dispatch(actor, "choose", index=index)
        elif phase == "final_guess":
            remaining = game.view()["guess_remaining"]
            character = remaining[0]
            role = game.view("m")["secret"]["initial_roles"][character]
            game.dispatch(actor, "guess", character=character, role=role)
        else:
            game.dispatch(actor, "next")
        events(game, start)
    else:
        raise RuntimeError("完整演示未能在预期步骤内结束")
    match_board(game)
    print("演示完成：已从日初运行到正式胜负。")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--gui" in argv:
        argv.remove("--gui")
        return gui_main(argv)
    if "--practice" in argv:
        argv.remove("--practice")
        return practice_main(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    from .game import Game
    from .scenario import example_scenario, load_scenario
    parser = argparse.ArgumentParser(description="悲剧轮回完整本地热座对局")
    parser.add_argument("--module", choices=_supported_modules("cli_supported"), default="FS")
    parser.add_argument("--lang", choices=("zh", "en", "ja"), default="zh", help="术语与时间点语言")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--demo", action="store_true", help="演示事件、失败、重置和获胜的完整对局")
    source.add_argument("--script", help="加载 JSON 剧本；以文件的 module 为准")
    source.add_argument("--load", help="恢复完整对局存档")
    source.add_argument("--serve", action="store_true", help="启动版本化 JSON/HTTP 游戏服务")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP 服务监听地址（默认仅本机）")
    parser.add_argument("--port", type=int, default=8765, help="HTTP 服务端口")
    parser.add_argument("--allow-origin", action="append", default=[], help="允许的浏览器 Origin，可重复指定")
    parser.add_argument("--practice", action="store_true", help="仅练习出牌（独立模式）")
    parser.add_argument("--gui", action="store_true", help="打开本地热座桌面窗口")
    args = parser.parse_args(argv)
    if args.serve:
        if not 1 <= args.port <= 65535:
            parser.error("--port 必须在 1–65535 之间")
        from .server import serve
        serve(args.host, args.port, allowed_origins=args.allow_origin)
        return 0
    if args.demo:
        return match_demo(args.module, args.lang)
    try:
        game = Game.load(args.load) if args.load else Game(load_scenario(args.script) if args.script else example_scenario(args.module))
        game.language = args.lang
    except (ValueError, OSError, TypeError) as exc:
        print(f"无法开始对局：{exc}")
        return 1
    print(MATCH_HELP)
    match_board(game)
    while True:
        try:
            parts = [p.strip('"') for p in shlex.split(input(f"\n[{MATCH_PHASES[game.state.phase]}] > "), posix=False)]
        except (EOFError, KeyboardInterrupt):
            print("\n已退出；未保存的对局不会自动存档。")
            return 0
        except ValueError as exc:
            print(f"输入格式错误：{exc}")
            continue
        if not parts:
            continue
        cmd, *values = parts
        start = len(game.state.events)
        try:
            counts = {"board": (0,), "status": (0,), "help": (0,), "quit": (0,), "hand": (1,),
                      "play": (3,), "view": (1,), "resolve": (0,), "options": (1,), "choose": (2,),
                      "next": (0, 1), "log": (0,), "inspect": (1,), "rules": (0,), "save": (1,), "replay": (1,),
                      "guess": (3,), "final": (1,)}
            if cmd not in counts or len(values) not in counts[cmd]:
                raise RuleError("命令或参数数量错误，请输入 help")
            if cmd == "quit":
                return 0
            if cmd == "help":
                print(MATCH_HELP)
            elif cmd in ("board", "status"):
                match_board(game)
            elif cmd == "view":
                match_board(game, values[0])
            elif cmd == "hand":
                if values[0] == "m":
                    print("【剧作家私密手牌】")
                for cid in game.view(values[0])["hand"]:
                    card = deck(values[0], game.module)[cid]
                    print(f"  {cid:<4} {card.name}" + (" [每轮限一次]" if card.once_per_loop else ""))
            elif cmd == "play":
                game.dispatch(values[0], "play", card=values[1], target=values[2])
            elif cmd == "resolve":
                game.dispatch("m", "resolve")
            elif cmd == "next":
                game.dispatch(values[0] if values else game.controller, "next")
            elif cmd == "options":
                game.view(values[0])  # Validate the actor even when no options exist.
                if values[0] == "m":
                    print("【剧作家私密选择 · 请勿向主人公展示】")
                opts = game.options(values[0])
                for index, item in enumerate(opts, 1):
                    print(f"  {index}. {item['label']}")
                if not opts:
                    print("当前没有属于这个座位的能力/目标选择。")
            elif cmd == "choose":
                game.dispatch(values[0], "choose", index=int(values[1]))
            elif cmd == "guess":
                game.dispatch(values[0], "guess", character=values[1], role=values[2])
            elif cmd == "final":
                game.dispatch(values[0], "final")
            elif cmd == "log":
                events(game)
            elif cmd == "rules":
                show_rules(game)
            elif cmd == "inspect":
                char = game.view()["characters"].get(values[0])
                if not char:
                    raise RuleError("角色不在本剧本中")
                print(f"{char['name']} [{char['id']}]：{' / '.join(char['traits'])}；不安临界 {char['paranoia_limit']}")
                print(f"初始区域：{LOCATIONS[char['initial_location']]}；当前区域：{LOCATIONS[char['location']]}")
                print("禁行区域：" + ("、".join(LOCATIONS[loc] for loc in char["forbidden"]) or "无"))
                for a in char["abilities"]:
                    print(f"  {a['id']}：友好 ≥ {a['threshold']}，{a['text']}" + ("（每轮一次）" if a["once"] else "（每日一次）"))
                if char["passive"]:
                    print("  被动特性：" + char["passive"])
            elif cmd == "save":
                game.save(values[0])
                print("已保存完整对局。文件包含剧本和暗牌秘密，请勿在对局中分享。")
            elif cmd == "replay":
                game.save_replay(values[0])
                print("已导出纯文本回放。文件包含全部秘密，只应在对局结束后查看或分享。")
            if cmd in ("play", "resolve", "next", "choose", "guess", "final"):
                events(game, start)
                hint(game)
        except (ValueError, OSError, TypeError) as exc:
            print(f"无法执行：{exc}")
