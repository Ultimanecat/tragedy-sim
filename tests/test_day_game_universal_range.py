"""Universal day utility, native path enumeration, and fair tree compression."""

from copy import deepcopy
from fractions import Fraction as Q
import random
import unittest

from tragedy_sim import Game
from tragedy_sim.catalog import CHARACTERS
from tragedy_sim.day_game.continuation import DayContinuationSolver, WorkLimit, day_boundary_value
from tragedy_sim.day_game.fair_engine import bayesian_engine_game
from tragedy_sim.day_game.frozen_information import FrozenBehavior
from tragedy_sim.day_game.information_game import _Builder, build_ability_information_tree, build_root_information_tree, solve_information_tree
from tragedy_sim.day_game.keys import rule_state_key
from tragedy_sim.day_game.universal_range import UniversalDayRange
from tests.test_day_game_information_game import rescue_root, matching_selection
from tests.test_day_game_mixed_engine import matching_root


def all_native_outcomes(world, position):
    """Independent full tree: both players' choices are possible outcomes."""
    boundary = day_boundary_value(world, position)
    if boundary is not None:
        return {int(boundary)}
    result = set()
    for action in world.legal_actions(world.controller):
        result.update(all_native_outcomes(world.transition(action).game, position))
    return result


def constant_root(value):
    world = rescue_root()
    world.state.characters["doctor"].goodwill = 0
    if value:
        world.state.characters["girl"].paranoia = 0
    return world


class UniversalRangeTests(unittest.TestCase):
    def test_ten_seeds_match_independent_all_native_outcomes_on_both_backends(self):
        for seed in range(10):
            rng = random.Random(seed)
            world = rescue_root(key=rng.choice(("girl", "worker")))
            world.state.characters["doctor"].goodwill = rng.choice((0, 2))
            world.state.characters["worker"].goodwill = rng.choice((0, 3))
            for cid in ("girl", "worker"):
                world.state.characters[cid].paranoia = rng.choice((0, CHARACTERS[cid].limit))
                world.state.characters[cid].intrigue = rng.choice((0, 2))
            expected = all_native_outcomes(world, (1, 3))
            before = deepcopy(world.__dict__)
            for backend in ("reference", "cached"):
                result = UniversalDayRange(backend=backend).probe(world, node_limit=100000)
                self.assertTrue(result.exact, (seed, backend))
                self.assertEqual((result.minimum, result.maximum), (min(expected), max(expected)), (seed, backend))
            self.assertEqual(world.__dict__, before)

    def test_known_world_best_play_one_is_not_a_universal_constant(self):
        world = rescue_root()
        self.assertEqual(DayContinuationSolver().solve(world).bounds.lower, 1)
        result = UniversalDayRange().probe(world, node_limit=100000)
        self.assertTrue(result.exact)
        self.assertEqual((result.minimum, result.maximum), (0, 1))
        self.assertIsNone(result.constant)

    def test_unknown_cutoff_is_not_cached_as_an_exact_mixed_range(self):
        world, analyzer = rescue_root(), UniversalDayRange()
        key = (analyzer.version, (1, 3), rule_state_key(world))
        cut = analyzer.probe(world, work=WorkLimit(node_limit=1))
        self.assertFalse(cut.exact)
        self.assertNotIn(key, analyzer.values)
        full = analyzer.probe(world, node_limit=100000)
        self.assertTrue(full.exact)
        self.assertIsNone(full.constant)
        work = WorkLimit(node_limit=None)
        reused = analyzer.probe(world, work=work, node_limit=0)
        self.assertEqual(reused, full)
        self.assertEqual(work.nodes, 0)
        self.assertGreater(analyzer.stats.hits, 0)

    def test_probe_cap_is_local_and_does_not_consume_all_future_action_work(self):
        world, work = rescue_root(), WorkLimit(node_limit=None)
        result = UniversalDayRange().probe(world, work=work, node_limit=1)
        self.assertFalse(result.exact)
        self.assertEqual(work.nodes, 1)
        self.assertFalse(work.exhausted())
        tree = build_ability_information_tree((("h0", 1, world),), range_probe_nodes=1)
        self.assertTrue(tree.continuation_complete)
        self.assertEqual(solve_information_tree(tree).bounds.lower, 1)
        self.assertGreater(tree.range_stats["cutoffs"], 0)

    def test_cache_reuses_histories_but_keeps_physical_resources_and_private_fields(self):
        world, analyzer = constant_root(1), UniversalDayRange()
        self.assertEqual(analyzer.probe(world, node_limit=100000).constant, 1)
        same = world.clone()
        same.history.append(dict(actor="m", action="next"))
        same._event("unit", "different observed text")
        self.assertEqual(analyzer.probe(same, node_limit=0).constant, 1)
        same.state.hands["a"].remove("fm")
        same.state.discarded["a"].append("fm")
        self.assertFalse(analyzer.probe(same, node_limit=0).exact)
        failed = constant_root(0)
        self.assertEqual(analyzer.probe(failed, node_limit=100000).constant, 0)
        self.assertEqual(analyzer.probe(world, node_limit=0).constant, 1)

    def test_capacity_and_unknown_key_fail_closed(self):
        analyzer = UniversalDayRange(capacity=1)
        for value in (1, 0):
            self.assertEqual(analyzer.probe(constant_root(value), node_limit=100000).constant, value)
        self.assertEqual(len(analyzer.values), 1)
        self.assertGreater(analyzer.stats.evictions, 0)
        world = constant_root(1)
        world.unaudited = object()
        self.assertFalse(analyzer.probe(world).exact)
        self.assertGreater(analyzer.stats.unsupported, 0)
        with self.assertRaises(ValueError):
            analyzer.probe(rescue_root(), position=(2, 1))


class ConstantCompressionTests(unittest.TestCase):
    def test_frozen_skip_path_is_not_cached_as_a_universal_failure(self):
        world, analyzer = rescue_root(), UniversalDayRange()
        builder = _Builder(work=WorkLimit(node_limit=100000), max_depth=128, tree_node_limit=10000,
                           fixed_behavior=FrozenBehavior("red"), range_analyzer=analyzer)
        pair = builder.visit(world, (1, 3))
        self.assertEqual(pair.constant, 0)
        self.assertFalse(pair.universal)
        key = (analyzer.version, (1, 3), rule_state_key(world))
        self.assertNotIn(key, analyzer.values)
        result = analyzer.probe(world, node_limit=100000)
        self.assertTrue(result.exact)
        self.assertIsNone(result.constant)

    def test_fully_covered_forced_response_steps_can_populate_universal_cache_without_probes(self):
        world, analyzer = constant_root(1), UniversalDayRange()
        builder = _Builder(work=WorkLimit(node_limit=100000), max_depth=128, tree_node_limit=10000,
                           fixed_behavior=FrozenBehavior("red"), range_analyzer=analyzer)
        pair = builder.visit(world, (1, 3))
        self.assertTrue(pair.universal)
        self.assertEqual(pair.constant, 1)
        self.assertEqual(analyzer.stats.nodes, 0)
        self.assertGreater(analyzer.stats.bottom_up_stores, 0)
        self.assertEqual(analyzer.probe(world, node_limit=0).constant, 1)

    def test_controlled_root_compression_keeps_exact_mixed_value_and_shrinks_native_tree(self):
        model = bayesian_engine_game((("h0", 1, matching_root()),), belief_domain_complete=True)
        rows, columns = matching_selection(model)
        raw = build_root_information_tree(model, rows, columns, range_compression=False)
        compressed = build_root_information_tree(model, rows, columns)
        self.assertEqual(solve_information_tree(raw).bounds, solve_information_tree(compressed).bounds)
        self.assertGreater(compressed.range_stats["folded_subtrees"], 0)
        self.assertEqual(compressed.compression, UniversalDayRange.version)

    def test_shared_information_with_private_constant_failure_does_not_reveal_the_world(self):
        ordinary = rescue_root()
        scenario = deepcopy(ordinary.scenario)
        scenario["cast"].update(doctor="brain", student="ordinary")
        used = Game(scenario)
        used.state = deepcopy(ordinary.state)
        used._timing_window = None
        used.day_used.add("goodwill:doctor:adjust")
        self.assertEqual(UniversalDayRange().probe(used, node_limit=100000).constant, 0)
        worlds = (("used", Q(1, 2), used), ("unused", Q(1, 2), ordinary))
        raw = build_ability_information_tree(worlds, belief_domain_complete=True, range_compression=False)
        compressed = build_ability_information_tree(worlds, belief_domain_complete=True)
        first, second = solve_information_tree(raw), solve_information_tree(compressed)
        self.assertEqual(first.bounds, second.bounds)
        self.assertEqual(second.bounds.lower, Q(1, 2))
        self.assertTrue(second.certified_optimal)
        self.assertGreater(compressed.range_stats["folded_subtrees"], 0)
        self.assertEqual(second.policy_extension, "next-first-v1")

    def test_query_and_refusal_branch_values_remain_one_after_compression(self):
        worlds = (("girl", Q(1, 2), rescue_root()), ("worker", Q(1, 2), rescue_root(key="worker")))
        for _, _, world in worlds:
            world.state.characters["worker"].goodwill = 3
        raw = build_ability_information_tree(worlds, belief_domain_complete=True, range_compression=False)
        compressed = build_ability_information_tree(worlds, belief_domain_complete=True)
        self.assertEqual(solve_information_tree(raw).bounds, solve_information_tree(compressed).bounds)
        self.assertEqual(solve_information_tree(compressed).bounds.lower, 1)
        self.assertLess(compressed.lower.nodes, raw.lower.nodes)


if __name__ == "__main__":
    unittest.main()
