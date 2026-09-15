"""Shared character-specific script-role validation."""

from collections import Counter

from ..catalog import PLOTS, REFUSAL, ROLE_NAMES
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
    # Copycat duplicates another card's role without consuming a role slot.
    if "copycat" in cast:
        actual[cast["copycat"]] -= 1
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
    expected = {cid for cid in ("godly", "boss", "transfer_student") if cid in cast}
    optional = {cid for cid in ("copycat", "servant", "henchman") if cid in cast}
    if not expected.issubset(options) or not set(options).issubset(expected | optional):
        missing = "、".join(sorted(expected - set(options)))
        extra = "、".join(sorted(set(options) - expected - optional))
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
    if "copycat" in cast:
        value = options.get("copycat")
        same_role = [cid for cid, role in cast.items()
                     if cid != "copycat" and role == cast["copycat"]]
        if not same_role:
            raise RuleError("模仿者需要用 role_source 指定另一名身份相同的角色")
        if value is not None and (
                not isinstance(value, dict) or set(value) != {"role_source"}
                or value["role_source"] not in same_role):
            raise RuleError("模仿者需要用 role_source 指定另一名身份相同的角色")
    if "servant" in options:
        value = options["servant"]
        if (not isinstance(value, dict) or set(value) != {"initial_location"}
                or value["initial_location"] not in {"school", "city"}):
            raise RuleError("侍从需要用 initial_location 指定学校或都市")
    if "henchman" in options:
        value = options["henchman"]
        if (not isinstance(value, dict) or set(value) != {"initial_location"}
                or value["initial_location"] not in LOCATIONS):
            raise RuleError("手下需要用 initial_location 指定合法版图")
    if "part_timer_question" in cast:
        raise RuleError("“临时工？”不能单独写入 cast；临时工死亡后会自动替换")
    if cast.get("little_sister") in REFUSAL:
        raise RuleError("妹妹不能被分配拒绝友好的身份")
    if cast.get("ai") == "ordinary":
        raise RuleError("A.I. 的身份不能是平民")
    return options


def validate_scenario_metadata(data: dict) -> None:
    """Validate optional official-script metadata and narrowly scoped variants."""
    loop_options = data.get("loop_options")
    if loop_options is not None and (
            not isinstance(loop_options, list) or not loop_options
            or any(type(value) is not int or not 1 <= value <= 8 for value in loop_options)
            or loop_options != sorted(set(loop_options))
            or data["loops"] not in loop_options):
        raise RuleError("loop_options 必须是不重复的升序轮回数，且包含默认 loops")
    special = data.get("special_rules", {})
    if not isinstance(special, dict) or set(special) - {
            "disabled_mastermind_cards", "all_locations_count_as"}:
        raise RuleError("special_rules 包含不支持的特殊规则")
    disabled = special.get("disabled_mastermind_cards", [])
    if (not isinstance(disabled, list) or len(disabled) != len(set(disabled))
            or any(card not in {"fg"} for card in disabled)):
        raise RuleError("disabled_mastermind_cards 包含不支持的行动牌")
    counted_as = special.get("all_locations_count_as")
    if counted_as is not None and counted_as not in LOCATIONS:
        raise RuleError("all_locations_count_as 必须指定合法版图")
    role_slots = data.get("role_slots")
    if role_slots is not None and (
            not isinstance(role_slots, dict) or not role_slots
            or any(role == "ordinary" or role not in ROLE_NAMES
                   or type(count) is not int or count < 1
                   for role, count in role_slots.items())):
        raise RuleError("role_slots 必须明确列出合法的非平民身份数量")
