"""Shared character-specific script-role validation."""

from collections import Counter

from ..catalog import PLOTS
from ..engine import RuleError


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
