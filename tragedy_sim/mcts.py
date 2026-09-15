"""Full-information Monte Carlo tree search over the typed game API."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import random
from time import perf_counter
from typing import Any, Sequence

from .search import (Evaluator, MastermindEvaluator, RootActionStats,
                     SearchBudget, SearchGame, SearchTrace)


@dataclass
class _Node:
    game: SearchGame
    parent: "_Node | None" = None
    action: Any | None = None
    children: list["_Node"] = field(default_factory=list)
    visits: int = 0
    value_sum: float = 0.0
    unexpanded: list[Any] | None = None
    exhausted: bool = False

    @property
    def mean_value(self) -> float:
        return self.value_sum / self.visits if self.visits else 0.0

    def actions(self) -> list[Any]:
        if self.unexpanded is None:
            if self.game.winner is not None:
                self.unexpanded = []
                self.exhausted = True
            else:
                self.unexpanded = list(self.game.action_offers(self.game.controller))
        return self.unexpanded


class FullInformationMctsMastermindAgent:
    """UCT search with random rollouts and a mastermind-side value function.

    Opponent nodes minimize the same root value.  The fixed seed is mixed with
    the root state hash, so node-limited searches are reproducible per position.
    """

    def __init__(self, budget: SearchBudget | None = None,
                 evaluator: Evaluator | None = None):
        self.budget = budget or SearchBudget()
        self.evaluator = evaluator or MastermindEvaluator()
        self.last_trace: SearchTrace | None = None

    @property
    def plan_name(self) -> str:
        return "full_information_mcts"

    def _select_child(self, node: _Node, rng: random.Random) -> _Node:
        maximizing = node.game.controller == "m"
        log_parent = math.log(max(1, node.visits))

        def score(child: _Node) -> float:
            if child.visits == 0:
                return math.inf
            exploitation = child.mean_value if maximizing else -child.mean_value
            exploration = self.budget.exploration * math.sqrt(log_parent / child.visits)
            return exploitation + exploration

        scores = [(score(child), child) for child in node.children if not child.exhausted]
        if not scores:
            raise ValueError("cannot select from an exhausted node")
        best = max(value for value, _ in scores)
        return rng.choice([child for value, child in scores if value == best])

    def _rollout(self, game: SearchGame, rng: random.Random) -> tuple[float, int]:
        world = game
        depth = 0
        while world.winner is None and depth < self.budget.rollout_depth:
            offers = world.action_offers(world.controller)
            if not offers:
                break
            world = world.transition(rng.choice(offers)).game
            depth += 1
        return self.evaluator(world), depth

    @staticmethod
    def _propagate_exhaustion(node: _Node) -> None:
        cursor: _Node | None = node
        while cursor is not None:
            if cursor.actions() or any(not child.exhausted for child in cursor.children):
                return
            cursor.exhausted = True
            cursor = cursor.parent

    def search(self, game: SearchGame) -> Any:
        if game.controller != "m":
            raise ValueError("full-information mastermind MCTS requires a mastermind decision")
        root_key = game.state_key("m")
        root_hash = SearchTrace.hash_state_key(root_key)
        rng = random.Random(f"{self.budget.seed}:{root_hash}")
        root = _Node(game.clone())
        root_offers = list(root.actions())
        if not root_offers:
            raise ValueError("cannot choose from an empty action list")

        started = perf_counter()
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
                actions = node.actions()
                if actions:
                    action = actions.pop(rng.randrange(len(actions)))
                    successor = node.game.transition(action).game
                    child = _Node(successor, parent=node, action=action)
                    node.children.append(child)
                    node = child
                    nodes += 1
                    tree_depth += 1
                    break
                available_children = [child for child in node.children if not child.exhausted]
                if not available_children:
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
            self._propagate_exhaustion(leaf)
            iterations += 1

        by_id = {child.action.id: child for child in root.children}
        ranked = []
        for action in root_offers:
            child = by_id.get(action.id)
            terminal_rank = (2 if child and child.game.winner == "mastermind" else
                             0 if child and child.game.winner is not None else 1)
            ranked.append((terminal_rank, child.visits if child else 0,
                           child.mean_value if child else float("-inf"), action))
        best_rank = max((terminal, visits, value)
                        for terminal, visits, value, _ in ranked)
        selected = rng.choice([action for terminal, visits, value, action in ranked
                               if (terminal, visits, value) == best_rank])
        elapsed = (perf_counter() - started) * 1000
        root_stats = tuple(RootActionStats(
            action_id=action.id, actor=action.actor, kind=action.kind,
            parameters=dict(action.parameters),
            visits=by_id[action.id].visits if action.id in by_id else 0,
            mean_value=by_id[action.id].mean_value if action.id in by_id else 0.0,
        ) for action in root_offers)
        self.last_trace = SearchTrace(
            strategy="full_information_mcts", seed=self.budget.seed,
            root_key_hash=root_hash, node_limit=self.budget.node_limit,
            rollout_depth=self.budget.rollout_depth,
            time_limit_ms=self.budget.time_limit_ms, nodes=nodes,
            iterations=iterations, max_depth=max_depth, elapsed_ms=elapsed,
            stop_reason=stop_reason, selected_action_id=selected.id,
            root_actions=root_stats,
        )
        return selected

    def choose_game_action(self, *, participant: str, game: SearchGame,
                           offers: Sequence[dict[str, Any]]) -> dict[str, Any]:
        if participant != "m":
            raise ValueError("full-information mastermind MCTS can only control seat m")
        typed = list(game.action_offers("m"))
        if len(typed) != len(offers):
            raise ValueError("service offers do not match the search root")
        chosen = self.search(game)
        return offers[next(index for index, action in enumerate(typed)
                           if action.id == chosen.id)]

    def choose_action(self, *, participant: str, view: dict[str, Any],
                      offers: Sequence[dict[str, Any]]) -> dict[str, Any]:
        del participant, view, offers
        raise ValueError("full-information MCTS requires an isolated engine search clone")
