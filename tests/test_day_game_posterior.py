"""Original joint posterior mass, witness conditioning, and root reconstruction."""

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as Q
from itertools import product
import random
import unittest
from unittest.mock import patch

from benchmarks.ai_exact_day import load_root
from tests.test_belief_matrix import witness
from tests.test_day_game import root
from tragedy_sim.belief import FactorizedBeliefState, HiddenWorldHypothesis, PublicEvidence
from tragedy_sim.belief_culprit_posterior import JointCulpritPosterior
from tragedy_sim.belief_role_solver import enumerate_role_worlds
from tragedy_sim.day_game import posterior as module
from tragedy_sim.day_game.posterior import (PosteriorUnavailable, PublicWorldPosterior, _ordered_culprits,
                                           reconstruct_public_roots)
from tragedy_sim.witness import FsbtxWitnessMatcher, WitnessStrength


def constrained_view(unknown=("girl", "worker"), *, known_culprits=False, midgame=False):
    game = root(actual_cast=True) if midgame else load_root("official-fs-01-first-script")
    view = game.protagonist_team_view()
    # Test-only received information: source API receives this authorized view,
    # not the Game used to construct a reproducible fixture.
    view["known_roles"] = {cid: {"role": role} for cid, role in game.roles.items() if cid not in unknown}
    view["known_plots"] = [game.scenario["main_plot"], *game.scenario["subplots"]]
    if known_culprits:
        view["known_culprits"] = {str(i["day"]): i["culprit"] for i in game.scenario["incidents"]}
    return view


def signature(world):
    return world.main_plot, tuple(sorted(world.subplots)), world.roles, tuple((d, cid) for d, _, _, cid in world.incidents)


class OrderedCulpritTests(unittest.TestCase):
    def test_lazy_suffix_order_matches_independent_weighted_repeat_enumeration(self):
        for seed in range(10):
            rng = random.Random(seed)
            schedule = ((1, "serial_murder"), (2, "suicide"), (3, "serial_murder"))
            domains = {day: ("girl", "doctor", "maiden") for day, _ in schedule}
            weights = {day: {cid: Q(rng.randrange(1, 6)) for cid in domains[day]} for day, _ in schedule}
            expected = {}
            for choices in product(*(domains[day] for day, _ in schedule)):
                kinds = {}
                for (_, kind), cid in zip(schedule, choices):
                    kinds.setdefault(cid, []).append(kind)
                if any(len(row) > 1 and any(k != "serial_murder" for k in row) for row in kinds.values()):
                    continue
                mass = Q(1)
                for (day, _), cid in zip(schedule, choices):
                    mass *= weights[day][cid]
                expected[choices] = mass
            total = sum(expected.values())
            expected = {choices: mass/total for choices, mass in expected.items()}
            actual = tuple(_ordered_culprits(JointCulpritPosterior(schedule, domains, weights)))
            self.assertEqual(dict(actual), expected)
            self.assertEqual([p for _, p in actual], sorted(expected.values(), reverse=True))
        self.assertEqual(tuple(_ordered_culprits(JointCulpritPosterior((), {}, {}))), (((), Q(1)),))


class PublicPosteriorTests(unittest.TestCase):
    def test_unconditioned_fs_prefix_has_original_mass_and_full_support_count(self):
        view = load_root("official-fs-01-first-script").protagonist_team_view()
        source = PublicWorldPosterior(view)
        selected = source.select(5)
        self.assertEqual((selected.role_support, selected.culprit_support, selected.joint_support), (5430, 30, 162900))
        self.assertEqual(selected.selected_mass, Q(1, 1620))
        self.assertEqual(selected.missing_mass, 1-Q(1, 1620))
        self.assertEqual(selected.status, "partial")
        self.assertEqual(len({signature(w.hypothesis) for w in selected.worlds}), 5)
        self.assertTrue(all(w.mass == Q(1, 8100) for w in selected.worlds))

    def test_complete_constrained_posterior_matches_independent_factor_product(self):
        view = constrained_view()
        facts = (witness("role_is", "girl", "key", WitnessStrength.SOFT),
                 witness("culprit_is", "2", "worker", WitnessStrength.SOFT))
        source = PublicWorldPosterior(view, witnesses=facts)
        selected = source.select(1000)
        evidence, matcher = PublicEvidence.from_view(view), FsbtxWitnessMatcher()
        role_facts = FactorizedBeliefState._role_witnesses(facts)
        roles = tuple(enumerate_role_worlds(evidence, role_facts))
        role_weights = tuple(source.roles.target.rational_weight(w, role_facts) for w in roles)
        expected = {}
        incident_rows = {}
        for pair in product(evidence.characters, repeat=2):
            if pair[0] == pair[1]:
                continue
            weight = Q(1)
            for (day, kind), cid in zip(evidence.schedule, pair):
                candidate = HiddenWorldHypothesis("ref", "", (), (), ((day, kind, kind, cid),))
                weight *= Q(str(2.0**matcher.soft_score(candidate, facts[1:])))
            incident_rows[pair] = weight
        for role, r_weight in zip(roles, role_weights):
            for pair, c_weight in incident_rows.items():
                world = replace(role, incidents=tuple((day, kind, kind, cid)
                                for (day, kind), cid in zip(evidence.schedule, pair)))
                expected[signature(world)] = r_weight/sum(role_weights)*c_weight/sum(incident_rows.values())
        self.assertEqual({signature(w.hypothesis): w.mass for w in selected.worlds}, expected)
        self.assertEqual(selected.selected_mass, 1)
        self.assertEqual(selected.status, "complete")
        self.assertEqual([w.mass for w in selected.worlds], sorted(expected.values(), reverse=True))
        prefix = source.select(4)
        self.assertEqual(prefix.worlds, selected.worlds[:4])
        self.assertNotEqual(prefix.selected_mass, 1)

    def test_hard_role_and_incident_witnesses_condition_both_dimensions(self):
        facts = (witness("role_is", "girl", "key"), witness("culprit_is", "2", "worker"))
        selected = PublicWorldPosterior(constrained_view(), witnesses=facts).select(100)
        self.assertEqual((selected.role_support, selected.culprit_support), (1, 5))
        self.assertEqual(selected.selected_mass, 1)
        self.assertTrue(all(dict(w.hypothesis.roles)["girl"] == "key" for w in selected.worlds))
        self.assertTrue(all(w.hypothesis.incidents[0][3] == "worker" for w in selected.worlds))
        self.assertTrue(all(w.hypothesis.incidents[1][3] != "worker" for w in selected.worlds))

    def test_complete_role_support_does_not_mark_joint_prefix_complete(self):
        selected = PublicWorldPosterior(constrained_view(unknown=())).select(3)
        self.assertEqual((selected.role_support, selected.culprit_support), (1, 30))
        self.assertEqual(selected.selected_mass, Q(1, 10))
        self.assertEqual(selected.status, "partial")
        self.assertEqual(len(selected.worlds), 3)

    def test_equal_mass_prefix_spans_both_factors_without_changing_mass(self):
        source = PublicWorldPosterior(constrained_view(), witnesses=())
        selected = source.select(3)
        self.assertEqual(len({w.hypothesis.roles for w in selected.worlds}), 2)
        self.assertEqual(len({w.hypothesis.incidents for w in selected.worlds}), 2)
        self.assertEqual(selected.selected_mass, Q(3, 60))

    def test_unclassified_or_contradictory_facts_fail_without_truncated_normalization(self):
        for facts in ((witness("future_unknown", "x", {}),),
                      (witness("culprit_is", "2", "doctor"), witness("culprit_is", "3", "doctor"))):
            with self.assertRaises(PosteriorUnavailable):
                PublicWorldPosterior(constrained_view(), witnesses=facts)
        with self.assertRaises(PosteriorUnavailable):
            PublicWorldPosterior(load_root("official-fs-01-first-script").protagonist_team_view(), node_limit=1)
        for limit in (0, True, 1.2):
            with self.assertRaises(ValueError):
                PublicWorldPosterior(constrained_view()).select(limit)

    def test_exact_rational_prior_matches_existing_numeric_target(self):
        source = PublicWorldPosterior(constrained_view(), witnesses=(witness("role_is", "girl", "key", WitnessStrength.SOFT),))
        for world in enumerate_role_worlds(source.evidence):
            self.assertAlmostEqual(float(source.roles.target.rational_weight(world, source.roles.role_witnesses)),
                                   source.roles.target.weight(world, source.roles.role_witnesses), places=15)


class PublicRootReconstructionTests(unittest.TestCase):
    def test_fresh_roots_replay_unique_setup_and_preserve_original_prefix_mass(self):
        view = constrained_view(unknown=())
        selection = PublicWorldPosterior(view).select(3)
        roots = reconstruct_public_roots(selection, view)
        self.assertEqual(len(roots.roots), 3)
        self.assertEqual((roots.failed_mass, roots.approximated_state_mass), (0, 0))
        self.assertEqual(tuple(roots.roots[0][2].state.characters), tuple(view["characters"]))
        self.assertEqual(roots.model().covered_mass, Q(1, 10))
        self.assertFalse(roots.model().belief_domain_complete)

    def test_all_joint_worlds_known_and_exact_startup_can_assert_model_coverage(self):
        view = constrained_view(unknown=(), known_culprits=True)
        selection = PublicWorldPosterior(view).select(10)
        self.assertEqual(selection.joint_support, 1)
        roots = reconstruct_public_roots(selection, view)
        self.assertTrue(roots.model().belief_domain_complete)
        self.assertEqual(roots.model().covered_mass, 1)

    def test_failed_reconstruction_mass_remains_unknown_without_retry_renormalization(self):
        view = constrained_view(unknown=())
        selection = PublicWorldPosterior(view).select(30)
        original = module._initial_root
        calls = 0

        def reject_one(*args):
            nonlocal calls
            calls += 1
            return (None, "unit_failure") if calls == 1 else original(*args)

        with patch.object(module, "_initial_root", side_effect=reject_one):
            roots = reconstruct_public_roots(selection, view, allow_state_prior=False)
        self.assertEqual(roots.failed_mass, Q(1, 30))
        self.assertEqual(roots.model().covered_mass, Q(29, 30))
        self.assertEqual(roots.model().missing_mass, Q(1, 30))
        self.assertFalse(roots.model().belief_domain_complete)

    def test_midgame_prior_restores_received_answers_and_own_memory_but_is_not_complete(self):
        view = constrained_view(unknown=(), known_culprits=True, midgame=True)
        view["protagonist_knowledge"] = {"roles": {"girl": "key"}, "initial_roles": {"girl": "key"}}
        selection = PublicWorldPosterior(view).select(10)
        commands = (dict(actor="a", action="goodwill", character="girl", ability="unit-memory"),)
        roots = reconstruct_public_roots(selection, view, own_commands=commands)
        self.assertEqual(roots.failed_mass, 0, roots.failures)
        self.assertEqual(roots.approximated_state_mass, 1)
        world = roots.roots[0][2]
        self.assertEqual(world.protagonist_knowledge, view["protagonist_knowledge"])
        self.assertEqual(world.history, list(commands))
        self.assertEqual(tuple(world.state.characters), tuple(view["characters"]))
        self.assertFalse(roots.model().belief_domain_complete)
        self.assertIn("hidden-state-prior", roots.model().scope)
        refused = reconstruct_public_roots(selection, view, allow_state_prior=False)
        self.assertEqual(refused.failed_mass, 1)
        with self.assertRaises(PosteriorUnavailable):
            refused.model()

    def test_nonteam_private_views_and_other_seats_commands_are_rejected(self):
        view = constrained_view(unknown=(), known_culprits=True)
        selection = PublicWorldPosterior(view).select(10)
        for patch_data in ({"viewer": "m"}, {"secret": {}}, {"team_hands": {}}):
            bad = deepcopy(view)
            bad.update(patch_data)
            with self.assertRaises(ValueError):
                reconstruct_public_roots(selection, bad)
        with self.assertRaises(ValueError):
            reconstruct_public_roots(selection, view, own_commands=({"actor": "m", "action": "pass"},))
        changed = deepcopy(view)
        changed["characters"]["girl"]["goodwill"] += 1
        with self.assertRaises(ValueError):
            reconstruct_public_roots(selection, changed)


if __name__ == "__main__":
    unittest.main()
