"""First Steps script validation."""

from ...engine import RuleError
from ..common.scenario import validate_scenario as _validate_basic


def validate_scenario(data):
    if not isinstance(data, dict) or data.get("module") != "FS":
        raise RuleError("First Steps 剧本的 module 必须为 FS")
    return _validate_basic(data)
