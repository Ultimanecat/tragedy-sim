"""Basic Tragedy X script validation."""

from ...engine import RuleError
from ..common.scenario import validate_scenario as _validate_basic


def validate_scenario(data):
    if not isinstance(data, dict) or data.get("module") != "BTX":
        raise RuleError("Basic Tragedy X 剧本的 module 必须为 BTX")
    return _validate_basic(data)
