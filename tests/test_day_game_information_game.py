"""Native abilities share red decisions while hidden types remain private."""

from copy import deepcopy
from fractions import Fraction as Q
import json
import unittest

from tragedy_sim import Game
from tragedy_sim.catalog import CHARACTERS
from tragedy_sim.day_game.continuation import DayContinuationSolver, WorkLimit
from tragedy_sim.day_game.engine_game import red_plan
from tragedy_sim.day_game.fair_engine import FixedPolicyDayContinuation, PublicSkipOptionalPolicy, bayesian_engine_game
from tragedy_sim.day_game.information_game import (authorized_information, build_ability_information_tree,
                                                  build_root_information_tree, solve_information_tree)
from tragedy_sim.day_game.matrix import MatrixLimit
from tragedy_sim.scenario_library import ScenarioLibrary
from tests.test_day_game_mixed_engine import matching_root


def rescue_root(*, key="girl"):
    """Controlled day-3 goodwill state; doctor can avert one suicide."""
    scenario = ScenarioLibrary().get("official-fs-01-first-script")
    scenario["cast"].update(doctor="ordinary", student="brain")
    other = "worker" if key == "girl" else "girl"
    scenario["cast"][key], scenario["cast"][other] = "key", "killer"
    scenario["incidents"] = [dict(day=2, kind="murder", culprit=other), dict(day=3, kind="suicide", culprit=key)]
    world = Game(scenario)
    world.state.phase, world.state.round = "goodwill", 3
    world._timing_window = None
    for cid in ("girl", "worker"):
        world.state.characters[cid].location = "hospital"
        world.state.characters[cid].paranoia = CHARACTERS[cid].limit
    world.state.characters["doctor"].goodwill = 2
    return world


def matching_selection(model):
    def plan(card):
        return red_plan((dict(actor="c", action="play", card=card, target="maiden"),
                         dict(actor="a", action="play", card="g1", target="hospital"),
                         dict(actor="b", action="play", card="g1", target="city")))
    rows = tuple(plan(card) for card in ("h", "v"))
    columns = tuple(next(c for c in model.blocks[0].game.columns() if c[0].card == card) for card in ("h", "v"))
    return rows, (columns,)


class InformationGameTests(unittest.TestCase):
    def test_native_goodwill_optimization_can_rescue_a_day_that_skip_baseline_loses(self):
        world = rescue_root()
        baseline = FixedPolicyDayContinuation(PublicSkipOptionalPolicy()).solve(world)
        self.assertEqual(baseline.bounds.lower, 0)
        self.assertEqual(DayContinuationSolver().solve(world).bounds.lower, 1)
        before = deepcopy(world.__dict__)
        tree = build_ability_information_tree((("known", 1, world),), belief_domain_complete=True)
        result = solve_information_tree(tree)
        self.assertEqual(result.bounds.lower, 1)
        self.assertTrue(result.certified_optimal)
        self.assertEqual(world.__dict__, before)
        self.assertTrue(any(json.loads(action)["action"] == "choose" and p
                            for _, choices in result.red_behavior for action, p in choices))

    def test_two_indistinguishable_suicide_types_have_half_not_clairvoyant_one(self):
        worlds = (("girl-key", Q(1, 2), rescue_root()), ("worker-key", Q(1, 2), rescue_root(key="worker")))
        for label, _, world in worlds:
            tree = build_ability_information_tree(((label, 1, world),), belief_domain_complete=True)
            self.assertEqual(solve_information_tree(tree).bounds.lower, 1)
        tree = build_ability_information_tree(worlds, belief_domain_complete=True)
        result = solve_information_tree(tree)
        self.assertEqual((result.bounds.lower, result.bounds.upper), (Q(1, 2), Q(1, 2)))
        self.assertTrue(result.certified_optimal)
        self.assertEqual(len(tree.lower.red.information_sets), 1)
        worlds = (("girl-key", Q(3, 4), worlds[0][2]), ("worker-key", Q(1, 4), worlds[1][2]))
        result = solve_information_tree(build_ability_information_tree(worlds, belief_domain_complete=True))
        self.assertEqual(result.bounds.lower, Q(3, 4))

    def test_red_information_ignores_private_roles_flags_and_hidden_command_count(self):
        left, right = rescue_root(), rescue_root(key="worker")
        right.loop_used.add("unit-private-use")
        right.history.extend([dict(actor="m", action="next")]*3)
        actions = left.legal_actions(left.controller)
        self.assertEqual(authorized_information(left, actions), authorized_information(right, actions))
        self.assertNotEqual(authorized_information(left, actions, "previous-answer-a"),
                            authorized_information(left, actions, "previous-answer-b"))
        right.protagonist_knowledge["roles"] = {"girl": "killer"}
        self.assertNotEqual(authorized_information(left, actions), authorized_information(right, actions))

    def test_native_query_or_its_refusal_allows_a_later_information_conditioned_rescue(self):
        worlds = (("girl-key", Q(1, 2), rescue_root()), ("worker-key", Q(1, 2), rescue_root(key="worker")))
        for _, _, world in worlds:
            world.state.characters["worker"].goodwill = 3
        # Worker can reveal their own role. Killer may refuse, Key cannot;
        # either the answer or that refusal distinguishes these two types.
        # The doctor must be used afterwards on the appropriate victim.
        tree = build_ability_information_tree(worlds, belief_domain_complete=True)
        result = solve_information_tree(tree)
        self.assertEqual((result.bounds.lower, result.bounds.upper), (1, 1))
        self.assertTrue(result.certified_optimal)
        self.assertGreater(len(tree.lower.red.information_sets), 1)

    def test_missing_mass_and_unexpanded_ability_tree_keep_rigorous_intervals(self):
        world = rescue_root()
        partial = build_ability_information_tree((("known", Q(2, 3), world),))
        solved = solve_information_tree(partial)
        self.assertEqual((solved.bounds.lower, solved.bounds.upper), (Q(2, 3), 1))
        self.assertFalse(solved.certified_optimal)
        for options in (dict(work=WorkLimit(node_limit=1)), dict(max_depth=1)):
            tree = build_ability_information_tree((("known", 1, world),), belief_domain_complete=True, **options)
            solved = solve_information_tree(tree)
            self.assertEqual((solved.bounds.lower, solved.bounds.upper), (0, 1))
            self.assertFalse(tree.continuation_complete)
            self.assertFalse(solved.certified_optimal)

    def test_root_mixed_cards_commit_before_red_random_draw_and_keep_restricted_scope(self):
        model = bayesian_engine_game((("h0", 1, matching_root()),), belief_domain_complete=True)
        rows, columns = matching_selection(model)
        tree = build_root_information_tree(model, rows, columns)
        solved = solve_information_tree(tree)
        self.assertTrue(tree.continuation_complete)
        self.assertEqual((solved.bounds.lower, solved.bounds.upper), (Q(1, 2), Q(1, 2)))
        self.assertEqual(dict(solved.red_cards), {r: Q(1, 2) for r in rows})
        self.assertFalse(tree.root_domain_complete)
        self.assertFalse(solved.certified_optimal)
        reordered = build_root_information_tree(model, reversed(rows), (tuple(reversed(columns[0])),))
        self.assertEqual(solve_information_tree(reordered).bounds, solved.bounds)
        # Forced phase steps are retained in recall but need no LP choices.
        self.assertLess(len(tree.lower.red.sequences), tree.engine_nodes)

    def test_root_unknown_world_mass_is_not_renormalized(self):
        model = bayesian_engine_game((("h0", Q(2, 3), matching_root()),))
        rows, columns = matching_selection(model)
        result = solve_information_tree(build_root_information_tree(model, rows, columns))
        self.assertEqual((result.bounds.lower, result.bounds.upper), (Q(1, 3), Q(2, 3)))

    def test_truncated_root_keeps_every_selected_plan_and_has_no_global_certificate(self):
        model = bayesian_engine_game((("h0", 1, matching_root()),), belief_domain_complete=True)
        rows, columns = matching_selection(model)
        tree = build_root_information_tree(model, rows, columns, work=WorkLimit(node_limit=1))
        result = solve_information_tree(tree)
        self.assertEqual((result.bounds.lower, result.bounds.upper), (0, 1))
        self.assertEqual(sum(p for _, p in result.red_cards), 1)
        self.assertEqual(len(tree.lower.red.information_sets[0].actions), 2)
        self.assertFalse(result.certified_optimal)

    def test_incompatible_information_illegal_domains_and_too_large_trees_are_rejected(self):
        world = rescue_root()
        altered = world.clone()
        altered._event("unit", "observed extra event")
        with self.assertRaises(ValueError):
            build_ability_information_tree((("a", Q(1, 2), world), ("b", Q(1, 2), altered)))
        for roots in ((), (("h", Q(2), world),), (("h", 0, world),)):
            with self.assertRaises(ValueError):
                build_ability_information_tree(roots)
        model = bayesian_engine_game((("h0", 1, matching_root()),))
        rows, columns = matching_selection(model)
        for bad_rows, bad_columns in (((), columns), ((rows[0], rows[0]), columns), (rows, ((),))):
            with self.assertRaises(ValueError):
                build_root_information_tree(model, bad_rows, bad_columns)
        with self.assertRaises(MatrixLimit):
            build_root_information_tree(model, rows, columns, tree_node_limit=1)


if __name__ == "__main__":
    unittest.main()
