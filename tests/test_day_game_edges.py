"""Raw execution/resource inputs and authorized observation forks stay distinct."""

from dataclasses import FrozenInstanceError
import json
import unittest

from tests.test_day_game import root, commit, brute_day
from tests.test_day_game_local_cards import same_world
from tragedy_sim.day_game import ValueBounds, PureDaySolver
from tragedy_sim.day_game.cached import CachedDayContinuationSolver
from tragedy_sim.day_game.edges import execution_graph, TransitionEdgeCache
from tragedy_sim.day_game.kernel import FsTransitionKernel
from tragedy_sim.day_game.keys import rule_state_key, information_key


class ExecutionGraphTests(unittest.TestCase):
    def test_clone_equivalence_and_raw_hand_order(self):
        world = commit(root())
        clone = world.clone()
        self.assertEqual(execution_graph(world), execution_graph(clone))
        clone.state.hands["a"].reverse()
        self.assertEqual(rule_state_key(world), rule_state_key(clone))
        self.assertEqual(information_key(world), information_key(clone))
        self.assertNotEqual(execution_graph(world), execution_graph(clone))

    def test_mutable_aliases_and_cycles_are_encoded_without_addresses(self):
        world = commit(root())
        world.extra_left = []
        world.extra_right = world.extra_left
        copied = world.clone()
        self.assertEqual(execution_graph(world), execution_graph(copied))
        copied.extra_right = []
        self.assertEqual(rule_state_key(world), rule_state_key(copied))
        self.assertNotEqual(execution_graph(world), execution_graph(copied))
        world.extra_left.append(world.extra_left)
        self.assertEqual(execution_graph(world), execution_graph(world.clone()))


class TransitionObservationEdgeTests(unittest.TestCase):
    def test_repeated_transition_is_exact_detached_and_records_legal_viewer_branches(self):
        world = commit(root())
        action = world.legal_actions(world.controller)[0]
        kernel = FsTransitionKernel(compiled=True, edge_cache_capacity=4)
        gold = world.transition(action).game
        first = kernel.transition(world, action)
        same_world(self, first, gold)
        before_graph = execution_graph(world)
        first.state.events[0]["message"] = "mutated"
        first.history[0]["action"] = "mutated"
        second = kernel.transition(world, action)
        same_world(self, second, gold)
        self.assertEqual(kernel.edges.stats.hits, 1)
        self.assertEqual(kernel.program_stats.movements, 1)
        self.assertEqual(execution_graph(world), before_graph)
        branch = kernel.edges.observation(world, action, "team")
        self.assertEqual(branch.before, information_key(world))
        self.assertEqual(branch.after, information_key(gold))
        self.assertFalse(branch.replaces_event_history)
        self.assertIsNotNone(branch.events)
        self.assertEqual(branch.after_observation.to_dict(), json.loads(json.dumps(gold.protagonist_team_view())))
        detached_view = branch.after_observation.to_dict()
        detached_view["characters"]["girl"]["paranoia"] = 1000
        self.assertNotEqual(branch.after_observation.to_dict(), detached_view)
        with self.assertRaises(FrozenInstanceError):
            branch.viewer = "m"
        with self.assertRaises(ValueError):
            kernel.edges.observation(world, action, "a")
        self.assertEqual(kernel.edges.observation(world, action, "m").after, information_key(gold, "m"))

    def test_same_rule_state_different_observation_history_does_not_hit(self):
        world = commit(root())
        changed = world.clone()
        changed._event("public_test", "different history")
        self.assertEqual(rule_state_key(world), rule_state_key(changed))
        kernel = FsTransitionKernel(compiled=True, edge_cache_capacity=4)
        action = world.legal_actions(world.controller)[0]
        first = kernel.transition(world, action)
        second = kernel.transition(changed, action)
        self.assertEqual(kernel.edges.stats.hits, 0)
        self.assertEqual(kernel.edges.stats.stores, 2)
        self.assertNotEqual(information_key(first), information_key(second))
        same_world(self, second, changed.transition(action).game)

    def test_raw_resource_order_is_not_replaced_by_rule_equivalent_successor(self):
        world = commit(root())
        changed = world.clone()
        changed.state.hands["b"].reverse()
        kernel = FsTransitionKernel(compiled=True, edge_cache_capacity=4)
        action = world.legal_actions(world.controller)[0]
        kernel.transition(world, action)
        second = kernel.transition(changed, action)
        self.assertEqual(kernel.edges.stats.hits, 0)
        same_world(self, second, changed.transition(action).game)

    def test_diagnostic_history_does_not_prevent_safe_hit(self):
        world = commit(root())
        changed = world.clone()
        changed.decisions.append("private output only")
        kernel = FsTransitionKernel(compiled=True, edge_cache_capacity=4)
        action = world.legal_actions(world.controller)[0]
        first = kernel.transition(world, action)
        second = kernel.transition(changed, action)
        self.assertEqual(kernel.edges.stats.hits, 1)
        same_world(self, second, first)

    def test_capacity_and_unsupported_fields_fall_back_without_changing_rule_result(self):
        world = commit(root())
        kernel = FsTransitionKernel(compiled=True, edge_cache_capacity=1)
        action = world.legal_actions(world.controller)[0]
        child = kernel.transition(world, action)
        kernel.transition(child, child.legal_actions(child.controller)[0])
        self.assertEqual(len(kernel.edges), 1)
        self.assertGreater(kernel.edges.stats.evictions, 0)
        self.assertIsNone(kernel.edges.observation(world, action, "team"))
        world.unreviewed = object()
        result = kernel.transition(world, action)
        self.assertEqual(result.state, world.transition(action).game.state)
        self.assertGreater(kernel.edges.stats.fallbacks, 0)
        self.assertGreater(kernel.fallback_clones, 0)

    def test_minimax_with_observation_cache_matches_independent_gold(self):
        solver = CachedDayContinuationSolver(compiled=True, edge_cache_capacity=8)
        for faces in (("d", "p-1", "h"), ("d", "fg", "h")):
            world = commit(root(faces))
            expected = brute_day(world, (2, 2))
            self.assertEqual(solver.solve(world).bounds, ValueBounds(expected, expected))
        self.assertLessEqual(len(solver.kernel.edges), 8)
        self.assertGreater(solver.kernel.edges.stats.stores, 0)

    def test_disabled_by_default_and_capacity_viewer_configuration(self):
        self.assertIsNone(FsTransitionKernel().edges)
        cache = TransitionEdgeCache(2, viewers=("a", "m"))
        self.assertEqual(cache.viewers, ("a", "m"))
        for value in (True, -1, 1.2):
            with self.assertRaises(ValueError):
                FsTransitionKernel(edge_cache_capacity=value)
        for value in (True, 0, -1, 1.2):
            with self.assertRaises(ValueError):
                TransitionEdgeCache(value)
        for viewers in ((), ("a", "a"), ("unknown",), (["a"],)):
            with self.assertRaises(ValueError):
                TransitionEdgeCache(1, viewers=viewers)
        with self.assertRaises(ValueError):
            PureDaySolver(edge_cache_capacity=2)


if __name__ == "__main__":
    unittest.main()
