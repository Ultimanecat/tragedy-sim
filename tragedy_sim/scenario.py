"""Strict JSON scenarios: invalid/unsupported rules fail before the game starts."""

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

from .catalog import CHARACTERS, INCIDENT_NAMES, MODULE_PLOTS, PLOTS
from .engine import RuleError


def validate_scenario(data: dict) -> dict:
    required = {"id", "title", "module", "days", "loops", "main_plot", "subplots", "cast", "incidents"}
    if not isinstance(data, dict) or set(data) - required - {"table_talk"} or required - set(data):
        raise RuleError("剧本字段不完整或含不支持的字段；请参考 examples 中的 JSON")
    if any(not isinstance(data[k], str) or not data[k] for k in ("id", "title", "module", "main_plot")):
        raise RuleError("剧本名称、ID、模组、规则 Y 必须是非空字符串")
    module = data["module"]
    if module not in MODULE_PLOTS:
        raise RuleError("仅支持 FS / BTX")
    if any(type(data[k]) is not int or not 1 <= data[k] <= 8 for k in ("days", "loops")):
        raise RuleError("天数、轮回数必须在 1–8 之间")
    if not isinstance(data["subplots"], list) or len(data["subplots"]) != (1 if module == "FS" else 2):
        raise RuleError("FS 需要一个规则 X；BTX 需要两个规则 X")
    plots = [data["main_plot"], *data["subplots"]]
    if any(not isinstance(p, str) or p not in MODULE_PLOTS[module] for p in plots):
        raise RuleError("剧本使用了不属于该模组的规则")
    if len(set(plots)) != len(plots) or PLOTS[plots[0]][1] != "Y" or any(PLOTS[p][1] != "X" for p in plots[1:]):
        raise RuleError("规则 X/Y 类型错误或重复")
    cast = data["cast"]
    if not isinstance(cast, dict) or not 3 <= len(cast) <= len(CHARACTERS):
        raise RuleError("剧本需要至少三名已支持角色")
    if any(c not in CHARACTERS or not isinstance(r, str) for c, r in cast.items()):
        raise RuleError("剧本包含未知角色或无效身份")
    expected = Counter()
    for p in plots:
        expected.update(PLOTS[p][2])
    for role, cap in (("conspiracy", 1), ("friend", 2)):
        expected[role] = min(expected[role], cap)
    actual = Counter(cast.values())
    actual.pop("ordinary", None)
    if "hideous" in plots:
        if actual.get("curmudgeon", 0) > 2:
            raise RuleError("最黑暗的剧本允许 0–2 名暴徒")
        actual.pop("curmudgeon", None)
    if +actual != +expected:
        raise RuleError("角色身份数量与规则 X/Y 的身份槽位不符")
    if "sign" in plots and any("girl" not in CHARACTERS[c].traits for c, r in cast.items() if r == "key"):
        raise RuleError("和我签订契约吧！要求关键人物具有少女属性")
    if not isinstance(data["incidents"], list):
        raise RuleError("incidents 必须是数组")
    days, culprits = set(), set()
    for incident in data["incidents"]:
        if not isinstance(incident, dict) or set(incident) != {"day", "kind", "culprit"}:
            raise RuleError("事件需要 day / kind / culprit 三个字段")
        day, kind, culprit = incident["day"], incident["kind"], incident["culprit"]
        if type(day) is not int or not 1 <= day <= data["days"] or day in days:
            raise RuleError("事件日期非法或一天安排了多起事件")
        if not isinstance(kind, str) or kind not in INCIDENT_NAMES or (module == "FS" and kind in ("foul_play", "butterfly")):
            raise RuleError("该模组不支持此事件")
        if not isinstance(culprit, str) or culprit not in cast or culprit in culprits:
            raise RuleError("事件当事人不存在或重复承担事件")
        days.add(day)
        culprits.add(culprit)
    if type(data.get("table_talk", False)) is not bool:
        raise RuleError("table_talk 必须是布尔值")
    result = deepcopy(data)
    result["incidents"].sort(key=lambda i: i["day"])
    result.setdefault("table_talk", False)
    return result


def load_scenario(path: str | Path) -> dict:
    return validate_scenario(json.loads(Path(path).read_text(encoding="utf-8-sig")))


def example_scenario(module: str = "FS") -> dict:
    return validate_scenario({
        "id": "silent-town-" + module.lower(), "title": "寂静小镇（原创教学剧本）", "module": module,
        "days": 3, "loops": 3, "main_plot": "murder_plan",
        "subplots": ["rumor"] if module == "FS" else ["rumor", "threads"],
        "cast": {"student": "ordinary", "girl": "key", "doctor": "brain", "worker": "killer",
                 "maiden": "conspiracy", "patient": "ordinary"},
        "incidents": [{"day": 2, "kind": "murder", "culprit": "doctor"},
                      {"day": 3, "kind": "suicide", "culprit": "patient"}], "table_talk": True,
    })
