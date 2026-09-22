"""Server-owned scenario catalog with public metadata and strict loading.

Tutorial scenarios remain available even when the repository has no external
scenario data.  Additional scripts are discovered from ``scenarios/*.json``;
their secret contents never cross the catalog API boundary.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from .catalog import MODULES
from .engine import RuleError
from .scenario import example_scenario, validate_scenario


DEFAULT_SCENARIO_ROOT = Path(__file__).resolve().parent.parent / "scenarios"


def _loop_variants(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn a card's loop-count choices into distinct catalog entries.

    More loops are an easier setting for the protagonists.  Keeping each
    setting behind a stable scenario ID prevents rooms, replays and benchmark
    reports from silently mixing different difficulties.
    """
    options = scenario.get("loop_options", [scenario["loops"]])
    if len(options) == 1:
        concrete = deepcopy(scenario)
        concrete["loop_options"] = [concrete["loops"]]
        return [concrete]

    variants: list[dict[str, Any]] = []
    suffixes = ("", "-easy", "-very-easy")
    labels = ("", " (Easy)", " (Very Easy)")
    for index, loops in enumerate(options):
        concrete = deepcopy(scenario)
        concrete["id"] += suffixes[index]
        concrete["title"] += labels[index]
        concrete["loops"] = loops
        concrete["loop_options"] = [loops]
        variants.append(concrete)
    return variants


class ScenarioLibrary:
    """Discover validated scripts and resolve stable IDs to private data."""

    def __init__(self, root: str | Path | None = None):
        self.root = DEFAULT_SCENARIO_ROOT if root is None else Path(root)

    def _entries(self) -> dict[str, tuple[dict[str, Any], str]]:
        entries = {
            scenario["id"]: (scenario, "tutorial")
            for scenario in (example_scenario(module) for module in MODULES)
        }
        if not self.root.exists():
            return entries
        if not self.root.is_dir():
            raise RuleError(f"剧本目录不是文件夹：{self.root}")
        for path in sorted(self.root.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8-sig"))
                scenario = validate_scenario(raw)
            except (OSError, json.JSONDecodeError, RuleError) as exc:
                raise RuleError(f"剧本文件 {path.name} 无效：{exc}") from exc
            for concrete in _loop_variants(scenario):
                scenario_id = concrete["id"]
                if scenario_id in entries:
                    raise RuleError(f"剧本 ID 重复：{scenario_id}（{path.name}）")
                entries[scenario_id] = (concrete, "library")
        return entries

    def list(self, module: str | None = None) -> list[dict[str, Any]]:
        if module is not None and module not in MODULES:
            raise RuleError("不支持的模组；当前支持 " + " / ".join(MODULES))
        order = {name: index for index, name in enumerate(MODULES)}
        summaries = [{
            "id": scenario["id"],
            "title": scenario["title"],
            "module": scenario["module"],
            "days": scenario["days"],
            "loops": scenario["loops"],
            "loop_options": scenario.get("loop_options", [scenario["loops"]]),
            "source": source,
        } for scenario, source in self._entries().values()
            if module is None or scenario["module"] == module]
        return sorted(summaries, key=lambda item: (order[item["module"]], item["source"] != "tutorial",
                                                    item["title"], item["id"]))

    def get(self, scenario_id: str) -> dict[str, Any]:
        if not isinstance(scenario_id, str) or not scenario_id:
            raise RuleError("scenario_id 必须是非空字符串")
        entry = self._entries().get(scenario_id)
        if entry is None:
            raise RuleError("剧本不存在")
        return deepcopy(entry[0])
