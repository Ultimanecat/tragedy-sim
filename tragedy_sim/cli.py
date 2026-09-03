"""Small local hotseat / debugging interface for the action-card milestone."""

import argparse
import sys

from .cards import ACTOR_NAMES, LOCATIONS, deck
from .engine import ActionGame, RuleError

PHASES = {"mastermind": "剧作家出牌", "protagonists": "主人公出牌",
          "reveal": "等待揭示", "resolved": "行动结算完成"}
HELP = """
board                         公开棋盘、暗牌目标、限次牌留置区
hand <玩家>                   该玩家手牌（m 剧作家，a/b/c 主人公）
play <玩家> <牌> <目标>        例如 play m i2 doctor
view <玩家|spectator>         查看该玩家自己的暗牌；不显示他人的暗牌
resolve                       六张牌齐全后统一揭示并结算
log                           查看本次练习的公开日志
next                          练习控制：保留棋盘，轮换领队，开始下一次出牌
reset                         练习控制：恢复初始棋盘和所有牌，开始新轮回
help                          显示命令
quit                          退出

地图：hospital 医院 | shrine 神社
      city     都市 | school 学校
角色：student 男学生、doctor 医生、maiden 巫女、worker 职员、patient 住院患者

仅实现基础行动牌。没有能力、身份、事件、胜负或机器人。
本地热座/调试模式：允许操作者查看各方手牌，终端历史不提供安全隔离。
"""


def board(game: ActionGame, viewer: str = "spectator") -> None:
    view = game.view(viewer)
    print(f"\n{view['module']} 出牌练习 | 轮回 {view['loop']} | 第 {view['round']} 次出牌 | "
          f"{PHASES[view['phase']]} | 领队 {view['leader']}")
    for loc, name in LOCATIONS.items():
        print(f"  {loc} {name}（密谋 {view['locations'][loc]}）")
        for char in view["characters"].values():
            if char["location"] == loc:
                print(f"    {char['id']:<9} {char['name']}：友好 {char['goodwill']} / "
                      f"不安 {char['paranoia']} / 密谋 {char['intrigue']}"
                      + (" [死亡]" if not char["alive"] else ""))
    for p in view["pending"]:
        label = deck(p["actor"])[p["card"]].name if p["card"] else "暗牌"
        print(f"  {ACTOR_NAMES[p['actor']]} → {p['target']}：{label}")
    for actor, discarded in view["discarded"].items():
        if discarded:
            print(f"  {actor} 公开留置：" + ", ".join(discarded))
    if game.next_actor:
        print(f"  下一位：{ACTOR_NAMES[game.next_actor]} ({game.next_actor})")


def events(game: ActionGame, start: int = 0) -> None:
    for event in game.view()["events"][start:]:
        print(f"  [轮回{event['loop']}/出牌{event['round']}] {event['message']}")
        if event["kind"] == "cards_revealed":
            for p in event["cards"]:
                print(f"    {p['actor']} {deck(p['actor'])[p['card']].name} → {p['target']}")


def demo(module: str) -> int:
    game = ActionGame(module=module)
    print("演示：相同方向只移动一次；一张禁止密谋有效；友好直接增加。")
    for actor, card, target in [("m", "h", "student"), ("m", "i2", "hospital"),
                                ("m", "p1a", "doctor"), ("a", "h", "student"),
                                ("b", "fi", "hospital"), ("c", "g2", "doctor")]:
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


def main(argv: list[str] | None = None) -> int:
    # Windows redirected stdout otherwise uses the legacy code page and garbles Chinese.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="FS / BTX 基础出牌模拟器（第一阶段）")
    parser.add_argument("--module", choices=("FS", "BTX"), default="FS", help="选择资源依据；当前基础牌相同")
    parser.add_argument("--demo", action="store_true", help="自动演示一次双方出牌及结算")
    args = parser.parse_args(argv)
    if args.demo:
        return demo(args.module)
    game = ActionGame(module=args.module)
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
