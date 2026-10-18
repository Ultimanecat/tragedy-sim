"""Sequence LP against independent complete pure-policy matrix games."""

from dataclasses import replace
from fractions import Fraction as Q
from itertools import permutations, product
import random
from time import perf_counter
import unittest

from tragedy_sim.day_game.matrix import MatrixLimit, solve_matrix
from tragedy_sim.day_game.sequence_form import (Chance, Decision, Terminal, behavioral_policy,
    build_sequence_game, solve_sequence_game, verify_sequence_solution)


def pure_matrix(root):
    """Independent tree evaluator; no sequence matrix or flow equations."""
    infos = {"red": {}, "black": {}}

    def collect(node):
        if type(node) is Chance:
            for _, child in node.outcomes:
                collect(child)
        elif type(node) is Decision:
            infos[node.player][node.information] = tuple(a for a, _ in node.actions)
            for _, child in node.actions:
                collect(child)
    collect(root)
    policies = {p: tuple(dict(zip(sets, choices)) for choices in product(*sets.values())) for p, sets in infos.items()}

    def value(node, red, black):
        if type(node) is Terminal:
            return Q(node.value)
        if type(node) is Chance:
            return sum(p*value(child, red, black) for p, child in node.outcomes)
        selected = (red if node.player == "red" else black)[node.information]
        return value(dict(node.actions)[selected], red, black)
    return tuple(tuple(value(root, red, black) for black in policies["black"]) for red in policies["red"])


def matching(*, observed=False):
    return Decision("red", "red-root", tuple((str(i), Decision("black", f"black-{i}" if observed else "black-blind",
                    tuple((str(j), Terminal(int(i == j))) for j in range(2)))) for i in range(2)))


class SequenceFormTests(unittest.TestCase):
    def test_kuhn_poker_matches_complete_64_by_64_normal_form(self):
        deals = []
        for red_card, black_card in permutations(range(3), 2):
            sign = 1 if red_card > black_card else -1
            after_bet = Decision("black", f"black-facing-bet/{black_card}",
                                 (("fold", Terminal(1)), ("call", Terminal(2*sign))))
            after_check_bet = Decision("red", f"red-facing-bet/{red_card}",
                                      (("fold", Terminal(-1)), ("call", Terminal(2*sign))))
            after_check = Decision("black", f"black-after-check/{black_card}",
                                   (("check", Terminal(sign)), ("bet", after_check_bet)))
            deals.append((Q(1, 6), Decision("red", f"red-first/{red_card}", (("bet", after_bet), ("check", after_check)))))
        root = Chance(tuple(deals))
        complete = pure_matrix(root)
        self.assertEqual((len(complete), len(complete[0])), (64, 64))
        result = solve_sequence_game(build_sequence_game(root))
        self.assertEqual(result.value, solve_matrix(complete).value)
        self.assertEqual(result.value, -Q(1, 18))

    def test_blind_matching_has_mixed_half_and_revealed_reply_has_zero(self):
        model = build_sequence_game(matching())
        solution = solve_sequence_game(model)
        self.assertEqual(solution.value, Q(1, 2))
        self.assertEqual(solution.red, (Q(1), Q(1, 2), Q(1, 2)))
        self.assertEqual(solution.black, (Q(1), Q(1, 2), Q(1, 2)))
        self.assertTrue(verify_sequence_solution(model, solution))
        self.assertEqual(solve_sequence_game(build_sequence_game(matching(observed=True))).value, 0)

    def test_hidden_chance_types_share_red_decision_until_information_is_observed(self):
        def tree(reveal):
            return Chance(tuple((Q(1, 2), Decision("red", str(h) if reveal else "same-observation",
                          tuple((str(a), Terminal(int(a == h))) for a in range(2)))) for h in range(2)))
        self.assertEqual(solve_sequence_game(build_sequence_game(tree(False))).value, Q(1, 2))
        self.assertEqual(solve_sequence_game(build_sequence_game(tree(True))).value, 1)

    def test_ten_seeds_multistage_hidden_world_games_match_full_normal_form(self):
        for seed in range(10):
            rng = random.Random(seed)
            outcomes = []
            for h, mass in enumerate((Q(2, 5), Q(3, 5))):
                root_actions = []
                for a in range(2):
                    black_actions = []
                    for b in range(2):
                        red = Decision("red", f"red-after-{a}-{b}", tuple((str(c), Terminal(Q(rng.randrange(-4, 6), 3)))
                                                                                 for c in range(2)))
                        black_actions.append((str(b), red))
                    root_actions.append((str(a), Decision("black", f"black-{h}-{a}", tuple(black_actions))))
                outcomes.append((mass, Decision("red", "red-root", tuple(root_actions))))
            tree = Chance(tuple(outcomes))
            model = build_sequence_game(tree)
            expected = solve_matrix(pure_matrix(tree)).value
            solved = solve_sequence_game(model)
            self.assertEqual(solved.value, expected, seed)
            self.assertTrue(verify_sequence_solution(model, solved))
            self.assertLess(len(model.red.sequences), len(pure_matrix(tree)))

    def test_chance_only_and_one_sided_games_allow_negative_values(self):
        for root, expected in ((Terminal(-3), -3), (Chance(((Q(1, 3), Terminal(2)), (Q(2, 3), Terminal(-1)))), 0),
                               (Decision("red", "r", (("a", Terminal(-1)), ("b", Terminal(3)))), 3),
                               (Decision("black", "b", (("a", Terminal(-2)), ("b", Terminal(1)))), -2)):
            self.assertEqual(solve_sequence_game(build_sequence_game(root)).value, expected)

    def test_perfect_recall_and_consistent_action_domains_are_enforced(self):
        forget = Decision("red", "first", tuple((a, Decision("red", "forgot", (("x", Terminal(0)),))) for a in ("a", "b")))
        mismatch = Chance(((Q(1, 2), Decision("red", "same", (("x", Terminal(0)),))),
                           (Q(1, 2), Decision("red", "same", (("y", Terminal(0)),)))))
        for root in (forget, mismatch):
            with self.assertRaises(ValueError):
                build_sequence_game(root)
        reorder = Chance(((Q(1, 2), Decision("red", "same", (("x", Terminal(0)), ("y", Terminal(1))))),
                          (Q(1, 2), Decision("red", "same", (("y", Terminal(1)), ("x", Terminal(0)))))))
        self.assertEqual(solve_sequence_game(build_sequence_game(reorder)).value, 1)

    def test_certificate_rejects_forged_flows_values_and_dual_prices(self):
        model = build_sequence_game(matching())
        solved = solve_sequence_game(model)
        for bad in (replace(solved, value=Q(1)), replace(solved, red=(Q(1), Q(1), Q(0))),
                    replace(solved, black=(Q(1), Q(0), Q(1))), replace(solved, red_upper_potential=(Q(0), Q(0))),
                    replace(solved, black_lower_potential=(Q(99), Q(99))), replace(solved, shift=Q(99)),
                    replace(solved, numeric_error_bound=Q(1, 100))):
            with self.assertRaises(ValueError):
                verify_sequence_solution(model, bad)

    def test_behavioral_policy_normalizes_every_information_set_including_unreachable(self):
        root = Decision("red", "root", (("safe", Terminal(1)), ("unused", Decision("red", "unreachable",
                                        (("x", Terminal(0)), ("y", Terminal(0)))))))
        model = build_sequence_game(root)
        solved = solve_sequence_game(model)
        policy = dict(behavioral_policy(model.red, solved.red))
        self.assertEqual(dict(policy["root"]), {"safe": 1, "unused": 0})
        self.assertEqual(dict(policy["unreachable"]), {"x": Q(1, 2), "y": Q(1, 2)})

    def test_invalid_trees_budgets_and_limits_do_not_return_partial_certificates(self):
        roots = (Chance(()), Chance(((0, Terminal(0)), (1, Terminal(1)))), Chance(((Q(1, 2), Terminal(0)),)),
                 Decision("other", "i", (("a", Terminal(0)),)), Decision("red", "", (("a", Terminal(0)),)),
                 Decision("red", "i", (("a", Terminal(0)), ("a", Terminal(1)))), Terminal(True), object())
        for root in roots:
            with self.assertRaises(ValueError):
                build_sequence_game(root)
        for options in (dict(node_limit=1), dict(max_depth=1), dict(cell_limit=1), dict(deadline=perf_counter()-1)):
            with self.assertRaises(MatrixLimit):
                build_sequence_game(matching(), **options)
        model = build_sequence_game(matching())
        for options in (dict(pivot_limit=1), dict(lp_cell_limit=1), dict(deadline=perf_counter()-1)):
            with self.assertRaises(MatrixLimit):
                solve_sequence_game(model, **options)


if __name__ == "__main__":
    unittest.main()
