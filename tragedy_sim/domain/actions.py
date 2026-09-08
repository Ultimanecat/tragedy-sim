"""Structured player actions, independent from presentation text."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping

from ..model import TimingId
from .keys import RuleSource


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ActionOffer:
    """One legal decision exposed to a player or a search algorithm.

    ``label`` is deliberately excluded from identity. Translated display text can
    therefore change without invalidating a network action or an AI tree edge.
    """

    id: str
    actor: str
    kind: str
    timing: TimingId
    source: RuleSource
    parameters: Mapping[str, Any] = field(default_factory=dict)
    label: str = ""

    @classmethod
    def create(
        cls, *, actor: str, kind: str, timing: TimingId, source: RuleSource,
        parameters: Mapping[str, Any] | None = None, label: str = "",
    ) -> "ActionOffer":
        RuleSource(kind)  # action kinds follow the same namespaced identifier grammar
        parameters = deepcopy(dict(parameters or {}))
        identity = {
            "actor": actor, "kind": kind, "timing": TimingId(timing).value,
            "source": source.value, "parameters": parameters,
        }
        digest = hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()[:24]
        return cls(digest, actor, kind, TimingId(timing), source, parameters, label)

    @classmethod
    def from_command(
        cls, command: Mapping[str, Any], *, timing: TimingId,
        source: RuleSource = RuleSource("core.command"), label: str = "",
    ) -> "ActionOffer":
        command = dict(command)
        try:
            actor = command.pop("actor")
            kind = command.pop("action")
        except KeyError as exc:
            raise ValueError("命令必须包含 actor 和 action") from exc
        return cls.create(actor=actor, kind=f"core.{kind}", timing=timing,
                          source=source, parameters=command, label=label)

    @property
    def command(self) -> dict[str, Any]:
        kind = self.kind.removeprefix("core.")
        return {"actor": self.actor, "action": kind, **deepcopy(dict(self.parameters))}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "actor": self.actor, "kind": self.kind,
            "timing": self.timing.value, "source": self.source.value,
            "parameters": deepcopy(dict(self.parameters)), "label": self.label,
        }
