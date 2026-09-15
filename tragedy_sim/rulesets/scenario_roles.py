"""Shared character-specific script-role validation."""

from collections import Counter

from ..catalog import PLOTS
from ..cards import LOCATIONS
from ..engine import RuleError


def character_genders(traits):
    result = set()
    if "boy" in traits or "man" in traits:
        result.add("male")
    if "girl" in traits or "woman" in traits:
        result.add("female")
    return result


def selected_role_counts(cast: dict[str, str], plots: list[str], module_plots: tuple[str, ...]) -> Counter:
    """Return roles supplied by plot slots, excluding a legal Irregular role."""
    actual = Counter(cast.values())
    actual.pop("ordinary", None)
    if "irregular" not in cast:
        return actual

    role = cast["irregular"]
    selected_roles = {name for plot in plots for name in PLOTS[plot][2]}
    module_roles = {name for plot in module_plots for name in PLOTS[plot][2]}
    if role == "ordinary" or role in selected_roles or role not in module_roles:
        raise RuleError("局外人的身份必须存在于当前模组，且未被所选规则 X/Y 使用")
    actual[role] -= 1
    return +actual


def validate_character_options(data: dict, cast: dict[str, str]) -> dict:
    """Validate script-time choices printed on special character cards."""
    options = data.get("character_options", {})
    if not isinstance(options, dict) or any(cid not in cast for cid in options):
        raise RuleError("character_options 只能配置本剧本登场的角色")
    expected = {
        cid for cid in ("godly", "boss", "transfer_student") if cid in cast
    }
    if set(options) != expected:
        missing = "、".join(sorted(expected - set(options)))
        extra = "、".join(sorted(set(options) - expected))
        detail = f"缺少：{missing}" if missing else f"不支持：{extra}"
        raise RuleError(f"特殊角色的剧本配置不完整（{detail}）")
    for cid, expected_key, upper in (
            ("godly", "entry_loop", data["loops"]),
            ("transfer_student", "entry_day", data["days"])):
        if cid not in cast:
            continue
        value = options[cid]
        if (not isinstance(value, dict) or set(value) != {expected_key}
                or type(value[expected_key]) is not int
                or not 1 <= value[expected_key] <= upper):
            raise RuleError(f"{cid} 需要有效的 {expected_key}")
    if "boss" in cast:
        value = options["boss"]
        if (not isinstance(value, dict) or set(value) != {"territory"}
                or value["territory"] not in LOCATIONS):
            raise RuleError("大人物需要用 territory 指定合法版图")
    if cast.get("ai") == "ordinary":
        raise RuleError("A.I. 的身份不能是平民")
    return options
