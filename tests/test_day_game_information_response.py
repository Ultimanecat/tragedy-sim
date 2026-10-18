"""Frozen legal extensions, complete root separation, and global witnesses."""

from dataclasses import replace
from fractions import Fraction as Q
import unittest
from unittest.mock import patch

from tests.test_day_game import brute_day
from tests.test_day_game_information_game import matching_selection
from tests.test_day_game_mixed_engine import matching_root
from tragedy_sim.day_game.continuation import WorkLimit
from tragedy_sim.day_game.engine_game import red_commands
from tragedy_sim.day_game.fair_engine import bayesian_engine_game
from tragedy_sim.day_game.frozen_information import FrozenBehavior, freeze_information_solution
from tragedy_sim.day_game.information_game import _key, column_identity, build_root_information_tree, solve_information_tree
from tragedy_sim.day_game.information_oracle import InformationDoubleOracle
from tragedy_sim.day_game.information_response import (BlackSkipCache, InformationResponse, black_candidate_value, black_information_response,
                                                      red_information_response, red_candidate_value)
from tragedy_sim.day_game.pure import commit_pair


def frozen_matching(mass=Q(1)):
    model = bayesian_engine_game((("h0", mass, matching_root()),), belief_domain_complete=mass == 1)
    rows, columns = matching_selection(model)
    tree = build_root_information_tree(model, rows, columns)
    result = solve_information_tree(tree)
    return model, rows, columns, tree, freeze_information_solution(tree, result)


class FrozenInformationTests(unittest.TestCase):
    def test_policy_copies_normalizes_and_versions_its_content_and_has_legal_fallback(self):
        first, second = dict(actor="a", action="choose", index=1), dict(actor="a", action="next")
        table = [("seen", [(_key(first), Q(1))])]
        policy = FrozenBehavior("red", table)
        table.clear()
        self.assertEqual(policy.choices("seen", (first, second)), ((first, Q(1)),))
        self.assertEqual(policy.choices("unknown", (first, second)), ((second, Q(1)),))
        self.assertEqual(policy.version, FrozenBehavior("red", (("seen", ((_key(first), 1),)),)).version)
        self.assertNotEqual(policy.version, FrozenBehavior("red").version)
        with self.assertRaises(ValueError):
            policy.choices("seen", (second,))
        for choices in (("red", (("i", ((_key(first), 2),)),)), ("red", (("i", ((_key(first), -1),)),))):
            with self.assertRaises(ValueError):
                FrozenBehavior(*choices)

    def test_physical_column_identity_and_strategy_remain_meaningful_after_reordering(self):
        model, rows, columns, tree, strategy = frozen_matching()
        reverse = build_root_information_tree(model, tuple(reversed(rows)), (tuple(reversed(columns[0])),))
        self.assertEqual(set(tree.root_columns[0][1]), set(reverse.root_columns[0][1]))
        self.assertEqual({key for key, _ in tree.root_columns[0][1]}, {column_identity(c) for c in columns[0]})
        self.assertEqual(sum(p for _, p in strategy.red_cards), 1)
        self.assertEqual(sum(p for _, p in strategy.black_cards[0][1]), 1)

    def test_full_responses_distinguish_complete_extreme_and_exhausted_domains(self):
        model, rows, columns, _, strategy = frozen_matching()
        version = strategy.version
        black = black_information_response(model.blocks[0], strategy, WorkLimit(node_limit=100000))
        self.assertEqual((black.bounds.lower, black.bounds.upper), (Q(1, 2), Q(1, 2)))
        self.assertTrue(black.domain_exhausted)
        self.assertEqual(black.checked, 6)
        red = red_information_response(model, strategy, WorkLimit(node_limit=100000))
        self.assertEqual((red.bounds.lower, red.bounds.upper), (1, 1))
        self.assertTrue(red.complete)
        self.assertFalse(red.domain_exhausted)
        self.assertNotIn(red.action, rows)
        self.assertEqual(strategy.version, version)

    def test_limits_and_missing_mass_never_renormalize_or_claim_a_complete_response(self):
        model, rows, _, _, strategy = frozen_matching(Q(2, 3))
        candidate = red_candidate_value(model, rows[0], strategy, WorkLimit(node_limit=100000))
        self.assertEqual((candidate.bounds.lower, candidate.bounds.upper), (Q(1, 3), Q(2, 3)))
        short = red_information_response(model, strategy, WorkLimit(node_limit=1), candidate_limit=1)
        self.assertEqual((short.bounds.lower, short.bounds.upper), (0, 1))
        self.assertFalse(short.complete)
        limited = black_information_response(model.blocks[0], strategy, WorkLimit(node_limit=100000), candidate_limit=1)
        self.assertFalse(limited.complete)
        self.assertFalse(limited.domain_exhausted)
        self.assertEqual(limited.bounds.lower, 0)
        with self.assertRaises(ValueError):
            red_information_response(model, strategy, WorkLimit(), candidate_limit=0)

    def test_empty_policy_cache_matches_full_information_tree_and_rejects_learned_scope(self):
        model, _, columns, _, strategy = frozen_matching()
        block, cache = model.blocks[0], BlackSkipCache()
        for col in block.game.columns():
            original = black_candidate_value(block, col, strategy, WorkLimit()).bounds
            cached = black_candidate_value(block, col, strategy, WorkLimit(), skip_cache=cache).bounds
            self.assertEqual(original, cached)
        first = cache.stats()["hits"]
        black_candidate_value(block, columns[0][0], strategy, WorkLimit(), skip_cache=cache)
        self.assertGreater(cache.stats()["hits"], first)
        learned = replace(strategy, red_policy=FrozenBehavior("red", (("unseen", ((_key(dict(actor="a", action="next")), 1),)),)))
        evaluations = cache.stats()["evaluations"]
        black_candidate_value(block, columns[0][0], learned, WorkLimit(), skip_cache=cache)
        self.assertEqual(cache.stats()["evaluations"], evaluations)


class InformationOracleTests(unittest.TestCase):
    def test_verified_proposal_is_retained_when_budget_ends_after_response(self):
        model, rows, columns, _, strategy = frozen_matching()
        verified = red_information_response(model, strategy, WorkLimit(node_limit=100000))
        self.assertNotIn(verified.action, rows)
        oracle = InformationDoubleOracle(model, seed_rows=rows, seed_columns=columns)

        def stop_after_verified_reply(model, strategy, work, **options):
            work.node_limit = work.nodes
            work.reasons.add("node_limit")
            return verified

        with patch("tragedy_sim.day_game.information_oracle.red_information_response", side_effect=stop_after_verified_reply):
            result = oracle.solve(work=WorkLimit(node_limit=None))
        self.assertEqual(result.stop_reason, "node_limit")
        self.assertIn(verified.action, oracle.rows)
        self.assertTrue(result.iterations[-1].added_row)

    def test_closed_bound_trace_does_not_claim_an_unnecessary_proposal_was_added(self):
        model, rows, _, _, _ = frozen_matching()
        noop = tuple(type(rows[0][0])(actor, card, target) for actor, card, target in
                     (("c", "h", "hospital"), ("a", "g1", "girl"), ("b", "g1", "maiden")))
        alternative = (rows[0][0], type(rows[0][1])("a", "g1", "city"), type(rows[0][2])("b", "g1", "hospital"))
        columns = tuple(next(c for c in model.blocks[0].game.columns() if c[0].card == card) for card in ("h", "v", "fp"))
        oracle = InformationDoubleOracle(model, seed_rows=(*rows, noop), seed_columns=(columns,))

        def equally_optimal_reply(model, strategy, work, **options):
            candidate = red_candidate_value(model, alternative, strategy, work)
            self.assertEqual(candidate.bounds.lower, Q(2, 3))
            self.assertTrue(candidate.bounds.exact)
            return InformationResponse(alternative, candidate.bounds, candidate.bounds, candidate.behavior,
                                       model.row_count, model.row_count, True, True, "complete_domain")

        with patch("tragedy_sim.day_game.information_oracle.red_information_response", side_effect=equally_optimal_reply):
            result = oracle.solve(work=WorkLimit(node_limit=100000))
        self.assertTrue(result.certified_optimal)
        self.assertFalse(result.iterations[-1].added_row)
        self.assertNotIn(alternative, oracle.rows)

    def test_verified_black_proposal_also_survives_a_budget_stop(self):
        model, rows, columns, _, _ = frozen_matching()
        noop = tuple(type(rows[0][0])(actor, card, target) for actor, card, target in
                     (("c", "h", "hospital"), ("a", "g1", "girl"), ("b", "g1", "maiden")))
        oracle = InformationDoubleOracle(model, seed_rows=(*rows, noop), seed_columns=columns)

        def stop_after_black_reply(block, strategy, work, **options):
            response = black_information_response(block, strategy, work, **options)
            self.assertNotIn(response.action, columns[0])
            work.node_limit = work.nodes
            work.reasons.add("node_limit")
            return response

        with patch("tragedy_sim.day_game.information_oracle.black_information_response", side_effect=stop_after_black_reply):
            result = oracle.solve(work=WorkLimit(node_limit=None))
        self.assertTrue(result.iterations[-1].added_columns[0])
        self.assertEqual(len(oracle.columns[0]), 3)

    def test_utility_cap_avoids_red_scan_and_keeps_unrepresented_mass(self):
        for mass in (Q(1), Q(2, 3)):
            world = matching_root()
            world.state.characters["girl"].alive = False
            model = bayesian_engine_game((("h0", mass, world),), belief_domain_complete=mass == 1)
            rows, columns = matching_selection(model)
            result = InformationDoubleOracle(model, seed_rows=rows, seed_columns=columns).solve(work=WorkLimit(node_limit=10000))
            self.assertEqual((result.bounds.lower, result.bounds.upper), (mass, 1))
            self.assertEqual(result.iterations[0].red_response.checked, 0)
            self.assertEqual(result.iterations[0].red_response.stop_reason, "utility_range_bound")
            self.assertEqual(result.certified_optimal, mass == 1)
            self.assertEqual(result.stop_reason, "proven_optimal" if mass == 1 else "unrepresented_mass")

    def test_global_two_thirds_matches_independent_native_full_game_and_resumes_after_budget(self):
        model, rows, columns, _, _ = frozen_matching()
        oracle = InformationDoubleOracle(model, seed_rows=rows, seed_columns=columns)
        partial = oracle.solve(work=WorkLimit(node_limit=1))
        self.assertFalse(partial.certified_optimal)
        self.assertEqual((partial.bounds.lower, partial.bounds.upper), (0, 1))
        solved = oracle.solve(work=WorkLimit(node_limit=100000))
        self.assertEqual((solved.bounds.lower, solved.bounds.upper), (Q(2, 3), Q(2, 3)))
        self.assertTrue(solved.certified_optimal)
        self.assertTrue(solved.best_response_complete)
        self.assertEqual(solved.restricted_rows, 3)
        self.assertEqual(solved.restricted_columns, (3,))
        self.assertEqual(solved.iterations[-1].red_response.checked, model.row_count)
        # No nontrivial red ability is available in this control state. The
        # independent native day tree therefore audits the frozen strategy
        # directly, without using sequence-flow payoffs or policy lookups.
        world = model.blocks[0].game._root
        native = min(sum(p*Q(brute_day(commit_pair(world, red_commands(row), col), (1, 1)))
                         for row, p in solved.red) for col in model.blocks[0].game.columns())
        self.assertEqual(native, Q(2, 3))
        resumed = oracle.solve(work=WorkLimit(node_limit=1))
        self.assertEqual(resumed.bounds, solved.bounds)
        self.assertTrue(resumed.best_response_complete)

    def test_sampled_type_model_cannot_receive_a_full_posterior_certificate(self):
        model, rows, columns, _, _ = frozen_matching()
        model.belief_domain_complete = False
        oracle = InformationDoubleOracle(model, seed_rows=rows, seed_columns=columns)
        # Closed [0,1] at epsilon=1 is still only a finite-model statement.
        result = oracle.solve(epsilon=1, work=WorkLimit(node_limit=1))
        self.assertFalse(result.certified_epsilon)
        self.assertEqual(result.stop_reason, "finite_model_only")


if __name__ == "__main__":
    unittest.main()
