"""Native FS ability trees with shared authorized perfect-recall decisions.

Both players optimize their actual information-set policies. Selected root
card domains remain explicitly restricted; they are not global certificates.
Truncation and missing posterior mass have [0,1] leaves, never guessed values.
"""

from dataclasses import asdict, dataclass
from fractions import Fraction as Q
import hashlib
import json

from ..domain import InformationState
from .continuation import WorkLimit, day_boundary_value
from .engine_game import red_commands
from .fair_engine import FixedPolicyDayGame, HistoryDayGame, public_policy_input
from .keys import audited_fs
from .matrix import MatrixLimit, rational
from .pure import commit_pair
from .sequence_form import (Chance, Decision, Terminal, behavioral_policy, build_sequence_game,
                            solve_sequence_game)
from .zero_sum import RationalInterval


def _key(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_key(value).encode()).hexdigest()


def authorized_information(world, actions, recall=""):
    """No hidden type, branch number, private black count or policy RNG for red.

    Recall records a player's own past information sets and choices, including
    observations later overwritten in the current projection. It never records
    the opponent's hidden decisions. Legal option labels are actually offered.
    """
    actor = world.controller
    if actor == "m":
        own = [c for c in world.history if c.get("actor") == "m"]
        info = InformationState.create("m", dict(state=world.view("m"), own_commands=own,
                         offers=sorted(actions, key=_key)))
    else:
        info = public_policy_input(world, actions)
    labels = [option.get("label", "") for option in world.options(actor)]
    return ("m/" if actor == "m" else "r/") + _digest((recall, info.key, labels))


def _remember(recall, information, action):
    return _digest((recall, information, action))


def column_identity(column):
    """Physical action identity, stable across selected-domain permutations."""
    if len(column) == 2 and type(column[0]) is int:
        return _key(dict(history=column[0], faces=[asdict(p) for p in column[1]]))
    return _key(dict(faces=[asdict(p) for p in column]))


@dataclass(frozen=True)
class InformationTree:
    lower: object
    upper: object
    continuation_complete: bool
    unknown_leaves: int
    stop_reasons: tuple
    engine_nodes: int
    engine_transitions: int
    root_domain_complete: bool
    belief_domain_complete: bool
    root_information: str | None = None
    root_plans: tuple = ()
    scope: str = "FS/native-abilities/authorized-perfect-recall/day-survival-v1"
    source_scope: str = "caller-supplied-finite-setup-types"
    root_columns: tuple = ()


class _Builder:
    def __init__(self, *, work, max_depth, tree_node_limit, fixed_behavior=None):
        if type(max_depth) is not int or max_depth < 1 or type(tree_node_limit) is not int or tree_node_limit < 1:
            raise ValueError("information tree limits must be positive integers")
        self.work = WorkLimit(node_limit=10000) if work is None else work
        self.before = self.work.nodes, self.work.transitions
        self.max_depth, self.tree_node_limit = max_depth, tree_node_limit
        self.unknown, self.reasons = 0, set()
        self.tree_nodes = 0
        self.fixed_behavior = fixed_behavior

    def account(self, count=1):
        self.tree_nodes += count
        if self.tree_nodes > self.tree_node_limit:
            raise MatrixLimit("tree_node_limit")

    def unknown_leaf(self, reason):
        self.account()
        self.unknown += 1
        self.reasons.add(reason)
        return Terminal(0), Terminal(1)

    def visit(self, world, position, recall=("", ""), depth=0):
        boundary = day_boundary_value(world, position)
        if boundary is not None:
            self.account()
            leaf = Terminal(rational(boundary))
            return leaf, leaf
        if self.work.exhausted():
            return self.unknown_leaf("/".join(sorted(self.work.reasons)))
        if depth >= self.max_depth:
            return self.unknown_leaf("continuation_depth_limit")
        actions = world.legal_actions(world.controller)
        if not actions:
            raise ValueError("nonterminal information node has no legal actions")
        self.work.nodes += 1
        index = int(world.controller == "m")
        information = authorized_information(world, actions, recall[index])
        player = "black" if index else "red"
        fixed = self.fixed_behavior is not None and self.fixed_behavior.player == player
        distribution = (self.fixed_behavior.choices(information, actions) if fixed else
                        tuple((a, None) for a in sorted(actions, key=_key)))
        lower, upper = [], []
        for action, probability in distribution:
            name = _key(action)
            if self.work.exhausted():
                lo, hi = self.unknown_leaf("/".join(sorted(self.work.reasons)))
            else:
                successor = world.transition(action).game
                self.work.transitions += 1
                memory = list(recall)
                memory[index] = _remember(recall[index], information, name)
                lo, hi = self.visit(successor, position, tuple(memory), depth+1)
            lower.append((probability if fixed else name, lo))
            upper.append((probability if fixed else name, hi))
        if len(distribution) == 1:
            # Forced steps have no strategic choice. Their authorized
            # observations/own action STILL enter recall before the child.
            return lower[0][1], upper[0][1]
        self.account()
        if fixed:
            return Chance(tuple(lower)), Chance(tuple(upper))
        return Decision(player, information, tuple(lower)), Decision(player, information, tuple(upper))

    def finish(self, lower, upper, *, root_complete, belief_complete, root_information=None, root_plans=(), source_scope=None,
               root_columns=()):
        deadline = None if self.work.time_limit_ms is None else self.work.started+self.work.time_limit_ms/1000
        lower_model = build_sequence_game(lower, node_limit=self.tree_node_limit, max_depth=self.max_depth+5, deadline=deadline)
        upper_model = (build_sequence_game(upper, node_limit=self.tree_node_limit, max_depth=self.max_depth+5, deadline=deadline)
                       if self.unknown else lower_model)
        tree = InformationTree(lower_model, upper_model, not self.unknown, self.unknown,
            tuple(sorted(self.reasons)), self.work.nodes-self.before[0], self.work.transitions-self.before[1],
            root_complete, belief_complete, root_information, root_plans)
        from dataclasses import replace
        tree = replace(tree, root_columns=root_columns,
                       source_scope=tree.source_scope if source_scope is None else source_scope)
        return tree


def _weighted_worlds(worlds, belief_domain_complete):
    worlds = tuple((label, rational(mass), world) for label, mass, world in worlds)
    if (not worlds or any(type(label) is not str or not label or mass <= 0 or not audited_fs(world)
                          for label, mass, world in worlds)
            or len({label for label, _, _ in worlds}) != len(worlds)):
        raise ValueError("unique weighted audited FS worlds are required")
    total = sum(mass for _, mass, _ in worlds)
    if type(belief_domain_complete) is not bool or total > 1 or (belief_domain_complete and total != 1):
        raise ValueError("original masses exceed one or asserted coverage is incomplete")
    return worlds, total


def build_ability_information_tree(worlds, *, work=None, max_depth=128, tree_node_limit=10000,
                                   belief_domain_complete=False):
    worlds, total = _weighted_worlds(worlds, belief_domain_complete)
    if any(world.state.phase in {"day_start", "mastermind", "protagonists"} for _, _, world in worlds):
        raise ValueError("ability roots require already committed cards")
    if any(public_policy_input(world).key != public_policy_input(worlds[0][2]).key for _, _, world in worlds):
        raise ValueError("ability roots have different authorized red information")
    builder = _Builder(work=work, max_depth=max_depth, tree_node_limit=tree_node_limit)
    builder.account()  # chance root
    lower, upper = [], []
    for _, mass, world in worlds:
        lo, hi = builder.visit(world, (world.state.loop, world.state.round))
        lower.append((mass, lo))
        upper.append((mass, hi))
    if total < 1:
        lo, hi = builder.unknown_leaf("unrepresented_mass")
        lower.append((1-total, lo))
        upper.append((1-total, hi))
    return builder.finish(Chance(tuple(lower)), Chance(tuple(upper)), root_complete=True,
                          belief_complete=belief_domain_complete)


def build_root_information_tree(model, rows, columns, *, work=None, max_depth=128, tree_node_limit=10000):
    """columns is one finite selected-column tuple per setup block.

    Black commits history/faces before the common red private card draw.
    Native ability choices then use authorized recall, with no fixed policy.
    """
    rows, columns = tuple(rows), tuple(tuple(c) for c in columns)
    if (not rows or len(set(rows)) != len(rows) or not all(model.contains_row(r) for r in rows)
            or len(columns) != len(model.blocks)):
        raise ValueError("distinct common legal rows and per-world columns are required")
    for block, selected in zip(model.blocks, columns):
        if (not isinstance(block.game, (FixedPolicyDayGame, HistoryDayGame)) or not selected
                or len(set(selected)) != len(selected) or not all(block.game.contains_column(c) for c in selected)):
            raise ValueError("selected columns must belong to audited FS fixed-root models")
    builder = _Builder(work=work, max_depth=max_depth, tree_node_limit=tree_node_limit)
    builder.account(1+len(model.blocks)+sum(len(c) for c in columns))
    root_info = "r/root-cards"
    plans = tuple((_key(red_commands(row)), row) for row in rows)
    lower, upper = [], []
    for block, selected in zip(model.blocks, columns):
        black_lo, black_hi = [], []
        black_info = "m/root-faces/" + block.label
        for column in selected:
            if isinstance(block.game, HistoryDayGame):
                variant, faces = block.game.variants[column[0]], column[1]
            else:
                variant, faces = block.game, column
            # Internal label identifies an action known to its own player.
            # It never enters the red information identity or recall.
            black_action = column_identity(column)
            red_lo, red_hi = [], []
            for action, row in plans:
                if builder.work.exhausted():
                    lo, hi = builder.unknown_leaf("/".join(sorted(builder.work.reasons)))
                else:
                    builder.work.nodes += 1
                    after = commit_pair(variant._root, red_commands(row), faces)
                    builder.work.transitions += len(row)
                    recall = (_remember("", root_info, action), _remember("", black_info, black_action))
                    lo, hi = builder.visit(after, (variant._root.state.loop, variant._root.state.round), recall)
                red_lo.append((action, lo))
                red_hi.append((action, hi))
            black_lo.append((black_action, Decision("red", root_info, tuple(red_lo))))
            black_hi.append((black_action, Decision("red", root_info, tuple(red_hi))))
        lower.append((block.mass, Decision("black", black_info, tuple(black_lo))))
        upper.append((block.mass, Decision("black", black_info, tuple(black_hi))))
    if model.missing_mass:
        lo, hi = builder.unknown_leaf("unrepresented_mass")
        lower.append((model.missing_mass, lo))
        upper.append((model.missing_mass, hi))
    root_complete = (len(rows) == model.row_count and all(len(c) == b.game.column_count for b, c in zip(model.blocks, columns)))
    return builder.finish(Chance(tuple(lower)), Chance(tuple(upper)), root_complete=root_complete,
                          belief_complete=model.belief_domain_complete, root_information=root_info, root_plans=plans,
                          source_scope=model.scope,
                          root_columns=tuple((b.label, tuple((column_identity(c), c) for c in cols))
                                             for b, cols in zip(model.blocks, columns)))


@dataclass(frozen=True)
class InformationSolution:
    bounds: RationalInterval
    lower_solution: object
    upper_solution: object
    red_behavior: tuple
    black_behavior: tuple
    red_cards: tuple
    certified_optimal: bool


def solve_information_tree(tree, *, pivot_limit=100000, deadline=None, lp_cell_limit=2000000):
    lower = solve_sequence_game(tree.lower, pivot_limit=pivot_limit, deadline=deadline, lp_cell_limit=lp_cell_limit)
    upper = (lower if tree.upper is tree.lower else
             solve_sequence_game(tree.upper, pivot_limit=pivot_limit, deadline=deadline, lp_cell_limit=lp_cell_limit))
    behavior = behavioral_policy(tree.lower.red, lower.red)
    cards = dict(dict(behavior).get(tree.root_information, ()))
    red_cards = tuple((plan, cards[action]) for action, plan in tree.root_plans if cards.get(action))
    bounds = RationalInterval(lower.value, upper.value)
    return InformationSolution(bounds, lower, upper, behavior, behavioral_policy(tree.upper.black, upper.black), red_cards,
        bounds.exact and tree.continuation_complete and tree.root_domain_complete and tree.belief_domain_complete)
