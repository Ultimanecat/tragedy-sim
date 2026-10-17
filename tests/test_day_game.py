"""Unpruned card domains and independent full-engine day-tree checks."""

from collections import Counter
from copy import deepcopy
from itertools import permutations
import unittest

from tragedy_sim import Game
from tragedy_sim.day_game import (CompleteCardSpace, DayContinuationSolver, PureDaySolver,
                                  ValueBounds, WorkLimit, engine_red_bundles, commit_pair)
from tragedy_sim.day_game.continuation import day_boundary_value
from tragedy_sim.scenario_library import ScenarioLibrary


def root(faces=("d", "fg", "h")):
    scenario = ScenarioLibrary().get("official-fs-01-first-script")
    scenario["cast"]["worker"], scenario["cast"]["student"] = "ordinary", "killer"
    world = Game(scenario)
    while world.state.phase != "mastermind":
        world = world.transition(world.legal_actions(world.controller)[0]).game
    world.state.loop, world.state.round, world.state.leader = 2, 2, "c"
    world.protagonist_order = ("c", "a", "b")
    for cid, area in {"girl": "shrine", "doctor": "shrine", "maiden": "shrine",
                      "worker": "city", "police": "city", "student": "school"}.items():
        world.state.characters[cid].location = area
    world.state.characters["worker"].paranoia = 1
    world.state.characters["worker"].intrigue = 2
    world.state.characters["police"].intrigue = 1
    world.state.characters["maiden"].goodwill = 1
    for face, target in zip(faces, ("girl", "worker", "doctor")):
        world = world.transition(dict(actor="m", action="play", card=face, target=target)).game
    return world


def commit(world, effects=(("fi", "girl"), ("h", "worker"), ("v", "maiden"))):
    for card, target in effects:
        world = world.transition(dict(actor=world.controller, action="play", card=card, target=target)).game
    return world


def signature(plan):
    return tuple((a["actor"], a["card"], a["target"]) for a in plan)


def brute_day(world, position):
    """No shortcut, interval propagation, playbook or search_transition."""
    if world.winner is not None:
        return int(world.winner == "protagonists")
    if world.state.phase in {"loop_end", "final_guess"} or world.state.loop != position[0]:
        return 0
    if world.state.round != position[1]:
        return 1
    actions = world.legal_actions(world.controller)
    if not actions:
        raise AssertionError("unfinished independent day tree")
    values = [brute_day(world.transition(action).game, position) for action in actions]
    return min(values) if world.controller == "m" else max(values)


class CompleteCardSpaceTests(unittest.TestCase):
    def test_full_raw_fs_domain_without_ai_pruning(self):
        world = root()
        space = CompleteCardSpace(world)
        self.assertEqual(sum(1 for _ in space.red_bundles()), 8**3 * 10 * 9 * 8)
        self.assertEqual(sum(1 for _ in space.black_bundles()), 720)
        triple_fi = tuple(dict(actor=actor, action="play", card="fi", target=target)
                          for actor, target in zip(space.actors, ("hospital", "city", "school")))
        triple_g2 = tuple({**a, "card": "g2"} for a in triple_fi)
        self.assertTrue(space.contains(triple_fi))
        self.assertTrue(space.contains(triple_g2))

    def test_independent_engine_enumeration_matches_complete_product_and_prefixes(self):
        for placed in range(3):
            with self.subTest(placed=placed):
                world = root()
                for c in world.state.characters.values():
                    c.alive = c.id == "girl"
                for actor in world.protagonist_order:
                    world.state.hands[actor] = ["fi"]
                for target in ("girl", "hospital")[:placed]:
                    world = world.transition(dict(actor=world.controller, action="play", card="fi", target=target)).game
                before = deepcopy(world.__dict__)
                space = CompleteCardSpace(world)
                fast = {signature(p) for p in space.red_bundles()}
                gold = {signature(p) for p in engine_red_bundles(world)}
                self.assertEqual(fast, gold)
                self.assertGreater(len(fast), 0)
                self.assertTrue(all(space.contains(p) for p in space.red_bundles()))
                self.assertEqual(world.state, before["state"])
                self.assertEqual(world.history, before["history"])
                self.assertEqual(world.roles, before["roles"])

    def test_limited_cards_keep_seat_owners_and_invalid_bundles_rejected(self):
        world = root()
        world.state.hands["a"].remove("fm")
        world.state.discarded["a"].append("fm")
        space = CompleteCardSpace(world)
        self.assertFalse(any(a["card"] == "fm" for a in space.domains[1]))
        self.assertTrue(any(a["card"] == "fm" for a in space.domains[0]))
        plan = next(space.red_bundles())
        self.assertFalse(space.contains(plan[:-1]))
        self.assertFalse(space.contains((plan[0], plan[0], plan[2])))
        self.assertFalse(space.contains(({**plan[0], "hidden": 1}, *plan[1:])))
        self.assertFalse(space.contains(({**plan[0], "card": "not_a_card"}, *plan[1:])))

    def test_root_validation(self):
        with self.assertRaises(ValueError):
            CompleteCardSpace(Game())
        with self.assertRaises(ValueError):
            CompleteCardSpace(commit(root()))

    def test_black_domain_matches_physical_permutations_after_limited_card_discard(self):
        world = root()
        world.state.hands["m"].remove("i2")
        world.state.discarded["m"].append("i2")
        existing = [p for p in world.state.pending if p.actor == "m"]
        available = set(world.state.hands["m"]) | {p.card for p in existing}
        actual = {tuple(p.card for p in plan) for plan in CompleteCardSpace(world).black_bundles()}
        self.assertEqual(actual, set(permutations(available, 3)))
        self.assertEqual(len(actual), 504)


class ExactDayTreeTests(unittest.TestCase):
    def test_known_joint_gap_four_cases_with_all_legal_abilities(self):
        for faces, expected in ((("v", "p-1", "h"), 1), (("d", "p-1", "h"), 1),
                                (("v", "fg", "h"), 1), (("d", "fg", "h"), 0)):
            with self.subTest(faces=faces):
                world = commit(root(faces))
                before = deepcopy(world.view("m"))
                result = DayContinuationSolver().solve(world, work=WorkLimit(node_limit=20000))
                self.assertTrue(result.bounds.exact, result)
                self.assertEqual(result.bounds.lower, expected)
                self.assertEqual(brute_day(world, (2, 2)), expected)
                self.assertEqual(world.view("m"), before)
                self.assertEqual(result.continuation, "all-engine-legal-decisions")

    def goodwill_root(self, refuses):
        scenario = ScenarioLibrary().get("official-fs-01-first-script")
        if not refuses:
            scenario["cast"]["doctor"], scenario["cast"]["student"] = "ordinary", "brain"
        world = Game(scenario)
        world.state.round = 3
        world.state.phase = "goodwill"
        for c in world.state.characters.values():
            c.alive = c.id in {"girl", "doctor"}
        world.state.characters["girl"].location = "hospital"
        world.state.characters["girl"].paranoia = 3
        world.state.characters["doctor"].goodwill = 2
        return world

    def test_red_goodwill_choices_and_black_refusal_are_real_tree_nodes(self):
        for refuses, expected in ((False, 1), (True, 0)):
            with self.subTest(refuses=refuses):
                world = self.goodwill_root(refuses)
                result = DayContinuationSolver().solve(world)
                self.assertEqual(result.bounds, ValueBounds(expected, expected))
                self.assertEqual(brute_day(world, (1, 3)), expected)
                if not refuses:
                    self.assertEqual(result.principal_action["action"], "choose")
                    skipped = world.transition(dict(actor=world.controller, action="next")).game
                    self.assertEqual(DayContinuationSolver().solve(skipped).bounds, ValueBounds(0, 0))

    def test_limits_keep_unknown_intervals_and_shared_work(self):
        world = commit(root())
        work = WorkLimit(node_limit=1)
        first = DayContinuationSolver().solve(world, work=work)
        second = DayContinuationSolver().solve(world, work=work)
        self.assertEqual(first.bounds, ValueBounds(0, 1))
        self.assertEqual(second.bounds, ValueBounds(0, 1))
        self.assertEqual(first.nodes, 1)
        self.assertEqual(second.nodes, 0)
        self.assertIn("node_limit", first.stop_reasons)
        self.assertFalse(first.bounds.exact)
        shallow = DayContinuationSolver(max_depth=1).solve(world)
        self.assertEqual(shallow.bounds, ValueBounds(0, 1))
        self.assertIn("depth_limit", shallow.stop_reasons)
        clock = WorkLimit(time_limit_ms=1)
        clock.started -= 1
        timed = DayContinuationSolver().solve(world, work=clock)
        self.assertEqual(timed.nodes, 0)
        self.assertEqual(timed.bounds, ValueBounds(0, 1))
        self.assertIn("time_limit", timed.stop_reasons)

    def test_day_boundary_does_not_continue_to_next_loop_or_guess(self):
        world = commit(root())
        world.state.phase = "loop_end"
        self.assertEqual(DayContinuationSolver().solve(world).bounds, ValueBounds(0, 0))
        world.state.phase = "final_guess"
        self.assertEqual(day_boundary_value(world, (2, 2)), 0)
        world.state.phase = "day_start"
        world.state.round = 3
        self.assertEqual(DayContinuationSolver().solve(world, position=(2, 2)).bounds, ValueBounds(1, 1))
        world.winner = "protagonists"
        self.assertEqual(day_boundary_value(world, (2, 2)), 1)

    def test_invalid_configuration_and_uncommitted_cards(self):
        with self.assertRaises(ValueError):
            DayContinuationSolver().solve(root())
        for n in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                WorkLimit(node_limit=n)
            with self.assertRaises(ValueError):
                DayContinuationSolver(max_depth=n)
        for lo, hi in ((-1, 1), (1, 0), (0, 2), (float("nan"), 1)):
            with self.assertRaises(ValueError):
                ValueBounds(lo, hi)


class PureDayTests(unittest.TestCase):
    def quiet_root(self):
        world = Game(ScenarioLibrary().get("official-fs-01-first-script"))
        while world.state.phase != "mastermind":
            world = world.transition(world.legal_actions(world.controller)[0]).game
        for c in world.state.characters.values():
            c.alive = c.id == "girl"
        for face, target in (("h", "hospital"), ("v", "shrine"), ("i1", "city")):
            world = world.transition(dict(actor="m", action="play", card=face, target=target)).game
        return world

    def test_security_one_certifies_unpruned_root_without_scanning_every_red(self):
        world = self.quiet_root()
        before = deepcopy(world.view("m"))
        result = PureDaySolver().solve(world, work=WorkLimit(node_limit=10000))
        self.assertEqual(result.bounds, ValueBounds(1, 1))
        self.assertEqual(result.black_actions, 720)
        self.assertEqual(result.red_actions, 8**3 * 5 * 4 * 3)
        self.assertEqual(result.evaluated_red, 1)
        self.assertEqual(result.evaluated_pairs, 720)
        self.assertEqual(result.stop_reason, "proven_security_one")
        self.assertEqual(world.view("m"), before)

    def test_budget_never_reports_no_defense_or_false_optimality(self):
        result = PureDaySolver().solve(root(), work=WorkLimit(node_limit=1))
        self.assertEqual(result.bounds, ValueBounds(0, 1))
        self.assertEqual(result.stop_reason, "node_limit")
        self.assertEqual(result.evaluated_pairs, 1)
        self.assertTrue(result.action_domain_complete)
        self.assertIsNotNone(result.red_bundle)

    def test_security_zero_requires_covering_all_red_rows(self):
        world = self.quiet_root()
        world.state.characters["maiden"].alive = True
        world.state.characters["girl"].location = "shrine"
        for actor in world.protagonist_order:
            world.state.hands[actor] = ["fi"]
        result = PureDaySolver().solve(world)
        self.assertEqual(result.bounds, ValueBounds(0, 0))
        self.assertEqual(result.red_actions, 6 * 5 * 4)
        self.assertEqual(result.evaluated_red, result.red_actions)
        self.assertEqual(result.evaluated_pairs, result.red_actions)
        self.assertEqual(result.stop_reason, "complete_domain")
        black = next(CompleteCardSpace(world).black_bundles())
        for red in engine_red_bundles(world):
            self.assertEqual(brute_day(commit_pair(world, red, black), (1, 1)), 0)

    def test_pair_clones_full_state_keeps_black_resources_and_engine_red_legality(self):
        world = root()
        space = CompleteCardSpace(world)
        red = next(space.red_bundles())
        black = next(space.black_bundles())
        before = deepcopy(world.state)
        after = commit_pair(world, red, black)
        self.assertEqual(after.state.phase, "reveal")
        self.assertEqual(len(after.state.pending), 6)
        self.assertEqual(world.state, before)
        self.assertEqual(set(after.state.hands["m"]) | {p.card for p in black},
                         set(world.state.hands["m"]) | {p.card for p in world.state.pending})
        from tragedy_sim.engine import Placement
        with self.assertRaises(ValueError):
            commit_pair(world, red, (Placement("m", "d", "girl"),) * 3)

    def test_warmstart_does_not_shrink_full_domain_and_partial_red_root_rejected(self):
        world = self.quiet_root()
        first = next(CompleteCardSpace(world).red_bundles())
        result = PureDaySolver().solve(world, warmstarts=(first, first), work=WorkLimit(node_limit=10000))
        self.assertEqual(result.bounds, ValueBounds(1, 1))
        self.assertEqual(result.evaluated_red, 1)
        with self.assertRaises(ValueError):
            PureDaySolver().solve(world, warmstarts=((dict(actor="a", action="play", card="none", target="girl"),),))
        with self.assertRaises(ValueError):
            PureDaySolver().solve(world, warmstarts=(first, ({**first[0], "card": "none"}, *first[1:])))
        partial = world.transition(first[0]).game
        with self.assertRaises(ValueError):
            PureDaySolver().solve(partial)

    def test_complete_rows_with_unknown_continuations_do_not_claim_complete_solution(self):
        # Five public targets, one red face per seat, three black faces:
        # 60 rows x 6 columns, each deliberately stopped before day end.
        world = self.quiet_root()
        for actor in world.protagonist_order:
            world.state.hands[actor] = ["fi"]
        world.state.discarded["m"] = list(world.state.hands["m"])
        world.state.hands["m"] = []
        result = PureDaySolver(max_depth=1).solve(world)
        self.assertEqual(result.evaluated_red, 60)
        self.assertEqual(result.evaluated_pairs, 360)
        self.assertEqual(result.bounds, ValueBounds(0, 1))
        self.assertEqual(result.stop_reason, "continuation_incomplete")
        self.assertEqual(result.continuation_stop_reasons, ("depth_limit",))


if __name__ == "__main__":
    unittest.main()
