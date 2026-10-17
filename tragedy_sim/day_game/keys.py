"""Conservative FS rule keys and separate complete observation-history keys.

Keys are private verification inputs, never player projections. Dictionary
order is retained: numeric engine choices may depend on insertion order.
Unknown objects fail closed, rather than receiving a repr/id-based state key.
"""

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from math import isfinite
from types import MappingProxyType

from ..domain import ComponentStore
from ..engine import State
from ..game import Game
from ..rulesets.registry import get_ruleset


class UnsupportedKey(TypeError):
    pass


# These append-only outputs are not read by the FS transition rules. Public
# events, visible commands and observation checkpoints remain in InformationKey.
DIAGNOSTICS = frozenset({"decisions", "_resolution_traces", "_activation_history"})
NON_RULE_HISTORY = DIAGNOSTICS | {"history", "_observation_checkpoints"}


def freeze(value):
    """Hashable, type-sensitive encoding, including dynamically added fields."""
    if value is None:
        return ("none",)
    if isinstance(value, Enum):
        return (type(value), freeze(value.value))
    if type(value) in {bool, int, str, bytes}:
        return (type(value), value)
    if type(value) is float and isfinite(value):
        return (float, value)
    if type(value) in {dict, MappingProxyType}:
        return (type(value), tuple((freeze(k), freeze(v)) for k, v in value.items()))
    if isinstance(value, Mapping):
        raise UnsupportedKey("custom mapping behavior has not been audited")
    if type(value) in {tuple, list}:
        return (type(value), tuple(freeze(v) for v in value))
    if type(value) in {set, frozenset}:
        return (type(value), frozenset(freeze(v) for v in value))
    if type(value) is ComponentStore:
        if value.to_dict():
            raise UnsupportedKey("nonempty components have not been audited for exact FS caching")
        return (ComponentStore,)
    if is_dataclass(value) and not isinstance(value, type):
        # All current rule dataclasses belong to the engine/domain. Reject
        # arbitrary user dataclasses that may hide behavior outside fields.
        if not type(value).__module__.startswith("tragedy_sim."):
            raise UnsupportedKey("unrecognized dataclass")
        names = [f.name for f in fields(value)]
        names += [name for name in vars(value) if name not in names] if hasattr(value, "__dict__") else []
        result = []
        for name in names:
            if type(value) is State and name == "events":
                continue
            item = getattr(value, name)
            if (type(value) is State and name == "hands" and type(item) is dict
                    and all(type(actor) is str and type(cards) is list
                            and all(type(card) is str for card in cards) for actor, cards in item.items())):
                # FS card access is by ID/membership; views enumerate in deck
                # order. Keep seat owners and multiplicities. Discards MUST
                # retain order: recovery abilities address numbered options.
                encoded = ("physical-hand-multisets-v1",
                           tuple((actor, tuple(sorted(cards))) for actor, cards in item.items()))
            else:
                encoded = freeze(item)
            result.append((name, encoded))
        return (type(value), tuple(result))
    raise UnsupportedKey(f"unsupported key value: {type(value).__name__}")


def audited_fs(world):
    return type(world) is Game and world.module == "FS" and world.ruleset is get_ruleset("FS")


@dataclass(frozen=True)
class RuleStateKey:
    version: str
    ruleset_identity: int
    fields: tuple


@dataclass(frozen=True)
class InformationKey:
    """Authorized present projection, public events and visible command history.

    Includes existing checkpoints (including their decision indices). No
    private diagnostics or invisible command arguments are used. Equal physical
    states with different observations remain different information states.
    Belief objects, when added later, require their own versioned extension.
    """
    version: str
    viewer: str
    projection: tuple
    commands: tuple
    checkpoints: tuple


def rule_state_key(world):
    if not audited_fs(world):
        raise UnsupportedKey("only the audited built-in FS Game supports rule keys")
    return RuleStateKey("fs-rule-v2-hand-multisets", id(world.ruleset),
                        tuple((name, freeze(value)) for name, value in world.__dict__.items()
                              if name not in NON_RULE_HISTORY | {"ruleset"}))


def information_key(world, viewer="team"):
    if not audited_fs(world):
        raise UnsupportedKey("information keys currently require the audited FS engine")
    if viewer not in {"a", "b", "c", "team", "m", "spectator"}:
        raise ValueError("invalid information-key viewer")
    projection = world.protagonist_team_view() if viewer == "team" else world.view(viewer)
    commands = []
    for command in world.history:
        # Mastermind knows their own choices and all revealed card faces, not
        # hidden red card faces while cards are still being committed.
        if viewer == "m" and command["actor"] == "m":
            commands.append(freeze(command))
        else:
            commands.append(freeze(world._command_observation(viewer, command)))
    checkpoints = world.observation_records(viewer) if viewer in {"a", "b", "c", "team"} else ()
    return InformationKey("fs-information-v1", viewer, freeze(projection), tuple(commands), freeze(checkpoints))
