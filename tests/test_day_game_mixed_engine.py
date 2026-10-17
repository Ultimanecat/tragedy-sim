"""Full current-hand FS domains: real day trees feed a mixed-game oracle."""

from copy import deepcopy
from fractions import Fraction as Q
import unittest

from tests import test_day_game as fixtures
from tragedy_sim import Game
from tragedy_sim.cards import deck
from tragedy_sim.engine import Placement
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.day_game import CompleteCardSpace, WorkLimit
from tragedy_sim.day_game.engine_game import EngineDayGame, red_commands
from tragedy_sim.day_game.matrix import solve_matrix
from tragedy_sim.day_game.zero_sum import DoubleOracle, SearchBudget


def matching_root():
    """Controlled FS state with one moving seat, not an official-play claim."""
    scenario = ScenarioLibrary().get("official-fs-01-first-script")
    scenario["cast"]["girl"], scenario["cast"]["maiden"] = "serial", "key"
    world = Game(scenario)
    while world.state.phase != "mastermind":
        world = world.transition(world.legal_actions(world.controller)[0]).game
    world.state.leader = "c"
    world.configure_actions(protagonists=("c", "a", "b"))
    for character in world.state.characters.values():
        character.alive = character.id in {"girl", "maiden"}
    world.state.characters["girl"].location = "shrine"
    world.state.hands.update(a=["g1"], b=["g1"], c=["h", "v"])
    # Artificial public card-domain restriction, not reachable ordinary-card
    # discards in an official FS match. This isolates the matching game.
    world.state.hands["m"] = ["h", "v", "fp"]
    world.state.discarded["m"] = [c for c in deck("m") if c not in {"h", "v", "fp"}]
    for card, target in (("h", "maiden"), ("v", "hospital"), ("fp", "city")):
        world = world.transition(dict(actor="m", action="play", card=card, target=target)).game
    return world


class EngineMixedGameTests(unittest.TestCase):
    def test_unknown_committed_actual_faces_do_not_change_fixed_work_policy(self):
        results = []
        for faces in (("d", "fg", "h"), ("v", "p-1", "h")):
            model = EngineDayGame(fixtures.root(faces))
            solver = DoubleOracle(model)
            result = solver.solve(budget=SearchBudget(payoff_limit=12))
            results.append((result.red, result.black, result.lower_bound, result.upper_bound,
                            result.generated_rows, result.generated_columns))
        self.assertEqual(results[0], results[1])

    def test_complete_cardinality_matches_product_and_independent_prefix_cases(self):
        world = fixtures.root()
        self.assertEqual(CompleteCardSpace(world).count_red(), 368640)
        for prefix in range(3):
            world = fixtures.root()
            for character in world.state.characters.values():
                character.alive = character.id == "girl"
            for actor in world.protagonist_order:
                world.state.hands[actor] = ["fi"]
            for target in ("girl", "hospital")[:prefix]:
                world = world.transition(dict(actor=world.controller, action="play", card="fi", target=target)).game
            space = CompleteCardSpace(world)
            self.assertEqual(space.count_red(), sum(1 for _ in space.red_bundles()))
            self.assertEqual(space.count_red(), sum(1 for _ in fixtures.engine_red_bundles(world)))

    def test_controlled_fs_game_mixed_two_thirds_beats_every_pure_action(self):
        world = matching_root()
        before = deepcopy(world.state)
        model = EngineDayGame(world)
        self.assertEqual((model.row_count, model.column_count), (240, 6))
        rows, columns = tuple(model.rows()), tuple(model.columns())
        budget = SearchBudget()
        matrix = tuple(tuple(model.evaluate(row, column, budget).lower for column in columns) for row in rows)
        self.assertEqual(max(min(row) for row in matrix), 0)
        # A 6-row dual reference is much smaller than a 240-slack tableau.
        neg_transpose = tuple(tuple(-matrix[i][j] for i in range(len(rows))) for j in range(len(columns)))
        # Moving either character or making a legal no-op yields three
        # complementary defenses. Removing no-op bluffs would change this game.
        self.assertEqual(-solve_matrix(neg_transpose).value, Q(2, 3))
        result = DoubleOracle(model).solve(max_iterations=32)
        self.assertTrue(result.certified_optimal, result)
        self.assertEqual(result.lower_bound, Q(2, 3))
        self.assertEqual(result.gap, 0)
        self.assertTrue(result.best_response_complete)
        self.assertTrue(all(model.contains_row(plan) for plan, _ in result.red))
        self.assertTrue(all(model.contains_column(plan) for plan, _ in result.black))
        self.assertEqual(world.state, before)

    def test_real_engine_quiet_root_certifies_one_with_full_black_domain(self):
        world = fixtures.PureDayTests().quiet_root()
        model = EngineDayGame(world, backend="compiled")
        solver = DoubleOracle(model)
        result = solver.solve()
        self.assertTrue(result.certified_optimal)
        self.assertEqual(result.lower_bound, 1)
        self.assertEqual(model.column_count, 720)
        self.assertEqual(result.iterations[-1].black_response.visited, 720)
        self.assertLess(result.iterations[-1].red_response.visited, model.row_count)

    def test_budget_unknown_cells_do_not_leak_true_faces_or_claim_optimality(self):
        model = EngineDayGame(fixtures.root())
        result = DoubleOracle(model).solve(budget=SearchBudget(work=WorkLimit(node_limit=1)))
        self.assertEqual((result.lower_bound, result.upper_bound), (0, 1))
        self.assertFalse(result.certified_optimal)
        self.assertTrue(model.continuation_reasons)
        self.assertEqual(len(result.red), 1)

    def test_malformed_seed_partial_root_and_unknown_backends_rejected(self):
        world = fixtures.root()
        model = EngineDayGame(world)
        for plan in (None, ["not-a-command"], [{"actor": "c", "action": "play", "card": "fi", "target": []}]):
            with self.assertRaises(ValueError):
                model.plan(plan)
        self.assertFalse(model.contains_column((Placement("m", "h", []),)))
        first = next(model.rows())
        self.assertEqual(model.plan(red_commands(first)), first)
        partial = world.transition(red_commands(first)[0]).game
        with self.assertRaises(ValueError):
            EngineDayGame(partial)
        with self.assertRaises(ValueError):
            EngineDayGame(world, backend="other")


if __name__ == "__main__":
    unittest.main()
