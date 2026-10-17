"""Optional exact transition/observation edges, with complete private inputs.

Unlike rule-value transpositions, edges retain raw resource order, the full
event/command/checkpoint history and mutable-object aliasing. These private
keys and snapshots must never enter a room projection or SSE message.
"""

from collections import OrderedDict
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from types import MappingProxyType

from ..domain import ComponentStore, InformationState
from .keys import DIAGNOSTICS, UnsupportedKey, audited_fs, freeze, information_key


def execution_graph(world):
    """Ordered graph encoding: no State normalization; repeated refs survive."""
    if not audited_fs(world):
        raise UnsupportedKey("transition edges require the audited FS Game")
    seen = {}

    def visit(value):
        if value is world.ruleset:
            return ("ruleset", id(value))
        if value is None or isinstance(value, Enum) or type(value) in {bool, int, str, bytes, float}:
            return freeze(value)
        identity = id(value)
        if identity in seen:
            return ("ref", seen[identity])
        index = len(seen)
        seen[identity] = index
        if type(value) in {dict, MappingProxyType}:
            items = value.items()
            if value is world.__dict__:
                items = ((k, v) for k, v in items if k not in DIAGNOSTICS)
            children = tuple((visit(k), visit(v)) for k, v in items)
        elif type(value) in {tuple, list}:
            children = tuple(visit(v) for v in value)
        elif type(value) in {set, frozenset}:
            children = tuple(visit(v) for v in sorted(value, key=lambda v: repr(freeze(v))))
        elif type(value) is ComponentStore and not value.to_dict():
            children = ()
        elif is_dataclass(value) and not isinstance(value, type) and type(value).__module__.startswith("tragedy_sim."):
            names = [f.name for f in fields(value)]
            names += [n for n in vars(value) if n not in names] if hasattr(value, "__dict__") else []
            children = tuple((n, visit(getattr(value, n))) for n in names)
        else:
            raise UnsupportedKey(f"unsupported execution graph value: {type(value).__name__}")
        return ("node", index, type(value), children)

    return ("fs-execution-graph-v1", visit(world.__dict__))


@dataclass(frozen=True)
class ObservationBranch:
    viewer: str
    before: object
    after: object
    events: tuple
    replaces_event_history: bool
    before_observation: InformationState
    after_observation: InformationState


@dataclass
class EdgeStats:
    hits: int = 0
    misses: int = 0
    stores: int = 0
    evictions: int = 0
    fallbacks: int = 0


@dataclass(frozen=True)
class _Entry:
    successor: object
    branches: tuple[ObservationBranch, ...]


class TransitionEdgeCache:
    version = "fs-transition-observation-edge-v1"

    def __init__(self, capacity, *, viewers=("team", "m")):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("edge cache capacity must be a positive integer")
        allowed = {"team", "m", "a", "b", "c", "spectator"}
        if (not isinstance(viewers, tuple) or not viewers or any(type(v) is not str or v not in allowed for v in viewers)
                or len(set(viewers)) != len(viewers)):
            raise ValueError("edge cache viewers must be distinct valid viewers")
        self.capacity, self.viewers = capacity, viewers
        self._entries = OrderedDict()
        self.stats = EdgeStats()

    def __len__(self):
        return len(self._entries)

    def key(self, world, command):
        try:
            return execution_graph(world), freeze(command)
        except (UnsupportedKey, RecursionError):
            self.stats.fallbacks += 1
            return None

    def get(self, key):
        if key is None:
            return None
        entry = self._entries.get(key)
        if entry is None:
            self.stats.misses += 1
            return None
        self.stats.hits += 1
        self._entries.move_to_end(key)
        return entry.successor.clone()

    def store(self, key, before, successor):
        if key is None:
            return
        try:
            execution_graph(successor)  # Refuse unreviewed fields created by an effect.
            prefix = before.state.events
            replaced = successor.state.events[:len(prefix)] != prefix
            delta = successor.state.events if replaced else successor.state.events[len(prefix):]
            def observe(game, viewer):
                view = game.protagonist_team_view() if viewer == "team" else game.view(viewer)
                return InformationState.create(viewer, view)

            branches = tuple(ObservationBranch(viewer, information_key(before, viewer),
                                               information_key(successor, viewer), freeze(tuple(delta)), replaced,
                                               observe(before, viewer), observe(successor, viewer)) for viewer in self.viewers)
            entry = _Entry(successor.clone(), branches)
        except (UnsupportedKey, RecursionError, TypeError):
            self.stats.fallbacks += 1
            return
        self._entries[key] = entry
        self._entries.move_to_end(key)
        self.stats.stores += 1
        if len(self._entries) > self.capacity:
            self._entries.popitem(last=False)
            self.stats.evictions += 1

    def observation(self, world, command, viewer):
        """Read one immutable authorized branch, never a private Game snapshot."""
        if viewer not in self.viewers:
            raise ValueError("viewer was not configured for this observation cache")
        key = self.key(world, command)
        entry = self._entries.get(key) if key is not None else None
        if entry is None:
            return None
        return next(branch for branch in entry.branches if branch.viewer == viewer)
