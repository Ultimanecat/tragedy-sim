"""Authorized continuation inputs and true-engine finite-world payoff checks."""

from fractions import Fraction as Q
import unittest

from tests.test_day_game import root
from tests.test_day_game_mixed_engine import matching_root
from tragedy_sim.day_game.bayesian import BayesianDoubleOracle
from tragedy_sim.day_game.continuation import day_boundary_value
from tragedy_sim.day_game.engine_game import red_commands
from tragedy_sim.day_game.fair_engine import (FixedPolicyDayContinuation, FixedPolicyDayGame,
                                            PublicSkipOptionalPolicy, bayesian_engine_game, public_policy_input)
from tragedy_sim.day_game.pure import commit_pair
from tragedy_sim.day_game.zero_sum import SearchBudget
from tragedy_sim.domain import InformationState, ScriptDefinition


def alternate(world):
    other = world.clone()
    other.roles["girl"], other.roles["maiden"] = other.roles["maiden"], other.roles["girl"]
    other.scenario["cast"]["girl"], other.scenario["cast"]["maiden"] = other.scenario["cast"]["maiden"], other.scenario["cast"]["girl"]
    other.script = ScriptDefinition.from_mapping(other.scenario)
    return other


def brute_fixed_day(world, position, policy):
    value = day_boundary_value(world, position)
    if value is not None:
        return Q(str(value))
    actions = world.legal_actions(world.controller)
    if world.controller != "m":
        actions = [policy.choose(public_policy_input(world, actions))]
    return min(brute_fixed_day(world.transition(action).game, position, policy) for action in actions)


class FairEngineTests(unittest.TestCase):
    def test_private_roles_flags_faces_and_hidden_command_counts_do_not_enter_policy_input(self):
        first = root(("d", "fg", "h"))
        second = root(("v", "p-1", "h"))
        second = alternate(second)
        second.day_used.add("doctor")
        second.history.extend((dict(actor="m", action="pass"), dict(actor="m", action="pass")))
        self.assertEqual(public_policy_input(first).key, public_policy_input(second).key)
        observation = public_policy_input(second).to_dict()
        self.assertNotIn("secret", observation["state"])
        self.assertFalse(any(c["actor"] == "m" for c in observation["own_commands"]))

    def test_own_decisions_and_visible_event_history_remain_in_information(self):
        world = root()
        original = public_policy_input(world).key
        world.history.append(dict(actor="a", action="pass"))
        self.assertNotEqual(public_policy_input(world).key, original)
        world.history.pop()
        world._event("public_test", "an observed event")
        self.assertNotEqual(public_policy_input(world).key, original)

    def test_root_worlds_require_same_authorized_information_and_keep_original_mass(self):
        first = matching_root()
        worlds = bayesian_engine_game((("first", Q(2, 5), first), ("other", Q(1, 2), alternate(first))))
        self.assertEqual(worlds.covered_mass, Q(9, 10))
        self.assertEqual(worlds.missing_mass, Q(1, 10))
        self.assertEqual(worlds.row_count, 240)
        changed = alternate(first)
        changed.state.characters["girl"].paranoia += 1
        with self.assertRaises(ValueError):
            bayesian_engine_game((("first", Q(1, 2), first), ("other", Q(1, 2), changed)))

    def test_reference_cached_compiled_and_independent_fixed_tree_agree(self):
        world, policy = matching_root(), PublicSkipOptionalPolicy()
        reference = FixedPolicyDayGame(world, policy=policy, backend="reference")
        rows, columns = tuple(reference.rows())[:3], tuple(reference.columns())
        expected = {}
        for i, row in enumerate(rows):
            for j, column in enumerate(columns):
                after = commit_pair(world, red_commands(row), column)
                expected[i, j] = brute_fixed_day(after, (world.state.loop, world.state.round), policy)
                value = reference.evaluate(row, column, SearchBudget())
                self.assertTrue(value.exact)
                self.assertEqual(value.lower, expected[i, j])
        for backend in ("cached", "compiled"):
            model = FixedPolicyDayGame(world, backend=backend)
            for (i, j), value in expected.items():
                self.assertEqual(model.evaluate(rows[i], columns[j], SearchBudget()).lower, value)
        self.assertFalse(reference.continuation.values)

    def test_policy_receives_only_detached_information_and_invalid_choice_is_rejected(self):
        class Spy:
            version = "test-observable-spy-v1"
            calls = 0

            def choose(self, observation):
                self.calls += 1
                assert isinstance(observation, InformationState)
                assert not hasattr(observation, "roles")
                assert "secret" not in observation.projection["state"]
                return PublicSkipOptionalPolicy().choose(observation)

        spy = Spy()
        model = FixedPolicyDayGame(matching_root(), policy=spy)
        row, column = next(model.rows()), next(model.columns())
        model.evaluate(row, column, SearchBudget())
        self.assertGreater(spy.calls, 0)

        class Bad(Spy):
            def choose(self, observation):
                return dict(actor="m", action="play", card="i2", target="girl")

        model = FixedPolicyDayGame(matching_root(), policy=Bad())
        with self.assertRaises(ValueError):
            model.evaluate(row, column, SearchBudget())
        frozen = FixedPolicyDayContinuation(spy)
        spy.version = "changed-policy-v2"
        with self.assertRaises(ValueError):
            frozen._check_policy()

    def test_observation_conditioned_value_cache_keeps_distinct_public_histories(self):
        model = FixedPolicyDayGame(matching_root())
        after = commit_pair(model._root, red_commands(next(model.rows())), next(model.columns()))
        other = after.clone()
        other._event("public_test", "a different public history")
        position = (after.state.loop, after.state.round)
        self.assertNotEqual(model.continuation._cache_key(after, position), model.continuation._cache_key(other, position))
        with self.assertRaises(ValueError):
            FixedPolicyDayContinuation(object())

    def test_finite_world_oracle_is_executable_and_does_not_claim_full_posterior_coverage(self):
        first = matching_root()
        worlds = bayesian_engine_game((("h0", Q(1, 2), first), ("h1", Q(1, 2), alternate(first))))
        result = BayesianDoubleOracle(worlds).solve(budget=SearchBudget(payoff_limit=50))
        self.assertFalse(result.certified_optimal)
        self.assertFalse(result.belief_domain_complete)
        self.assertIn("fixed-observable", result.model_scope)
        self.assertTrue(all(worlds.contains_row(plan) for plan, _ in result.red))
        self.assertEqual(sum(p for _, p in result.red), 1)
        self.assertLessEqual(result.lower_bound, result.upper_bound)


if __name__ == "__main__":
    unittest.main()
