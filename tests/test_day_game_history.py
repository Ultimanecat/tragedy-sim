"""Native compatible histories and adversarial alternatives within one type."""

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as Q
import unittest
from unittest.mock import patch

from tragedy_sim import Game
from tragedy_sim.belief import HiddenWorldHypothesis, PublicEvidence, PublicSnapshot
from tragedy_sim.day_game.bayesian import BayesianDoubleOracle
from tragedy_sim.day_game.continuation import WorkLimit
from tragedy_sim.day_game.fair_engine import HistoryDayGame, bayesian_engine_game, public_policy_input
from tragedy_sim.day_game.history import replay_public_history
from tragedy_sim.day_game.keys import rule_state_key
from tragedy_sim.day_game.posterior import PosteriorSelection, WeightedSetup, reconstruct_public_roots
from tragedy_sim.day_game.zero_sum import SearchBudget
from tragedy_sim.scenario_library import ScenarioLibrary
from benchmarks.ai_bayesian_day import continuation_work, result_payload
from tests.test_day_game_mixed_engine import matching_root


def second_day_root(*, rumor=False, next_loop=False):
    scenario = ScenarioLibrary().get("official-fs-01-first-script")
    if rumor:
        scenario["subplots"] = ["rumor"]
        scenario["cast"]["maiden"] = "ordinary"
    world = Game(scenario)
    for _ in range(100):
        if (world.state.loop, world.state.round) == ((2, 1) if next_loop else (1, 2)) and world.state.phase == "protagonists":
            return world
        actor = world.controller
        actions = world.legal_actions(actor)
        if world.state.phase == "mastermind":
            index = len(world.state.pending)
            cards, targets = (("h", "v", "p-1"), ("hospital", "school", "city")) if world.state.round == 1 else (
                ("h", "v", "fg"), ("girl", "worker", "doctor"))
            if next_loop and world.state.loop == 1:
                cards, targets = ("v", "p-1", "fg"), ("girl", "hospital", "school")
            command = dict(actor="m", action="play", card=cards[index], target=targets[index])
        elif world.state.phase == "protagonists":
            index = sum(p.actor != "m" for p in world.state.pending)
            command = dict(actor=actor, action="play", card="fi", target=("hospital", "school", "city")[index])
        elif rumor and world.state.round == 1 and world.state.phase == "master_abilities" and "plot:rumor" not in world.loop_used:
            index = next(i for i, option in enumerate(world.options("m"), 1)
                         if option.get("key") == "plot:rumor" and option["effects"][0]["target"] == "hospital")
            command = dict(actor="m", action="choose", index=index)
        else:
            command = next((a for a in actions if a["action"] == "next"), actions[0])
        world = world.transition(command).game
    raise AssertionError("fixture did not reach second day")


def inputs(world):
    view = world.protagonist_team_view()
    hypothesis = replace(HiddenWorldHypothesis.from_scenario(world.scenario),
                         roles=tuple(world.scenario["cast"].items()))
    own = tuple(c for c in world.history if c["actor"] != "m")
    return hypothesis, PublicEvidence.from_view(view), view, own


def singleton_selection(world, view):
    hypothesis, _, _, _ = inputs(world)
    return PosteriorSelection((WeightedSetup(hypothesis, Q(1)),), Q(1), Q(0), 1, 1, 1,
                              "complete", "unit-known-setup", PublicSnapshot.from_view(view).key)


class HistoryReplayTests(unittest.TestCase):
    def test_native_loop_loss_reset_retains_the_actual_previous_dead_history(self):
        actual = second_day_root(next_loop=True)
        hypothesis, evidence, view, own = inputs(actual)
        support = replay_public_history(hypothesis, evidence, view, own)
        self.assertTrue(support.complete, support.reasons)
        self.assertEqual(len(support.roots), 1)
        self.assertIn("girl", support.roots[0]._previous_dead)
        self.assertEqual(support.roots[0]._previous_dead, actual._previous_dead)
        self.assertEqual(support.roots[0]._previous_goodwill, actual._previous_goodwill)
        self.assertTrue(support.roots[0].state.characters["girl"].alive)
        self.assertEqual(public_policy_input(support.roots[0]), public_policy_input(actual))

    def test_native_indistinguishable_rumor_and_brain_keep_both_private_use_states(self):
        actual = second_day_root(rumor=True)
        hypothesis, evidence, view, own = inputs(actual)
        support = replay_public_history(hypothesis, evidence, view, own)
        self.assertTrue(support.complete, support.reasons)
        self.assertEqual(len(support.roots), 2)
        partial = replay_public_history(hypothesis, evidence, view, own, work=WorkLimit(node_limit=support.nodes-1))
        self.assertFalse(partial.complete)
        self.assertGreater(len(partial.roots), 0)
        self.assertEqual({"plot:rumor" in root.loop_used for root in support.roots}, {False, True})
        self.assertTrue(all(public_policy_input(root) == public_policy_input(actual) for root in support.roots))
        selected = singleton_selection(actual, view)
        reconstructed = reconstruct_public_roots(selected, view, own_commands=own, allow_state_prior=False, history_node_limit=10000)
        model = reconstructed.model()
        self.assertEqual(model.covered_mass, 1)
        self.assertEqual(len(model.blocks), 1)
        self.assertTrue(model.belief_domain_complete)
        self.assertEqual(len(model.blocks[0].game.variants), 2)
        self.assertEqual(model.blocks[0].game.column_count, 1440)

    def test_replay_native_second_day_root_without_true_world_or_prior(self):
        actual = second_day_root()
        hypothesis, evidence, view, own = inputs(actual)
        with patch("tragedy_sim.scenario_library.ScenarioLibrary.get", side_effect=AssertionError("secret lookup")):
            support = replay_public_history(hypothesis, evidence, view, own)
        self.assertTrue(support.complete, support.reasons)
        self.assertGreater(support.nodes, 0)
        self.assertEqual(len(support.roots), 1)
        reconstructed = support.roots[0]
        self.assertEqual(public_policy_input(reconstructed), public_policy_input(actual))
        # Canonical faces can differ. Applying the actual physical faces
        # restores the exact native rule state and both players' own memory.
        from tragedy_sim.day_game.pure import commit_pair
        from tragedy_sim.day_game.engine_game import red_commands
        from tragedy_sim.day_game.fair_engine import FixedPolicyDayGame
        model = FixedPolicyDayGame(actual)
        row = next(model.rows())
        faces = tuple(actual.state.pending)
        rebuilt = commit_pair(reconstructed, red_commands(row), faces)
        native = commit_pair(actual, red_commands(row), faces)
        # Public setup materialization normalizes absent special_rules to {},
        # and omits the library's loop_options display metadata. Conservative
        # keys intentionally distinguish those static representations.
        left, right = dict(rebuilt.scenario), dict(native.scenario)
        left.pop("loop_options", None)
        right.pop("loop_options", None)
        left.setdefault("special_rules", {})
        right.setdefault("special_rules", {})
        self.assertEqual(left, right)
        for name, value in rule_state_key(native).fields:
            if name not in {"scenario", "script"}:
                self.assertEqual(value, dict(rule_state_key(rebuilt).fields)[name], name)

    def test_revealed_faces_are_historical_evidence_not_private_current_faces(self):
        hypothesis, evidence, view, own = inputs(second_day_root())
        altered = deepcopy(view)
        altered["title"] = "different presentation"
        for event in altered["events"]:
            event["message"] = "translated text"
        first = replay_public_history(hypothesis, evidence, view, own)
        second = replay_public_history(hypothesis, evidence, altered, own)
        self.assertEqual((first.complete, len(first.roots)), (second.complete, len(second.roots)))
        self.assertEqual(second.roots[0].state.events, altered["events"])
        bad = deepcopy(view)
        next(e for e in bad["events"] if e["kind"] == "cards_revealed")["cards"][0]["card"] = "i2"
        contradicted = replay_public_history(hypothesis, evidence, bad, own)
        self.assertTrue(contradicted.complete)
        self.assertEqual(contradicted.roots, ())

    def test_missing_own_command_or_false_final_board_is_rejected(self):
        hypothesis, evidence, view, own = inputs(second_day_root())
        for bad_view, bad_own in ((view, own[:-1]), (view, (*own, own[-1]))):
            support = replay_public_history(hypothesis, evidence, bad_view, bad_own)
            self.assertTrue(support.complete)
            self.assertFalse(support.roots)
        view["characters"]["girl"]["paranoia"] += 1
        self.assertFalse(replay_public_history(hypothesis, evidence, view, own).roots)

    def test_budget_and_depth_leave_unknown_support_and_do_not_spend_action_work(self):
        args = inputs(second_day_root())
        short = replay_public_history(*args, work=WorkLimit(node_limit=1))
        self.assertFalse(short.complete)
        self.assertIn("node_limit", short.reasons)
        depth = replay_public_history(*args, max_depth=1)
        self.assertFalse(depth.complete)
        self.assertIn("history_depth_limit", depth.reasons)

    def test_private_input_and_black_commands_are_rejected(self):
        hypothesis, evidence, view, own = inputs(second_day_root())
        for modified in ({"viewer": "m"}, {"secret": {}}, {"phase": "goodwill"}):
            with self.assertRaises(ValueError):
                replay_public_history(hypothesis, evidence, {**view, **modified}, own)
        with self.assertRaises(ValueError):
            replay_public_history(hypothesis, evidence, view, (*own, dict(actor="m", action="next")))

    def test_bridge_exact_replay_preserves_mass_and_refuses_truncated_support(self):
        actual = second_day_root()
        _, _, view, own = inputs(actual)
        selected = singleton_selection(actual, view)
        strict = reconstruct_public_roots(selected, view, own_commands=own, allow_state_prior=False, history_node_limit=10000)
        self.assertEqual((strict.failed_mass, strict.approximated_state_mass), (0, 0))
        self.assertTrue(strict.history_audits[0][1])
        self.assertTrue(strict.model().belief_domain_complete)
        partial = reconstruct_public_roots(selected, view, own_commands=own, allow_state_prior=False, history_node_limit=1)
        self.assertEqual(partial.failed_mass, 1)
        self.assertFalse(partial.roots)
        prior = reconstruct_public_roots(selected, view, own_commands=own, history_node_limit=1)
        self.assertEqual(prior.approximated_state_mass, 1)
        self.assertFalse(prior.model().belief_domain_complete)
        impossible = reconstruct_public_roots(selected, view, own_commands=own[:-1], history_node_limit=10000)
        self.assertEqual(impossible.failed_mass, 1)
        self.assertEqual(impossible.approximated_state_mass, 0)
        self.assertEqual(impossible.failures[0][2], "no_compatible_history")


class AdversarialHistoryTests(unittest.TestCase):
    def test_histories_are_black_columns_not_duplicated_probability(self):
        root = matching_root()
        other = root.clone()
        other.day_used.add("unit-private-flag")
        model = bayesian_engine_game((("setup", Q(2, 3), (root, other)),))
        self.assertEqual(model.covered_mass, Q(2, 3))
        self.assertEqual(len(model.blocks), 1)
        game = model.blocks[0].game
        self.assertIsInstance(game, HistoryDayGame)
        self.assertEqual(game.column_count, 12)
        row = next(game.rows())
        for index, column in game.columns():
            self.assertTrue(game.contains_column((index, column)))
            self.assertEqual(game.evaluate(row, (index, column), SearchBudget()),
                             game.variants[index].evaluate(row, column, SearchBudget()))
        # A failing compatible past defeats a safe past; averaging would
        # incorrectly report 1/2. Both choose before the private red draw.
        with (patch.object(game.variants[0], "evaluate", return_value=game.utility.__class__(1, 1)),
              patch.object(game.variants[1], "evaluate", return_value=game.utility.__class__(0, 0))):
            result = BayesianDoubleOracle(model).solve(budget=SearchBudget(payoff_limit=1000))
        self.assertEqual(result.lower_bound, 0)
        self.assertEqual(result.upper_bound, Q(1, 3))
        report = result_payload(result)
        self.assertTrue(all("history_index" in entry for entry in report["black"][0]["conditional_policy"]))
        self.assertEqual(continuation_work(game)["compatible_histories"], 2)
        self.assertFalse(game.contains_column((True, next(game.variants[0].columns()))))

    def test_different_authorized_observations_and_empty_support_are_rejected(self):
        root = matching_root()
        other = root.clone()
        other._event("unit", "visible difference")
        with self.assertRaises(ValueError):
            HistoryDayGame((root, other))
        with self.assertRaises(ValueError):
            HistoryDayGame(())


if __name__ == "__main__":
    unittest.main()
