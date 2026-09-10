"""Immutable boundaries between script, world state, and player knowledge."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from types import MappingProxyType
from typing import Any, Mapping


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return deepcopy(value)


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return _freeze(value)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, frozenset)):
        return [_thaw(item) for item in value]
    return deepcopy(value)


@dataclass(frozen=True)
class ScriptDefinition:
    """Validated secret setup shared by all successors of a search node."""

    id: str
    title: str
    ruleset_id: str
    days: int
    loops: int
    main_plot: str
    subplots: tuple[str, ...]
    cast: Mapping[str, str]
    incidents: tuple[Mapping[str, Any], ...]
    table_talk: bool = False
    extensions: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ScriptDefinition":
        known = {"id", "title", "module", "days", "loops", "main_plot", "subplots",
                 "cast", "incidents", "table_talk"}
        return cls(data["id"], data["title"], data["module"], data["days"], data["loops"],
                   data["main_plot"], tuple(data["subplots"]), _freeze_mapping(data["cast"]),
                   tuple(_freeze_mapping(item) for item in data["incidents"]),
                   bool(data.get("table_talk", False)),
                   _freeze_mapping({key: value for key, value in data.items() if key not in known}))

    def __deepcopy__(self, memo):
        return self

    def to_dict(self) -> dict[str, Any]:
        result = {
            "id": self.id, "title": self.title, "module": self.ruleset_id,
            "days": self.days, "loops": self.loops, "main_plot": self.main_plot,
            "subplots": list(self.subplots), "cast": _thaw(self.cast),
            "incidents": _thaw(self.incidents), "table_talk": self.table_talk,
        }
        result.update(_thaw(self.extensions))
        return result


@dataclass(frozen=True)
class InformationState:
    """One viewer's complete observable state, detached from private engine data."""

    viewer: str
    projection: Mapping[str, Any]
    key: str

    @classmethod
    def create(cls, viewer: str, projection: Mapping[str, Any]) -> "InformationState":
        detached = deepcopy(dict(projection))
        key_data = deepcopy(detached)
        key_data.pop("events", None)
        key = json.dumps(key_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return cls(viewer, _freeze_mapping(detached), key)

    def to_dict(self) -> dict[str, Any]:
        return _thaw(self.projection)
