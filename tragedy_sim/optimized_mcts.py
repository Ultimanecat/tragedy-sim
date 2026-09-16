"""Optimized full-information MCTS while preserving the naive implementation.

This agent deliberately lives beside :mod:`tragedy_sim.mcts`: the latter is a
stable, exhaustive-action baseline.  This variant uses the engine's internal
search surface, progressive widening, and cheap forced-action rollouts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import random
from time import perf_counter
from typing import Any, Sequence

from .search import (Evaluator, MastermindEvaluator, RootActionStats,
                     SearchBudget, SearchGame, SearchTrace)
from .evaluation import ScenarioConditionedEvaluator


def _command_key(command: dict[str, Any]) -> str:
    return json.dumps(command, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


@dataclass
class _OptimizedNode:
    game: SearchGame
    parent: "_OptimizedNode | None" = None
    action: dict[str, Any] | None = None
    children: list["_OptimizedNode"] = field(default_factory=list)
    visits: int = 0
    value_sum: float = 0.0
    ordered_actions: list[dict[str, Any]] | None = None
    next_action: int = 0
    exhausted: bool = False

    @property
    def mean_value(self) -> float:
        return self.value_sum / self.visits if self.visits else 0.0


class OptimizedMctsMastermindAgent:
    """MCTS with progressive widening and a lightweight engine search path.

    The action prior only controls expansion order.  No legal action is
    discarded, so a sufficiently large budget still explores the full tree.
    """

    def __init__(self, budget: SearchBudget | None = None,
                 evaluator: Evaluator | None = None, *,
                 widening_constant: float = 2.0,
                 widening_exponent: float = 0.5):
        if widening_constant <= 0:
            raise ValueError("widening_constant must be positive")
        if not 0 < widening_exponent <= 1:
            raise ValueError("widening_exponent must be in (0, 1]")
        self.budget = budget or SearchBudget()
        self.evaluator = evaluator or ScenarioConditionedEvaluator()
        self.widening_constant = widening_constant
        self.widening_exponent = widening_exponent
        self.last_trace: SearchTrace | None = None
        self._candidate_actions = 0
        self._forced_transitions = 0
        self._retained_root: _OptimizedNode | None = None

    @property
    def plan_name(self) -> str:
        return "optimized_full_information_mcts"

    @staticmethod
    def _effect_text(game: SearchGame, action: dict[str, Any]) -> str:
        if action.get("action") != "choose":
            return ""
        try:
            choice = game.options(action["actor"])[action["index"] - 1]
        except (AttributeError, IndexError, KeyError, TypeError):
            return ""
        return json.dumps(choice, ensure_ascii=False, sort_keys=True, default=str)

    def _priority(self, game: SearchGame, action: dict[str, Any]) -> float:
        """Cheap mastermind-value prior; used only for widening order."""
        kind = action.get("action")
        if kind == "choose":
            text = self._effect_text(game, action)
            score = 30.0
            for marker, value in (("heroes_die", 100), ("finish_loop", 80),
                                  ('"lose"', 80), ('"kill"', 45),
                                  ("intrigue", 12), ("paranoia", 8)):
                if marker in text:
                    score += value
            return score
        if kind == "play":
            card = str(action.get("card", ""))
            target = action.get("target")
            role = game.roles.get(target)
            score = 0.0
            if card.startswith("i"):
                score += 18 if role == "key" else 13 if role == "killer" else 5
                score += 2 if card == "i2" else 0
            elif card.startswith("p"):
                culprits = {item.get("culprit") for item in game.scenario.get("incidents", ())
                            if item.get("day", 0) >= game.state.round}
                score += 16 if target in culprits else 4
            elif card in {"h", "v"}:
                score += 3 if role in {"key", "killer"} else 0
            return score
        if kind in {"resolve", "next"}:
            return -20.0
        return 0.0

    def _actions(self, node: _OptimizedNode, rng: random.Random) -> list[dict[str, Any]]:
        if node.ordered_actions is None:
            if node.game.winner is not None:
                node.ordered_actions = []
                node.exhausted = True
            else:
                actions = list(node.game.search_actions(node.game.controller))
                self._candidate_actions += len(actions)
                # Seeded shuffle makes equal-priority ordering reproducible without
                # inheriting a systematic preference from enumeration order.
                rng.shuffle(actions)
                maximizing = node.game.controller == "m"
                actions.sort(key=lambda item: self._priority(node.game, item),
                             reverse=maximizing)
                node.ordered_actions = actions
        return node.ordered_actions

    def _can_expand(self, node: _OptimizedNode, rng: random.Random) -> bool:
        actions = self._actions(node, rng)
        allowed = max(1, math.ceil(
            self.widening_constant * (node.visits + 1) ** self.widening_exponent))
        return node.next_action < len(actions) and len(node.children) < allowed

    def _select_child(self, node: _OptimizedNode,
                      rng: random.Random) -> _OptimizedNode:
        maximizing = node.game.controller == "m"
        log_parent = math.log(max(1, node.visits))

        def score(child: _OptimizedNode) -> float:
            if child.visits == 0:
                return math.inf
            exploitation = child.mean_value if maximizing else -child.mean_value
            exploration = self.budget.exploration * math.sqrt(log_parent / child.visits)
            return exploitation + exploration

        candidates = [child for child in node.children if not child.exhausted]
        if not candidates:
            raise ValueError("cannot select from an exhausted node")
        scored = [(score(child), child) for child in candidates]
        best = max(value for value, _ in scored)
        return rng.choice([child for value, child in scored if value == best])

    def _rollout(self, game: SearchGame,
                 rng: random.Random) -> tuple[float, int]:
        world = game
        depth = 0
        while world.winner is None and depth < self.budget.rollout_depth:
            actions = world.search_actions(world.controller)
            self._candidate_actions += len(actions)
            if not actions:
                break
            if len(actions) == 1:
                action = actions[0]
                self._forced_transitions += 1
            else:
                action = rng.choice(actions)
            world = world.search_transition(action)
            depth += 1
        return self.evaluator(world), depth

    def _propagate_exhaustion(self, node: _OptimizedNode,
                              rng: random.Random) -> None:
        cursor: _OptimizedNode | None = node
        while cursor is not None:
            actions = self._actions(cursor, rng)
            fully_expanded = cursor.next_action >= len(actions)
            if not fully_expanded or any(not child.exhausted for child in cursor.children):
                return
            cursor.exhausted = True
            cursor = cursor.parent

    def _trace_for_forced_action(self, game: SearchGame, typed: Any,
                                 root_hash: str, started: float) -> None:
        self._retained_root = None
        self.last_trace = SearchTrace(
            strategy=self.plan_name, seed=self.budget.seed,
            root_key_hash=root_hash, node_limit=self.budget.node_limit,
            rollout_depth=self.budget.rollout_depth,
            time_limit_ms=self.budget.time_limit_ms, nodes=1, iterations=0,
            max_depth=0, elapsed_ms=(perf_counter() - started) * 1000,
            stop_reason="forced_action", selected_action_id=typed.id,
            root_actions=(RootActionStats(
                action_id=typed.id, actor=typed.actor, kind=typed.kind,
                parameters=dict(typed.parameters), visits=0, mean_value=0.0),),
            candidate_actions=1, expanded_actions=0, forced_transitions=0,
            reused_nodes=0, retained_tree_nodes=0)

    @staticmethod
    def _tree_size(root: _OptimizedNode) -> int:
        return 1 + sum(OptimizedMctsMastermindAgent._tree_size(child)
                       for child in root.children)

    def _take_matching_subtree(self, root_key: str) -> tuple[_OptimizedNode | None, int]:
        """Return a retained descendant matching the actual private state."""
        if self._retained_root is None:
            return None, 0
        pending = [self._retained_root]
        while pending:
            candidate = pending.pop()
            if candidate.game.state_key("m") == root_key:
                candidate.parent = None
                count = self._tree_size(candidate)
                self._retained_root = None
                return candidate, count
            pending.extend(candidate.children)
        self._retained_root = None
        return None, 0

    def search(self, game: SearchGame) -> Any:
        if game.controller != "m":
            raise ValueError("optimized mastermind MCTS requires a mastermind decision")
        root_key = game.state_key("m")
        root_hash = SearchTrace.hash_state_key(root_key)
        rng = random.Random(f"{self.budget.seed}:{root_hash}:optimized")
        typed_offers = list(game.action_offers("m"))
        raw_actions = list(game.search_actions("m"))
        if not typed_offers or len(typed_offers) != len(raw_actions):
            raise ValueError("typed and internal search actions do not match")
        started = perf_counter()
        if len(raw_actions) == 1:
            self._trace_for_forced_action(game, typed_offers[0], root_hash, started)
            return typed_offers[0]

        self._candidate_actions = 0
        self._forced_transitions = 0
        root, reused_nodes = self._take_matching_subtree(root_key)
        if root is None:
            root = _OptimizedNode(game.search_clone())
        deadline = (None if self.budget.time_limit_ms is None else
                    started + self.budget.time_limit_ms / 1000)
        nodes = 1
        iterations = 0
        max_depth = 0
        stop_reason = "node_limit"

        while nodes < self.budget.node_limit:
            if root.exhausted:
                stop_reason = "tree_exhausted"
                break
            if deadline is not None and perf_counter() >= deadline:
                stop_reason = "time_limit"
                break
            node = root
            tree_depth = 0
            while node.game.winner is None:
                if self._can_expand(node, rng):
                    action = self._actions(node, rng)[node.next_action]
                    node.next_action += 1
                    child = _OptimizedNode(
                        node.game.search_transition(action), parent=node, action=action)
                    node.children.append(child)
                    node = child
                    nodes += 1
                    tree_depth += 1
                    break
                available = [child for child in node.children if not child.exhausted]
                if not available:
                    # Progressive widening may temporarily close expansion only
                    # when children exist; with none, the position is terminal.
                    if not self._actions(node, rng):
                        node.exhausted = True
                    break
                node = self._select_child(node, rng)
                tree_depth += 1

            reward, rollout_depth = self._rollout(node.game, rng)
            max_depth = max(max_depth, tree_depth + rollout_depth)
            leaf = node
            while node is not None:
                node.visits += 1
                node.value_sum += reward
                node = node.parent
            self._propagate_exhaustion(leaf, rng)
            iterations += 1

        children = {_command_key(child.action): child for child in root.children}
        ranked: list[tuple[int, int, float, Any]] = []
        for typed, raw in zip(typed_offers, raw_actions):
            child = children.get(_command_key(raw))
            terminal_rank = (2 if child and child.game.winner == "mastermind" else
                             0 if child and child.game.winner is not None else 1)
            ranked.append((terminal_rank, child.visits if child else 0,
                           child.mean_value if child else float("-inf"), typed))
        best_rank = max((terminal, visits, value)
                        for terminal, visits, value, _ in ranked)
        selected = rng.choice([typed for terminal, visits, value, typed in ranked
                               if (terminal, visits, value) == best_rank])
        retained = children.get(_command_key(raw_actions[
            next(index for index, typed in enumerate(typed_offers)
                 if typed.id == selected.id)]))
        if retained is not None:
            # Detach the chosen branch immediately so discarded siblings and
            # ancestors can be collected between real decisions.
            retained.parent = None
        self._retained_root = retained
        retained_tree_nodes = self._tree_size(retained) if retained is not None else 0
        root_stats = tuple(RootActionStats(
            action_id=typed.id, actor=typed.actor, kind=typed.kind,
            parameters=dict(typed.parameters),
            visits=children[_command_key(raw)].visits
            if _command_key(raw) in children else 0,
            mean_value=children[_command_key(raw)].mean_value
            if _command_key(raw) in children else 0.0,
        ) for typed, raw in zip(typed_offers, raw_actions))
        self.last_trace = SearchTrace(
            strategy=self.plan_name, seed=self.budget.seed,
            root_key_hash=root_hash, node_limit=self.budget.node_limit,
            rollout_depth=self.budget.rollout_depth,
            time_limit_ms=self.budget.time_limit_ms, nodes=nodes,
            iterations=iterations, max_depth=max_depth,
            elapsed_ms=(perf_counter() - started) * 1000,
            stop_reason=stop_reason, selected_action_id=selected.id,
            root_actions=root_stats, candidate_actions=self._candidate_actions,
            expanded_actions=nodes - 1,
            forced_transitions=self._forced_transitions,
            reused_nodes=reused_nodes,
            retained_tree_nodes=retained_tree_nodes)
        return selected

    def choose_game_action(self, *, participant: str, game: SearchGame,
                           offers: Sequence[dict[str, Any]]) -> dict[str, Any]:
        if participant != "m":
            raise ValueError("optimized mastermind MCTS can only control seat m")
        typed = list(game.action_offers("m"))
        if len(typed) != len(offers):
            raise ValueError("service offers do not match the search root")
        chosen = self.search(game)
        return offers[next(index for index, action in enumerate(typed)
                           if action.id == chosen.id)]

    def choose_action(self, *, participant: str, view: dict[str, Any],
                      offers: Sequence[dict[str, Any]]) -> dict[str, Any]:
        del participant, view, offers
        raise ValueError("optimized MCTS requires an isolated engine search clone")
