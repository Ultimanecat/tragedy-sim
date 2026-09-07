"""Strict JSON scenarios: invalid/unsupported rules fail before the game starts."""

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

from .catalog import CHARACTERS, INCIDENT_NAMES, MODULES, PLOTS, ROLE_NAMES
from .engine import RuleError


HSA_GROUP_INCIDENTS = {"frenzied_night", "curse_awakening", "filth_overflow", "dead_apocalypse"}


def validate_scenario(data: dict) -> dict:
    required = {"id", "title", "module", "days", "loops", "main_plot", "subplots", "cast", "incidents"}
    if (not isinstance(data, dict)
            or set(data) - required - {"table_talk", "wm_replacement_plot", "hidden_cast",
                                       "ll_secret_order"}
            or required - set(data)):
        raise RuleError("剧本字段不完整或含不支持的字段；请参考 examples 中的 JSON")
    if any(not isinstance(data[k], str) or not data[k] for k in ("id", "title", "module", "main_plot")):
        raise RuleError("剧本名称、ID、模组、规则 Y 必须是非空字符串")
    module = data["module"]
    if module not in MODULES:
        raise RuleError("不支持的模组；当前支持 " + " / ".join(MODULES))
    spec = MODULES[module]
    if any(type(data[k]) is not int or not 1 <= data[k] <= 8 for k in ("days", "loops")):
        raise RuleError("天数、轮回数必须在 1–8 之间")
    if not isinstance(data["subplots"], list) or len(data["subplots"]) != spec.subplot_count:
        raise RuleError(f"{module} 需要{spec.subplot_count}个规则 X")
    plots = [data["main_plot"], *data["subplots"]]
    if any(not isinstance(p, str) or p not in spec.plots for p in plots):
        raise RuleError("剧本使用了不属于该模组的规则")
    if len(set(plots)) != len(plots) or PLOTS[plots[0]][1] != "Y" or any(PLOTS[p][1] != "X" for p in plots[1:]):
        raise RuleError("规则 X/Y 类型错误或重复")
    replacement = data.get("wm_replacement_plot")
    if "wm_mad_truth" in plots:
        if (not isinstance(replacement, str) or replacement == data["main_plot"]
                or replacement not in spec.plots or PLOTS[replacement][1] != "Y"):
            raise RuleError("疯狂的真相需要 wm_replacement_plot 指定另一条 WM 规则 Y")
    elif replacement is not None:
        raise RuleError("只有疯狂的真相可以设置 wm_replacement_plot")
    cast = data["cast"]
    if not isinstance(cast, dict) or not 3 <= len(cast) <= len(spec.characters):
        raise RuleError("剧本需要至少三名已支持角色")
    if any(c not in spec.characters or not isinstance(r, str) or r not in ROLE_NAMES
           for c, r in cast.items()):
        raise RuleError("剧本包含未知角色或无效身份")
    hidden_cast = data.get("hidden_cast")
    if module == "AHR":
        if hidden_cast is None:
            hidden_cast = dict(cast)
        ahr_roles = {"ordinary"}
        for plot in spec.plots:
            ahr_roles.update(PLOTS[plot][2])
        if (not isinstance(hidden_cast, dict) or set(hidden_cast) != set(cast)
                or any(not isinstance(role, str) or role not in ahr_roles
                       for role in hidden_cast.values())):
            raise RuleError("AHR 的 hidden_cast 必须为同一批角色指定合法的里世界身份")
    elif hidden_cast is not None:
        raise RuleError("只有 AHR 可以设置 hidden_cast")
    secret_order = data.get("ll_secret_order")
    if module == "LL":
        if secret_order is not None and (not isinstance(secret_order, list)
                                         or sorted(secret_order) != ["A", "B", "C"]):
            raise RuleError("LL 的 ll_secret_order 必须是 A/B/C 的一个排列")
    elif secret_order is not None:
        raise RuleError("只有 LL 可以设置 ll_secret_order")
    expected = Counter()
    for p in plots:
        expected.update(PLOTS[p][2])
    for role, cap in spec.role_caps.items():
        expected[role] = min(expected[role], cap)
    actual = Counter(cast.values())
    actual.pop("ordinary", None)
    if "hideous" in plots:
        if actual.get("curmudgeon", 0) > 2:
            raise RuleError("最黑暗的剧本允许 0–2 名暴徒")
        actual.pop("curmudgeon", None)
    valid_roles = [+expected]
    if "ll_fabricated_secret" in plots and expected["secret_key"] == 0:
        valid_roles = []
        for extra in ("killer", "brain", "fragment"):
            if expected[extra] == 0:
                candidate = +expected
                candidate[extra] += 1
                valid_roles.append(candidate)
    if +actual not in valid_roles:
        raise RuleError("角色身份数量与规则 X/Y 的身份槽位不符")
    if spec.friend_gender_split:
        genders = Counter()
        for cid, role in cast.items():
            if role != "friend":
                continue
            traits = CHARACTERS[cid].traits
            gender = "male" if "boy" in traits or "man" in traits else "female"
            genders[gender] += 1
        if genders["male"] > 1 or genders["female"] > 1:
            raise RuleError(f"{module} 的亲友最多男女各一名")
    if "sign" in plots and any("girl" not in CHARACTERS[c].traits for c, r in cast.items() if r == "key"):
        raise RuleError("和我签订契约吧！要求关键人物具有少女属性")
    if "hsa_girl_crisis" in plots and any(
            "girl" not in CHARACTERS[c].traits for c, r in cast.items() if r == "key"):
        raise RuleError("少女大危机要求关键人物具有少女属性")
    if data["main_plot"] == "hsa_noble":
        key = next(c for c, role in cast.items() if role == "key")
        vampire = next(c for c, role in cast.items() if role == "vampire")
        def gender(cid):
            traits = CHARACTERS[cid].traits
            return "male" if "boy" in traits or "man" in traits else "female"
        if gender(key) == gender(vampire):
            raise RuleError("高贵的血族要求关键人物与吸血鬼为异性")
    if not isinstance(data["incidents"], list):
        raise RuleError("incidents 必须是数组")
    days = set()
    culprit_kinds = {}
    for incident in data["incidents"]:
        if (not isinstance(incident, dict)
                or set(incident) - {"day", "kind", "culprit", "public_kind"}
                or {"day", "kind", "culprit"} - set(incident)):
            raise RuleError("事件需要 day / kind / culprit；伪造事件另需 public_kind")
        day, kind, culprit = incident["day"], incident["kind"], incident["culprit"]
        if type(day) is not int or not 1 <= day <= data["days"] or day in days:
            raise RuleError("事件日期非法或一天安排了多起事件")
        if not isinstance(kind, str) or kind not in spec.incidents:
            raise RuleError("该模组不支持此事件")
        group_incident = module == "HSA" and kind in HSA_GROUP_INCIDENTS
        if (not isinstance(culprit, str)
                or (culprit not in {"hospital", "shrine", "city", "school"}
                    if group_incident else culprit not in cast)):
            raise RuleError("群聚事件必须指定版图" if group_incident else "事件当事人不存在")
        public_kind = incident.get("public_kind")
        if kind == "fake_incident":
            if not isinstance(public_kind, str) or public_kind not in INCIDENT_NAMES:
                raise RuleError("伪造事件需要用 public_kind 指定一个公开事件名")
        elif public_kind is not None:
            raise RuleError("只有伪造事件可以设置 public_kind")
        days.add(day)
        if not group_incident:
            culprit_kinds.setdefault(culprit, []).append(kind)
    for culprit, kinds in culprit_kinds.items():
        if len(kinds) > 1 and any(kind != "serial_murder" for kind in kinds):
            raise RuleError("只有连续杀人允许同一角色重复担任事件当事人")
    if "mz_battle" == data["main_plot"]:
        ninjas = [cid for cid, role in cast.items() if role == "ninja"]
        if any("man" not in CHARACTERS[cid].traits for cid in ninjas):
            raise RuleError("男子汉的战争要求忍者具有男性属性，且不能是少年")
    if "mz_doom_song" in data["subplots"] and not any(
            incident["kind"] == "suicide" for incident in data["incidents"]):
        raise RuleError("灭亡颂歌要求剧本中至少有一起自杀")
    if any(role == "obsessive" for role in cast.values()) and not any(
            cast[culprit] == "obsessive" for culprit in culprit_kinds):
        raise RuleError("强迫症必须担任至少一起事件的当事人")
    if any(role == "detective" for role in cast.values()) and any(
            cast[culprit] == "detective" for culprit in culprit_kinds):
        raise RuleError("侦探不能担任事件的当事人")
    for role, name in (("fool", "愚者"), ("twin", "双胞胎")):
        if any(value == role for value in cast.values()) and not any(
                cast[culprit] == role for culprit in culprit_kinds):
            raise RuleError(f"{name}必须担任至少一起事件的当事人")
    sacrifices = [cid for cid, role in cast.items() if role == "sacrifice"]
    if sacrifices:
        first = min(data["incidents"], key=lambda item: item["day"], default=None)
        if first is None or first["culprit"] not in sacrifices:
            raise RuleError("祭品必须担任剧本中第一起事件的当事人")
    clowns = [cid for cid, role in cast.items() if role == "clown"]
    if clowns:
        first = min(data["incidents"], key=lambda item: item["day"], default=None)
        if first is None or first["culprit"] not in clowns:
            raise RuleError("小丑必须担任剧本中第一起事件的当事人")
    if data["main_plot"] == "ll_treacherous_world" and any(
            "girl" not in CHARACTERS[cid].traits
            for cid, role in cast.items() if role in ("key", "fragment")):
        raise RuleError("叛逆的世界要求关键人物与碎片都具有少女属性")
    if type(data.get("table_talk", False)) is not bool:
        raise RuleError("table_talk 必须是布尔值")
    if module == "LL" and data.get("table_talk", False):
        raise RuleError("Last Liar 在轮回过程中禁止主人公讨论")
    result = deepcopy(data)
    if module == "AHR":
        result["hidden_cast"] = deepcopy(hidden_cast)
    result["incidents"].sort(key=lambda i: i["day"])
    result.setdefault("table_talk", False)
    return result


def load_scenario(path: str | Path) -> dict:
    return validate_scenario(json.loads(Path(path).read_text(encoding="utf-8-sig")))


def example_scenario(module: str = "FS") -> dict:
    if module not in MODULES:
        raise RuleError("不支持的模组；当前支持 " + " / ".join(MODULES))
    if module == "MZ":
        main_plot = "mz_secret_record"
        subplots = ["mz_factor", "mz_doom_song"]
        cast = {"student": "ordinary", "girl": "key", "doctor": "brain",
                "worker": "conspiracy", "maiden": "factor", "patient": "prophet"}
    elif module == "MC":
        main_plot = "mc_event_web"
        subplots = ["mc_detective", "mc_absolute"]
        cast = {"student": "detective", "girl": "fool", "doctor": "conspiracy",
                "worker": "friend", "maiden": "obsessive", "patient": "ordinary"}
    elif module == "HSA":
        main_plot = "hsa_noble"
        subplots = ["love_hsa", "hsa_monster_plot"]
        cast = {"student": "ordinary", "girl": "key", "doctor": "vampire",
                "worker": "conspiracy", "maiden": "loved", "patient": "lover"}
    elif module == "WM":
        main_plot = "wm_gospel"
        subplots = ["wm_rumor", "wm_great_race"]
        cast = {"student": "serial", "girl": "key", "doctor": "deep_one",
                "worker": "conspiracy", "maiden": "cultist", "patient": "time_traveler"}
    elif module == "AHR":
        main_plot = "ahr_closed_future"
        subplots = ["ahr_puppet_lines", "ahr_beyond_worldline"]
        cast = {"student": "obsessive", "girl": "key", "doctor": "ahr_puppet",
                "worker": "fragment", "maiden": "piper", "patient": "alice",
                "nurse": "piper"}
    elif module == "LL":
        main_plot = "ll_final_plan"
        subplots = ["ll_beyond_worldline", "ll_x_citizen"]
        cast = {"student": "ordinary", "girl": "key", "doctor": "brain",
                "worker": "killer", "maiden": "factor", "patient": "ordinary"}
    else:
        main_plot = "murder_plan"
        subplots = ["rumor"] if module == "FS" else ["rumor", "threads"]
        cast = {"student": "ordinary", "girl": "key", "doctor": "brain", "worker": "killer",
                "maiden": "conspiracy", "patient": "ordinary"}
    return validate_scenario({
        "id": "silent-town-" + module.lower(), "title": "寂静小镇（原创教学剧本）", "module": module,
        "days": 3, "loops": 3, "main_plot": main_plot,
        "subplots": subplots, "cast": cast,
        "incidents": ([{"day": 2, "kind": "murder", "culprit": "doctor"},
                       {"day": 3, "kind": "cocoon", "culprit": "patient"}]
                      if module == "LL" else
                      [{"day": 1, "kind": "dimension_swap", "culprit": "student"},
                       {"day": 3, "kind": "hope_light", "culprit": "patient"}]
                      if module == "AHR" else
                      [{"day": 2, "kind": "discovery", "culprit": "doctor"},
                       {"day": 3, "kind": "mass_suicide", "culprit": "patient"}]
                      if module == "WM" else
                      [{"day": 2, "kind": "frenzied_murder", "culprit": "doctor"},
                       {"day": 3, "kind": "curse_declaration", "culprit": "patient"}]
                      if module == "HSA" else
                      [{"day": 2, "kind": "omen", "culprit": "girl"},
                       {"day": 3, "kind": "suicide", "culprit": "maiden"}]
                      if module == "MC" else
                      [{"day": 2, "kind": "serial_murder", "culprit": "doctor"},
                       {"day": 3, "kind": "suicide", "culprit": "patient"}]
                      if module == "MZ" else
                      [{"day": 2, "kind": "murder", "culprit": "doctor"},
                       {"day": 3, "kind": "suicide", "culprit": "patient"}]),
        "table_talk": module != "LL",
    })
