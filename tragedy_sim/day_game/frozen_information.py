"""Immutable full-domain strategy extensions for information-set separation."""

from dataclasses import dataclass, field
from types import MappingProxyType

from .information_game import _digest, _key, column_identity
from .matrix import rational


@dataclass(frozen=True)
class FrozenBehavior:
    player: str
    table: tuple = ()
    version: str = field(init=False)

    def __post_init__(self):
        if self.player not in {"red", "black"}:
            raise ValueError("frozen behavior needs a valid player")
        normalized, seen = [], set()
        for information, choices in self.table:
            choices = tuple((action, rational(p)) for action, p in choices)
            if (type(information) is not str or not information or information in seen or not choices
                    or any(type(a) is not str or not a or p < 0 for a, p in choices)
                    or len({a for a, _ in choices}) != len(choices) or sum(p for _, p in choices) != 1):
                raise ValueError("invalid frozen conditional behavior")
            normalized.append((information, tuple(sorted((a, p) for a, p in choices if p))))
            seen.add(information)
        normalized = tuple(sorted(normalized))
        object.__setattr__(self, "table", normalized)
        object.__setattr__(self, "_lookup", MappingProxyType(dict(normalized)))
        version = _digest((self.player, tuple((i, tuple((a, str(p)) for a, p in c)) for i, c in normalized), "next-first-v1"))
        object.__setattr__(self, "version", "frozen-observable-v1/"+version)

    def choices(self, information, actions):
        """Only an authorized identity and a legal menu enter the policy.

        Unknown information sets have a fixed next/pass-first extension.
        Known information sets returning illegal actions are errors, not a
        reason to silently change a supposedly frozen opponent policy.
        """
        legal = {_key(action): action for action in actions}
        if not legal:
            raise ValueError("frozen policy received an empty menu")
        known = self._lookup.get(information)
        if known is None:
            action = next((legal[k] for k in sorted(legal) if legal[k]["action"] in {"next", "pass"}), legal[min(legal)])
            return ((dict(action), rational(1)),)
        if any(action not in legal for action, _ in known):
            raise ValueError("frozen behavior has an illegal known action")
        return tuple((dict(legal[action]), p) for action, p in known)


@dataclass(frozen=True)
class FrozenInformationStrategy:
    red_cards: tuple
    black_cards: tuple  # (setup label, conditional (physical column, p) pairs)
    red_policy: FrozenBehavior
    black_policy: FrozenBehavior
    version: str = field(init=False)

    def __post_init__(self):
        from .engine_game import red_commands
        red = tuple((row, rational(p)) for row, p in self.red_cards)
        black = tuple((label, tuple((column, rational(p)) for column, p in choices)) for label, choices in self.black_cards)
        if (not red or any(p <= 0 for _, p in red) or sum(p for _, p in red) != 1
                or len({row for row, _ in red}) != len(red) or not black
                or any(not choices or any(p <= 0 for _, p in choices) or sum(p for _, p in choices) != 1
                       or len({column for column, _ in choices}) != len(choices) for _, choices in black)
                or len({label for label, _ in black}) != len(black)
                or self.red_policy.player != "red" or self.black_policy.player != "black"):
            raise ValueError("invalid complete root strategy distribution")
        object.__setattr__(self, "red_cards", red)
        object.__setattr__(self, "black_cards", black)
        identity = (tuple((_key(red_commands(r)), str(p)) for r, p in red),
                    tuple((h, tuple((column_identity(c), str(p)) for c, p in choices)) for h, choices in black),
                    self.red_policy.version, self.black_policy.version)
        object.__setattr__(self, "version", "frozen-information-root-v1/"+_digest(identity))


def freeze_information_solution(tree, solution):
    if tree.root_information is None or not solution.red_cards:
        raise ValueError("a solved root card information game is required")
    behavior = dict(solution.black_behavior)
    black = []
    for label, columns in tree.root_columns:
        policy = dict(behavior["m/root-faces/"+label])
        black.append((label, tuple((column, policy[action]) for action, column in columns if policy.get(action))))
    return FrozenInformationStrategy(solution.red_cards, tuple(black),
        FrozenBehavior("red", tuple((i, c) for i, c in solution.red_behavior if i != tree.root_information)),
        FrozenBehavior("black", tuple((i, c) for i, c in solution.black_behavior if not i.startswith("m/root-faces/"))))
