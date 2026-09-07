"""Plain-text, deterministic full-match replays.

The format is deliberately line-oriented.  JSON payloads make it unambiguous to
load, while the trailing Chinese comments keep it useful in an ordinary editor.
Replay files contain every hidden decision and must only be shared after a match.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .engine import RuleError
from .flow import PHASE_LABELS
from .game import Game
from .transcript import describe_decision


MAGIC = "TRAGEDY_LOOPER_REPLAY"
VERSION = 1


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _payload(line: str, label: str) -> Any:
    parts = line.split("\t", 2)
    if len(parts) < 2 or parts[0] != label:
        raise RuleError(f"回放缺少 {label} 记录")
    try:
        return json.loads(parts[1])
    except json.JSONDecodeError as exc:
        raise RuleError(f"回放的 {label} 记录损坏") from exc


def dumps(game: Game) -> str:
    if game.winner is None or game.state.phase != "game_over":
        raise RuleError("只能导出已经正式结束的完整对局回放")
    if len(game.decisions) != len(game.history):
        raise RuleError("决策轨迹不完整，无法导出回放")
    winner_label = ("主人公" if game.winner == "protagonists" else "剧作家"
                    if game.winner == "mastermind" else "背叛者")
    lines = [
        f"{MAGIC}\t{VERSION}",
        "# 完整信息回放：包含所有暗牌、身份、事件当事人与玩家选择，只应在对局结束后查看。",
        f"# {game.scenario['title']} / {game.module} / 胜方：{winner_label}",
        f"SCENARIO\t{_json(game.scenario)}\t# 剧本与全部秘密",
    ]
    for record in game.decisions:
        command = _json(record.command)
        position = f"轮回 {record.before.loop} 第 {record.before.day} 天 · {PHASE_LABELS[record.before.phase.value]}"
        lines.append(f"ACTION\t{command}\t# {record.number:04d} | {position} | {record.description}")
        for step in record.steps:
            lines.append(f"#        => {step.message}")
    result = {"winner": game.winner, "commands": len(game.history)}
    lines.append(f"RESULT\t{_json(result)}\t# 回放终点")
    return "\n".join(lines) + "\n"


def dump(game: Game, path: str | Path) -> None:
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(dumps(game))


@dataclass(frozen=True)
class ReplayArchive:
    scenario: dict[str, Any]
    commands: tuple[dict[str, Any], ...]
    winner: str

    @classmethod
    def parse(cls, text: str) -> "ReplayArchive":
        lines = [line for line in text.splitlines() if line and not line.startswith("#")]
        if not lines or lines[0] != f"{MAGIC}\t{VERSION}":
            raise RuleError("无效或不支持的纯文本回放")
        if len(lines) < 3:
            raise RuleError("回放内容不完整")
        scenario = _payload(lines[1], "SCENARIO")
        result = _payload(lines[-1], "RESULT")
        command_lines = lines[2:-1]
        commands = tuple(_payload(line, "ACTION") for line in command_lines)
        if (not isinstance(result, dict) or set(result) != {"winner", "commands"}
                or (result["winner"] not in ("mastermind", "protagonists")
                    and result["winner"] not in {f"traitor:{seat}" for seat in ("a", "b", "c")})
                or type(result["commands"]) is not int or result["commands"] != len(commands)):
            raise RuleError("回放终点记录无效")
        archive = cls(scenario=scenario, commands=commands, winner=result["winner"])
        archive.verify()
        return archive

    @classmethod
    def load(cls, path: str | Path) -> "ReplayArchive":
        return cls.parse(Path(path).read_text(encoding="utf-8-sig"))

    def verify(self) -> Game:
        try:
            final = Game(self.scenario)
            for raw in self.commands:
                if not isinstance(raw, dict) or "actor" not in raw or "action" not in raw:
                    raise RuleError("回放包含非法命令")
                command = dict(raw)
                final.dispatch(command.pop("actor"), command.pop("action"), **command)
        except (KeyError, TypeError, ValueError) as exc:
            raise RuleError(f"无法重演回放：{exc}") from exc
        if final.state.phase != "game_over" or final.winner != self.winner:
            raise RuleError("回放命令未得到声明的正式胜负结果")
        return final


class ReplaySession:
    """Read-only timeline consumed by the GUI."""

    replay_mode = True
    seat = None
    expected_seat = None
    dirty = False

    def __init__(self, archive: ReplayArchive):
        self.archive = archive
        final = archive.verify()
        self.decisions = tuple(final.decisions)
        self._game = Game(archive.scenario)
        self.index = 0
        self.token = 0

    @property
    def game(self) -> Game:
        return self._game

    @property
    def length(self) -> int:
        return len(self.archive.commands)

    @property
    def current_decision(self):
        return None if self.index == 0 else self.decisions[self.index - 1]

    def public_view(self):
        return self.game.view("spectator")

    def private_view(self):
        return None

    def hide(self):
        return None

    def seek(self, index: int) -> None:
        if type(index) is not int or not 0 <= index <= self.length:
            raise RuleError("回放位置超出范围")
        if index < self.index:
            self._game = Game(self.archive.scenario)
            self.index = 0
        for raw in self.archive.commands[self.index:index]:
            command = dict(raw)
            self._game.dispatch(command.pop("actor"), command.pop("action"), **command)
            self.index += 1
        self.token += 1

    def step(self, amount: int) -> None:
        self.seek(max(0, min(self.length, self.index + amount)))
