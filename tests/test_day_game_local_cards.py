"""Local math exhaustiveness and full-phase public/private engine equivalence."""

from copy import deepcopy
from itertools import product
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.test_day_game import root, commit, brute_day
from tragedy_sim import Game
from tragedy_sim.cards import Card, deck
from tragedy_sim.engine import Placement
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.day_game import CompleteCardSpace, commit_pair, PureDaySolver, ValueBounds
from tragedy_sim.day_game.cached import CachedDayContinuationSolver
from tragedy_sim.day_game.kernel import FsTransitionKernel
from tragedy_sim.day_game.keys import DIAGNOSTICS, rule_state_key, information_key
from tragedy_sim.day_game.local_cards import (compile_local, target_programs,
                                             resolve_counters, resolve_movements)


def same_world(test, actual, expected):
    test.assertIs(type(actual), Game)
    test.assertEqual(set(vars(actual)), set(vars(expected)))
    for name in vars(expected).keys() - DIAGNOSTICS:
        test.assertEqual(getattr(actual, name), getattr(expected, name), name)
    test.assertEqual(actual.decisions[-1], expected.decisions[-1])
    test.assertEqual(actual.legal_actions(actual.controller), expected.legal_actions(expected.controller))


def raw_pair(base, target, origin, count, red, black):
    world = base.clone()
    world.state.phase, world.state.face_up = "action_counters", True
    if target in world.state.characters:
        char = world.state.characters[target]
        char.location = origin
        char.paranoia = char.goodwill = char.intrigue = count
    else:
        world.state.locations[target] = count
    world.state.pending = [Placement(actor, card, target) for actor, card in (("m", black), ("a", red))
                           if card is not None]
    for placement in world.state.pending:
        world.state.hands[placement.actor].remove(placement.card)
    return world


class LocalCardProgramTests(unittest.TestCase):
    def test_every_base_face_pair_location_count_and_forbidden_destination(self):
        base = Game(ScenarioLibrary().get("official-fs-01-first-script"))
        cases = 0
        for target, origins in (("girl", ("hospital", "shrine", "city", "school")),
                                ("worker", ("hospital", "shrine", "city")), ("hospital", (None,))):
            for origin, count, red, black in product(origins, (0, 2), (None, *deck("a")), (None, *deck("m"))):
                gold = raw_pair(base, target, origin, count, red, black)
                actual = gold.clone()
                programs = target_programs(actual)
                self.assertIsNotNone(programs)
                gold._resolve_movements()
                resolve_movements(actual, programs)
                self.assertEqual(actual.state, gold.state, (target, origin, count, red, black, "move"))
                gold._resolve_counters()
                resolve_counters(actual, programs)
                self.assertEqual(actual.state, gold.state, (target, origin, count, red, black, "counter"))
                self.assertEqual(actual.roles, gold.roles)
                cases += 1
        self.assertEqual(cases, 1584)

    def test_three_directions_zero_offset_still_emits_move_and_uses_unique_directions(self):
        world = Game(ScenarioLibrary().get("official-fs-01-first-script"))
        world.state.phase, world.state.face_up = "action_counters", True
        world.state.pending = [Placement("m", "d", "girl"), Placement("a", "h", "girl"),
                               Placement("b", "v", "girl")]
        programs = target_programs(world)
        self.assertEqual(programs[0][1].movement, (0, 0))
        gold = world.clone()
        gold._resolve_movements()
        resolve_movements(world, programs)
        self.assertEqual(world.state, gold.state)
        self.assertEqual(world.state.events[-1]["kind"], "character_moved")

    def test_global_forbid_cancellation_and_ignored_cards(self):
        world = commit(root(("i2", "fg", "h")), (("fi", "girl"), ("fi", "city"), ("fi", "school")))
        for ignored in (set(), {3}, {3, 4}):
            gold = world.transition(world.legal_actions(world.controller)[0]).game
            gold._ignored_placement_indexes = set(ignored)
            actual = gold.clone()
            gold._resolve_counters()
            resolve_counters(actual, target_programs(actual))
            self.assertEqual(actual.state, gold.state)
            self.assertEqual(actual.roles, gold.roles)

    def test_positive_then_negative_trigger_is_preserved_before_final_counter(self):
        world = Game(ScenarioLibrary().get("official-fs-01-first-script"))
        # Exercise the shared counter mutation primitive, including its
        # intermediate threshold. This is a controlled engine-state probe,
        # not a claim that Virus is a legal FS setup.
        world.scenario["subplots"] = ["virus"]
        world = raw_pair(world, "student", "school", 2, "p-1", "p1a")
        gold = world.clone()
        gold._resolve_counters()
        resolve_counters(world, target_programs(world))
        self.assertEqual(world.state, gold.state)
        self.assertEqual(world.roles, gold.roles)
        self.assertEqual(world.state.characters["student"].paranoia, 2)
        self.assertEqual(world.roles["student"], "serial")

    def test_unknown_effect_refuses_compilation_without_partial_program(self):
        self.assertIsNone(compile_local((Card("future", "future", "new_rule"),)))
        self.assertIsNone(compile_local((SimpleNamespace(effect="horizontal"),)))
        self.assertIsNone(compile_local((Card("future", "future", "horizontal", amount=[]),)))
        self.assertIs(compile_local((deck("a")["h"],)), compile_local((deck("a")["h"],)))


class CompiledCardPhaseTests(unittest.TestCase):
    def test_every_black_bundle_matches_complete_engine_reveal_and_counter_phases(self):
        source = root()
        red = next(CompleteCardSpace(source).red_bundles())
        kernel = FsTransitionKernel(compiled=True)
        for black in CompleteCardSpace(source).black_bundles():
            gold = commit_pair(source, red, black)
            actual = commit_pair(source, red, black, kernel=kernel)
            for _ in range(2):
                command = gold.legal_actions(gold.controller)[0]
                gold = gold.transition(command).game
                actual = kernel.transition(actual, command)
                same_world(self, actual, gold)
        self.assertEqual(kernel.program_stats.movements, 720)
        self.assertEqual(kernel.program_stats.counters, 720)
        self.assertEqual(kernel.program_stats.fallbacks, 0)
        self.assertEqual(kernel.fallback_clones, 0)

    def test_echo_uses_original_location_and_does_not_duplicate_limited_card_consumption(self):
        scenario = ScenarioLibrary().get("official-fs-01-first-script")
        scenario["cast"]["illusion"] = scenario["cast"].pop("student")
        world = Game(scenario)
        while world.state.phase != "mastermind":
            world = world.transition(world.legal_actions(world.controller)[0]).game
        for actor, card, target in (("m", "i1", "shrine"), ("m", "p1a", "girl"), ("m", "h", "worker"),
                                    ("a", "fi", "hospital"), ("b", "g2", "shrine"), ("c", "v", "doctor")):
            world = world.transition(dict(actor=actor, action="play", card=card, target=target)).game
        kernel = FsTransitionKernel(compiled=True)
        gold = world
        actual = world.clone()
        for _ in range(2):
            command = gold.legal_actions(gold.controller)[0]
            gold = gold.transition(command).game
            actual = kernel.transition(actual, command)
            same_world(self, actual, gold)
        self.assertEqual(actual.state.characters["illusion"].intrigue, 1)
        self.assertEqual(actual.state.characters["illusion"].goodwill, 2)
        self.assertEqual(actual.state.discarded["b"].count("g2"), 1)

    def test_servant_follow_keeps_leader_observation_branch_and_source_queue(self):
        scenario = ScenarioLibrary().get("official-fs-01-first-script")
        scenario["cast"].update(rich="ordinary", boss="ordinary", servant="ordinary")
        scenario["character_options"] = {"servant": {"initial_location": "school"}, "boss": {"territory": "school"}}
        world = Game(scenario)
        while world.state.phase != "mastermind":
            world = world.transition(world.legal_actions(world.controller)[0]).game
        world.state.characters["rich"].location = "school"
        world.state.characters["boss"].location = "school"
        for actor, card, target in (("m", "h", "rich"), ("m", "v", "boss"), ("m", "i1", "hospital"),
                                    ("a", "p1", "girl"), ("b", "g1", "worker"), ("c", "fi", "hospital")):
            world = world.transition(dict(actor=actor, action="play", card=card, target=target)).game
        kernel = FsTransitionKernel(compiled=True)
        gold = world.transition(dict(actor="m", action="resolve")).game
        actual = kernel.transition(world, dict(actor="m", action="resolve"))
        same_world(self, actual, gold)
        self.assertEqual(actual.state.phase, "decision")
        self.assertEqual(actual.controller, "a")
        for command in gold.legal_actions("a"):
            expected = gold.transition(command).game
            branch = kernel.transition(actual, command)
            same_world(self, branch, expected)
            self.assertIn(branch.state.characters["servant"].location, {"city", "shrine"})

    def test_future_card_effect_and_unknown_state_use_engine_fallback(self):
        world = commit(root())
        original_deck = deck

        def future_deck(actor, module=None):
            cards = original_deck(actor, module)
            cards["h"] = Card("h", "future", "new_rule")
            return cards

        kernel = FsTransitionKernel(compiled=True)
        with patch("tragedy_sim.engine.deck", side_effect=future_deck):
            actual = kernel.transition(world, dict(actor="m", action="resolve"))
            gold = world.transition(dict(actor="m", action="resolve")).game
            same_world(self, actual, gold)
        self.assertEqual(kernel.program_stats.movements, 0)
        self.assertEqual(kernel.program_stats.fallbacks, 1)
        world.unreviewed = object()
        kernel.transition(world, dict(actor="m", action="resolve"))
        self.assertGreater(kernel.fallback_clones, 0)

    def test_complete_continuation_values_match_brute_force_and_keep_input_unchanged(self):
        solver = CachedDayContinuationSolver(compiled=True)
        for faces in (("v", "p-1", "h"), ("d", "p-1", "h"), ("v", "fg", "h"), ("d", "fg", "h")):
            world = commit(root(faces))
            before = (deepcopy(world.state), rule_state_key(world), information_key(world))
            expected = brute_day(world, (2, 2))
            self.assertEqual(solver.solve(world).bounds, ValueBounds(expected, expected))
            self.assertEqual((world.state, rule_state_key(world), information_key(world)), before)
        self.assertGreater(solver.kernel.program_stats.movements, 0)
        self.assertGreater(solver.kernel.program_stats.counters, 0)

    def test_full_domain_pure_security_value_and_invalid_command(self):
        from tests import test_day_game as fixtures

        world = fixtures.PureDayTests().quiet_root()
        result = PureDaySolver(backend="compiled").solve(world)
        self.assertEqual(result.bounds, ValueBounds(1, 1))
        self.assertEqual(result.evaluated_pairs, 720)
        self.assertEqual(result.red_actions, 30720)
        source = commit(root())
        before = deepcopy(source.state)
        with self.assertRaises(ValueError):
            FsTransitionKernel(compiled=True).transition(source, dict(actor="a", action="next"))
        self.assertEqual(source.state, before)
        with self.assertRaises(ValueError):
            FsTransitionKernel(compiled="true")


if __name__ == "__main__":
    unittest.main()
