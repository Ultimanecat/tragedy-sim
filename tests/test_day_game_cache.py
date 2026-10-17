"""Independent full-engine comparisons for FS transpositions and observations."""

from copy import deepcopy
from dataclasses import replace
from collections import UserDict
from types import MappingProxyType
import unittest

from tests.test_day_game import root, commit, brute_day
from tests import test_day_game as gold_tests
from tragedy_sim import Game
from tragedy_sim.day_game import DayContinuationSolver, WorkLimit, ValueBounds, CompleteCardSpace, commit_pair, PureDaySolver
from tragedy_sim.day_game.cached import CachedDayContinuationSolver
from tragedy_sim.day_game.kernel import FsTransitionKernel
from tragedy_sim.day_game.keys import (UnsupportedKey, freeze, information_key,
                                      rule_state_key)


def assert_same_rule_state(test, actual, expected):
    test.assertEqual(actual.state, expected.state)
    test.assertEqual(rule_state_key(actual), rule_state_key(expected))
    for viewer in ("team", "a", "b", "c", "m", "spectator"):
        test.assertEqual(information_key(actual, viewer), information_key(expected, viewer))
    test.assertEqual(actual.legal_actions(actual.controller), expected.legal_actions(expected.controller))


class DayGameKeyTests(unittest.TestCase):
    def test_keys_retain_all_rule_fields_and_ignore_only_output_history(self):
        world = commit(root())
        original = rule_state_key(world)
        for name, change in (
            ("per-seat resource", lambda g: g.state.hands["a"].remove("fm")),
            ("discarded owner", lambda g: g.state.discarded["b"].append("fm")),
            ("private use", lambda g: g.day_used.add("private")),
            ("public use", lambda g: g.public_day_used.add("public")),
            ("initial identity", lambda g: g.scenario["cast"].update(girl="ordinary")),
            ("current identity", lambda g: g.roles.update(girl="ordinary")),
            ("guard", lambda g: g.guards.update(girl=1)),
            ("queue", lambda g: g._queue.append({"kind": "counter", "target": "girl", "amount": 1})),
            ("once", lambda g: g.loop_used.add("once")),
            ("knowledge", lambda g: g.protagonist_knowledge.update(roles={"girl": "key"})),
            ("extra state", lambda g: setattr(g.state, "future_flag", True)),
            ("extra engine", lambda g: setattr(g, "future_flag", True)),
        ):
            with self.subTest(name=name):
                changed = world.clone()
                change(changed)
                self.assertNotEqual(original, rule_state_key(changed))
        changed = world.clone()
        changed._event("public_test", "different observation")
        changed.history.append({"actor": "m", "action": "next"})
        self.assertEqual(original, rule_state_key(changed))
        self.assertNotEqual(information_key(world), information_key(changed))

    def test_order_type_and_mandatory_snapshot_are_not_collapsed(self):
        self.assertNotEqual(freeze({"x": 1, "y": 2}), freeze({"y": 2, "x": 1}))
        self.assertNotEqual(freeze([1]), freeze((1,)))
        self.assertNotEqual(freeze(True), freeze(1))
        self.assertNotEqual(freeze({"x": 1}), freeze(MappingProxyType({"x": 1})))
        world = commit(root())
        while world._timing_window is None:
            world = world.transition(world.legal_actions(world.controller)[0]).game
        changed = world.clone()
        changed._timing_window.stage = "other"
        self.assertNotEqual(rule_state_key(world), rule_state_key(changed))

    def test_hidden_faces_and_other_seat_checkpoints_do_not_enter_team_key(self):
        from tragedy_sim.belief import ObservationCheckpoint

        left, right = root(), root(("v", "fp", "h"))
        self.assertEqual(information_key(left), information_key(right))
        self.assertNotEqual(rule_state_key(left), rule_state_key(right))
        changed = left.clone()
        checkpoint = changed._observation_checkpoints[-1]
        # Change a different seat's private digest while preserving team data.
        changed._observation_checkpoints[-1] = replace(checkpoint, digests=tuple(
            (viewer, "different" if viewer == "b" else digest) for viewer, digest in checkpoint.digests))
        self.assertEqual(information_key(left), information_key(changed))
        self.assertNotEqual(information_key(left, "b"), information_key(changed, "b"))
        self.assertIsInstance(checkpoint, ObservationCheckpoint)
        with self.assertRaises(ValueError):
            information_key(left, "invalid")

    def test_unknown_values_refuse_cache_key(self):
        world = commit(root())
        world.unreviewed = object()
        with self.assertRaises(UnsupportedKey):
            rule_state_key(world)
        unsupported = Game()
        unsupported.module = "BTX"
        with self.assertRaises(UnsupportedKey):
            rule_state_key(unsupported)
        with self.assertRaises(UnsupportedKey):
            information_key(unsupported)
        with self.assertRaises(UnsupportedKey):
            freeze(UserDict({"extension": 1}))


class DayGameKernelTests(unittest.TestCase):
    def test_transitions_detach_all_rule_and_observation_data(self):
        world = commit(root())
        kernel = FsTransitionKernel()
        for _ in range(32):
            if world.winner is not None or world.state.round != 2 or world.state.phase == "loop_end":
                break
            actions = world.legal_actions(world.controller)
            before = (rule_state_key(world), information_key(world))
            for action in actions:
                gold = world.transition(action).game
                actual = kernel.transition(world, action)
                assert_same_rule_state(self, actual, gold)
                self.assertLessEqual(len(actual.decisions), 1)
                self.assertEqual((rule_state_key(world), information_key(world)), before)
            world = world.transition(actions[0]).game
        self.assertGreater(kernel.compact_clones, 0)
        self.assertEqual(kernel.fallback_clones, 0)

    def test_invalid_actions_and_successors_never_mutate_source(self):
        world = commit(root())
        before = deepcopy(world.view("m"))
        kernel = FsTransitionKernel()
        with self.assertRaises(ValueError):
            kernel.transition(world, {"actor": "a", "action": "next"})
        child = kernel.transition(world, world.legal_actions(world.controller)[0])
        child.state.events[0]["message"] = "changed"
        child.history[0]["action"] = "changed"
        child.state.characters["girl"].paranoia += 1
        self.assertEqual(world.view("m"), before)
        self.assertNotEqual(world.history[0]["action"], "changed")

    def test_unknown_fields_and_rulesets_fall_back_to_full_transition(self):
        kernel = FsTransitionKernel()
        world = commit(root())
        world.unreviewed = object()
        command = world.legal_actions(world.controller)[0]
        actual = kernel.transition(world, command)
        gold = world.transition(command).game
        self.assertEqual(actual.state, gold.state)
        self.assertEqual(actual.decisions, gold.decisions)
        self.assertGreater(kernel.fallback_clones, 0)
        self.assertEqual(kernel.compact_clones, 0)

    def test_pair_commitment_matches_every_black_face_assignment(self):
        world = root()
        red = next(CompleteCardSpace(world).red_bundles())
        kernel = FsTransitionKernel()
        for black in CompleteCardSpace(world).black_bundles():
            gold = commit_pair(world, red, black)
            actual = commit_pair(world, red, black, kernel=kernel)
            self.assertEqual(rule_state_key(actual), rule_state_key(gold))
            self.assertEqual(actual.state, gold.state)
            self.assertEqual(actual.history, gold.history)
        self.assertEqual(kernel.fallback_clones, 0)


class DayGameCacheTests(unittest.TestCase):
    def test_complete_ability_values_match_independent_brute_force(self):
        solver = CachedDayContinuationSolver()
        for faces in (("v", "p-1", "h"), ("d", "p-1", "h"), ("v", "fg", "h"), ("d", "fg", "h")):
            world = commit(root(faces))
            actual = solver.solve(world)
            expected = brute_day(world, (2, 2))
            self.assertEqual(actual.bounds, ValueBounds(expected, expected))
            hit_before = solver.stats.hits
            again = solver.solve(world)
            self.assertEqual(again.bounds, actual.bounds)
            self.assertEqual(again.principal_action, actual.principal_action)
            self.assertEqual(again.nodes, 0)
            self.assertGreater(solver.stats.hits, hit_before)
        for refuses in (False, True):
            world = gold_tests.ExactDayTreeTests().goodwill_root(refuses)
            actual = solver.solve(world)
            self.assertEqual(actual.bounds.lower, brute_day(world, (1, 3)))
            self.assertTrue(actual.bounds.exact)

    def test_unknown_values_are_never_stored_and_cache_can_resume(self):
        world = commit(root())
        solver = CachedDayContinuationSolver()
        unknown = solver.solve(world, work=WorkLimit(node_limit=1))
        self.assertFalse(unknown.bounds.exact)
        self.assertFalse(solver.values)
        actual = solver.solve(world)
        self.assertEqual(actual.bounds, DayContinuationSolver().solve(world).bounds)
        self.assertTrue(actual.bounds.exact)

    def test_cached_action_is_detached_and_capacity_is_enforced(self):
        world = gold_tests.ExactDayTreeTests().goodwill_root(False)
        solver = CachedDayContinuationSolver(capacity=1)
        actual = solver.solve(world)
        actual.principal_action["action"] = "mutated"
        again = solver.solve(world)
        self.assertNotEqual(again.principal_action["action"], "mutated")
        self.assertEqual(len(solver.values), 1)
        self.assertGreater(solver.stats.evictions, 0)
        for value in (True, 0, -1, 1.5):
            with self.assertRaises(ValueError):
                CachedDayContinuationSolver(capacity=value)

    def test_observation_histories_stay_separate_when_rule_values_are_shared(self):
        world = commit(root())
        other = world.clone()
        other._event("public_test", "different observation")
        self.assertEqual(rule_state_key(world), rule_state_key(other))
        self.assertNotEqual(information_key(world), information_key(other))
        solver = CachedDayContinuationSolver()
        first = solver.solve(world)
        hits = solver.stats.hits
        second = solver.solve(other)
        self.assertEqual(first.bounds, second.bounds)
        self.assertGreater(solver.stats.hits, hits)
        self.assertNotEqual(information_key(world), information_key(other))

    def test_complete_pure_game_preserves_domains_and_values(self):
        world = gold_tests.PureDayTests().quiet_root()
        gold = PureDaySolver().solve(world)
        solver = PureDaySolver(backend="cached")
        actual = solver.solve(world)
        self.assertEqual(actual.bounds, gold.bounds)
        self.assertEqual(actual.red_bundle, gold.red_bundle)
        self.assertEqual(actual.red_actions, gold.red_actions)
        self.assertEqual(actual.black_actions, gold.black_actions)
        self.assertEqual(actual.evaluated_pairs, gold.evaluated_pairs)
        self.assertGreater(solver.continuation.stats.hits, 0)
        with self.assertRaises(ValueError):
            PureDaySolver(backend="other")


if __name__ == "__main__":
    unittest.main()
