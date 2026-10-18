"""Authorized continuation inputs and true-engine finite-world payoff checks."""

from fractions import Fraction as Q
import json
import random
import unittest
from unittest.mock import patch

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
    def test_skip_policy_uses_native_next_instead_of_activating_optional_goodwill(self):
        world = root(actual_cast=True)
        world.state.phase = "goodwill"
        world.state.leader = "a"
        world.state.characters["doctor"].goodwill = 2
        world._timing_window = None
        actions = world.legal_actions("a")
        self.assertTrue(any(a["action"] == "choose" for a in actions))
        expected = dict(actor="a", action="next")
        self.assertIn(expected, actions)
        for backend in ("reference", "cached", "compiled"):
            solver = FixedPolicyDayContinuation(PublicSkipOptionalPolicy(), backend=backend)
            self.assertEqual(solver._actions(world, "a"), [expected])
        self.assertEqual(PublicSkipOptionalPolicy().version, "public-skip-optional-v2")

    def test_skip_policy_preserves_forced_choices_without_a_next_offer(self):
        commands = [dict(actor="a", action="choose", index=i) for i in (1, 2)]
        policy = PublicSkipOptionalPolicy()
        self.assertEqual(policy.choose(InformationState.create("team", dict(offers=commands))), commands[0])
        for action in ("pass", "next"):
            offers = [*commands, dict(actor="a", action=action)]
            self.assertEqual(policy.choose(InformationState.create("team", dict(offers=offers))), offers[-1])

    def test_concrete_skip_policy_depends_only_on_identical_legal_menus(self):
        policy = PublicSkipOptionalPolicy()
        for seed in range(10):
            rng = random.Random(seed)
            for index in range(40):
                offers = [dict(actor="a", action="choose", option=i) for i in range(1, rng.randrange(2, 6))]
                if index % 2:
                    offers.append(dict(actor="a", action="pass"))
                rng.shuffle(offers)
                offers.sort(key=lambda a: json.dumps(a, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
                full = InformationState.create("team", dict(offers=offers,
                    state=dict(events=[dict(kind=f"event-{seed}-{index}")], loop=rng.randrange(1, 5)),
                    own_commands=[dict(actor="a", action="play", card=f"card-{index}")]))
                menu = InformationState.create("team", dict(offers=offers))
                self.assertNotEqual(full.key, menu.key)
                self.assertEqual(policy.choose(full), policy.choose(menu))

    def test_audited_menu_context_matches_generic_policy_on_every_controlled_cell(self):
        class GenericSkip:
            version = PublicSkipOptionalPolicy().version

            def choose(self, observation):
                return PublicSkipOptionalPolicy().choose(observation)

        world = matching_root()
        golden = FixedPolicyDayGame(world, policy=GenericSkip(), backend="reference")
        plans, columns = tuple(golden.rows())[:3], tuple(golden.columns())
        values = {(i, j): golden.evaluate(row, column, SearchBudget()).lower
                  for i, row in enumerate(plans) for j, column in enumerate(columns)}
        for backend in ("reference", "cached", "compiled"):
            optimized = FixedPolicyDayGame(world, backend=backend)
            for (i, j), value in values.items():
                evaluated = optimized.evaluate(plans[i], columns[j], SearchBudget())
                self.assertTrue(evaluated.exact)
                self.assertEqual(evaluated.lower, value)
            self.assertEqual(optimized.continuation.context_stats.full_inputs, 0)
            self.assertGreater(optimized.continuation.context_stats.menu_inputs, 0)
        self.assertGreater(golden.continuation.context_stats.full_inputs, 0)
        self.assertEqual(golden.continuation.context_mode, "authorized-history-v1")

    def test_menu_policy_never_builds_full_node_observation_and_history_cache_can_hit(self):
        model = FixedPolicyDayGame(matching_root())
        row, column = next(model.rows()), next(model.columns())
        with patch("tragedy_sim.day_game.fair_engine.public_policy_input", side_effect=AssertionError("full node context")):
            result = model.evaluate(row, column, SearchBudget())
        self.assertTrue(result.exact)
        after = commit_pair(model._root, red_commands(row), column)
        other = after.clone()
        other._event("public_test", "new observed text")
        hits = model.continuation.stats.hits
        reused = model.continuation.solve(other)
        self.assertEqual(reused.bounds.lower, result.lower)
        self.assertEqual(reused.nodes, 0)
        self.assertGreater(model.continuation.stats.hits, hits)

    def test_policy_and_continuation_subclasses_do_not_inherit_audited_scope(self):
        class DerivedPolicy(PublicSkipOptionalPolicy):
            pass

        class DerivedContinuation(FixedPolicyDayContinuation):
            pass

        for continuation in (FixedPolicyDayContinuation(DerivedPolicy()),
                             DerivedContinuation(PublicSkipOptionalPolicy())):
            self.assertEqual(continuation.context_mode, "authorized-history-v1")

    def test_menu_specialization_preserves_both_safe_and_joint_killer_attack_values(self):
        from tests.test_day_game import root as pressure_root

        class GenericSkip:
            version = PublicSkipOptionalPolicy().version

            def choose(self, information):
                return PublicSkipOptionalPolicy().choose(information)

        world = pressure_root(actual_cast=True)
        reference = FixedPolicyDayGame(world, policy=GenericSkip(), backend="reference")
        row = reference.plan((dict(actor="c", action="play", card="fm", target="girl"),
                              dict(actor="a", action="play", card="fi", target="worker"),
                              dict(actor="b", action="play", card="v", target="maiden")))
        faces = (("d", "fg", "h"), ("i1", "d", "fg"))
        columns = tuple(next(c for c in reference.columns() if tuple(p.card for p in c) == cards) for cards in faces)
        values = tuple(reference.evaluate(row, c, SearchBudget()).lower for c in columns)
        self.assertEqual(values, (1, 0))
        for backend in ("cached", "compiled"):
            optimized = FixedPolicyDayGame(world, backend=backend)
            self.assertEqual(tuple(optimized.evaluate(row, c, SearchBudget()).lower for c in columns), values)

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
        class HistoryPolicy:
            version = "history-dependent-test-v1"

            def choose(self, observation):
                # An arbitrary client may inspect all authorized state. No
                # dependency claim is inferred from a matching version name.
                return PublicSkipOptionalPolicy().choose(observation)

        model = FixedPolicyDayGame(matching_root(), policy=HistoryPolicy())
        after = commit_pair(model._root, red_commands(next(model.rows())), next(model.columns()))
        other = after.clone()
        other._event("public_test", "a different public history")
        position = (after.state.loop, after.state.round)
        self.assertNotEqual(model.continuation._cache_key(after, position), model.continuation._cache_key(other, position))
        self.assertEqual(model.continuation.context_mode, "authorized-history-v1")
        menu_only = FixedPolicyDayGame(matching_root())
        self.assertEqual(menu_only.continuation._cache_key(after, position), menu_only.continuation._cache_key(other, position))
        self.assertEqual(menu_only.continuation.context_mode, "audited-menu-only-v1")
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
