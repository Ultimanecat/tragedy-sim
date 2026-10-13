from collections import Counter, defaultdict
from dataclasses import replace
from math import lcm
import random
import unittest
from unittest.mock import patch

from tragedy_sim import Game
from tragedy_sim.belief import FactorizedBeliefState, HiddenWorldHypothesis, PublicEvidence
from tragedy_sim.belief_matrix_sampler import (
    MatrixWorldSampler, RoleProposal, role_incident_placeholders,
)
from tragedy_sim.belief_posterior import RoleImportancePool, RolePosteriorTarget
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.witness import FsbtxWitnessMatcher, PublicWitness, WitnessStrength
from tests.test_belief_posterior import enumerate_printed, evidence


class RoleImportanceTests(unittest.TestCase):
    def optional_space(self):
        setup = replace(evidence(), characters=(*evidence().characters, "worker"),
                        known_plots=("avenger", "hideous"))
        worlds = enumerate_printed(setup)
        groups = defaultdict(list)
        for world in worlds:
            groups[tuple(sorted(Counter(dict(world.roles).values()).items()))].append(world)
        self.assertEqual(len(groups), 3)
        return setup, worlds, groups

    def test_quadrature_corrects_unequal_optional_count_proposals(self):
        setup, worlds, groups = self.optional_space()
        common = len(groups) * lcm(*(len(group) for group in groups.values()))
        proposals = []
        for group in groups.values():
            q = 1.0 / (len(groups) * len(group))
            for world in group:
                proposals.extend([RoleProposal(world, q)] * (common // (len(groups) * len(group))))
        target = RolePosteriorTarget(setup)
        soft = PublicWitness("role_pressure", "brain", {"candidates": ["girl"]},
                             1, 1, "day_end", "test", WitnessStrength.SOFT)
        pool = RoleImportancePool(proposals)
        posterior = pool.posterior(target, (soft,))
        actual = {FactorizedBeliefState._key(w): weight for w, weight in posterior}
        expected = {FactorizedBeliefState._key(w): target.weight(w, (soft,)) for w in worlds}
        total, reference_total = sum(actual.values()), sum(expected.values())
        self.assertEqual(actual.keys(), expected.keys())
        for key in expected:
            self.assertAlmostEqual(actual[key] / total, expected[key] / reference_total, places=12)
        # Fresh scoring does not compound evidence or rewrite proposal q.
        self.assertEqual(posterior, pool.posterior(target, (soft,)))

    def test_proposer_keeps_duplicates_and_reports_correct_density(self):
        setup, worlds, groups = self.optional_space()
        size_by_counts = {key: len(group) for key, group in groups.items()}
        draws = MatrixWorldSampler().propose_roles(
            setup, (), 3000, rng=random.Random(13), variant_policy="uniform")
        self.assertEqual(len(draws), 3000)
        self.assertLess(len({FactorizedBeliefState._key(p.world) for p in draws}), len(draws))
        for proposal in draws:
            counts = tuple(sorted(Counter(dict(proposal.world.roles).values()).items()))
            self.assertAlmostEqual(proposal.density, 1.0 / (len(groups) * size_by_counts[counts]))
            proposal.world.materialize(setup)
        posterior = RoleImportancePool(draws).posterior(RolePosteriorTarget(setup), ())
        total = sum(weight for _, weight in posterior)
        group_mass = Counter()
        for world, weight in posterior:
            self.assertLess(abs(weight / total - 1.0 / len(worlds)), 0.015)
            group_mass[tuple(sorted(Counter(dict(world.roles).values()).items()))] += weight / total
        for counts, size in size_by_counts.items():
            self.assertLess(abs(group_mass[counts] - size / len(worlds)), 0.03)

    def test_placeholder_schedule_reserves_later_known_culprits(self):
        setup = replace(evidence(), schedule=((1, "suicide"), (2, "hospital")),
                        known_culprits=((2, "doctor"),))
        rows = role_incident_placeholders(setup)
        self.assertNotEqual(rows[0][2], "doctor")
        self.assertEqual(rows[1][2], "doctor")
        impossible = replace(setup, known_culprits=((1, "doctor"), (2, "doctor")))
        self.assertIsNone(role_incident_placeholders(impossible))
        serial = replace(setup, schedule=((1, "serial_murder"), (2, "serial_murder")),
                         known_culprits=((1, "doctor"), (2, "doctor")))
        self.assertEqual([row[2] for row in role_incident_placeholders(serial)], ["doctor", "doctor"])
        replacement = replace(setup, characters=(*setup.characters, "part_timer"),
                              known_culprits=((2, "part_timer_question"),))
        self.assertEqual(role_incident_placeholders(replacement)[1][2], "part_timer")

    def test_proposer_requires_full_matcher_and_does_not_relax_hard_counts(self):
        setup, _, _ = self.optional_space()
        with patch("tragedy_sim.belief_matrix_sampler.FsbtxWitnessMatcher.matches", return_value=False):
            self.assertEqual(MatrixWorldSampler().propose_roles(
                setup, (), 4, rng=random.Random(1), max_attempts=8), ())
        facts = tuple(PublicWitness("role_is", cid, "brain", 1, 1, "query", "test")
                      for cid in ("girl", "maiden"))
        self.assertEqual(MatrixWorldSampler().propose_roles(setup, facts, 4, rng=random.Random(1)), ())

    def test_state_uses_corrected_batch_without_legacy_pool_or_rng(self):
        scenario = ScenarioLibrary().get("official-btx-06-secret-that-was-kept")
        setup = PublicEvidence.from_view(Game(scenario).protagonist_team_view())
        first = HiddenWorldHypothesis.from_scenario(scenario)
        cast = dict(first.roles)
        cast["rich"], cast["patient"] = cast["patient"], cast["rich"]
        second = replace(first, roles=tuple(sorted(cast.items())))
        second.materialize(setup)
        draws = (RoleProposal(first, 0.5), RoleProposal(first, 0.5),
                 RoleProposal(first, 0.5), RoleProposal(second, 0.25))
        state = FactorizedBeliefState(seed=11, matrix_proposals=True)
        original_rng = state.rng.getstate()
        with (patch.object(state.sampler, "sample", side_effect=AssertionError("legacy proposal called")),
              patch.object(MatrixWorldSampler, "propose_roles", return_value=draws)):
            posterior = state.role_posterior(setup, ())
        mass = sum(weight for _, weight in posterior)
        self.assertAlmostEqual(posterior[0][1] / mass, 0.6)
        self.assertAlmostEqual(posterior[1][1] / mass, 0.4)
        self.assertEqual(state.rng.getstate(), original_rng)
        summary = state.proposal_summary()
        self.assertEqual(summary["importance"]["proposal_draws"], 4)
        self.assertEqual(summary["importance"]["unique_roles"], 2)
        self.assertAlmostEqual(summary["importance"]["effective_sample_size"], 100 / 28)
        before = state.matrix_rng.getstate()
        summary["importance"]["proposal_draws"] = -1
        self.assertEqual(state.proposal_summary()["importance"]["proposal_draws"], 4)
        self.assertEqual(state.matrix_rng.getstate(), before)

    def test_invalid_density_is_rejected(self):
        world = enumerate_printed(evidence())[0]
        for q in (0, -1, float("nan"), float("inf"), 1.1):
            with self.subTest(q=q), self.assertRaises(ValueError):
                RoleImportancePool((RoleProposal(world, q),))

    def test_prior_proposals_follow_cast_mass_with_constant_importance_without_soft_evidence(self):
        setup, worlds, groups = self.optional_space()
        target = RolePosteriorTarget(setup)
        prior_draws = MatrixWorldSampler().propose_roles(
            setup, (), 3000, rng=random.Random(13), target=target)
        self.assertEqual(len(prior_draws), 3000)
        for proposal in prior_draws:
            self.assertAlmostEqual(proposal.density, 1 / len(worlds))
            self.assertEqual(proposal.policy, "prior")
        actual = Counter(tuple(sorted(Counter(dict(p.world.roles).values()).items()))
                         for p in prior_draws)
        for key, group in groups.items():
            self.assertLess(abs(actual[key] / 3000 - len(group) / len(worlds)), 0.03)
        diagnostic = RoleImportancePool(prior_draws).diagnostics(target, ())
        self.assertAlmostEqual(diagnostic["effective_sample_size"], 3000, places=8)
        uniform = MatrixWorldSampler().propose_roles(
            setup, (), 3000, rng=random.Random(13), variant_policy="uniform")
        old = RoleImportancePool(uniform).diagnostics(target, ())
        self.assertLess(old["effective_sample_size"], 2900)

    def test_prior_density_matches_independent_hard_conditioned_multiplot_target(self):
        setup = evidence("BTX")
        target = RolePosteriorTarget(setup)
        facts = (PublicWitness("role_is", "girl", "key", 1, 1, "query", "test"),)
        compatible = tuple(w for w in enumerate_printed(setup)
                           if FsbtxWitnessMatcher().matches(w, facts))
        normalizer = sum(target.weight(w, facts) for w in compatible)
        expected = {FactorizedBeliefState._key(w): target.weight(w, facts) / normalizer
                    for w in compatible}
        draws = MatrixWorldSampler().propose_roles(
            setup, facts, 2000, rng=random.Random(17), target=target)
        self.assertEqual(len(draws), 2000)
        for proposal in draws:
            self.assertAlmostEqual(proposal.density, expected[FactorizedBeliefState._key(proposal.world)],
                                   places=12)
        self.assertAlmostEqual(RoleImportancePool(draws).diagnostics(target, facts)[
            "effective_sample_size"], 2000, places=8)
        # Soft witness remains a likelihood factor; proposal q does not change.
        soft = PublicWitness("role_pressure", "brain", {"candidates": ["doctor"]},
                             1, 1, "day_end", "test", WitnessStrength.SOFT)
        soft_draws = MatrixWorldSampler().propose_roles(
            setup, (*facts, soft), 2000, rng=random.Random(17), target=target)
        self.assertEqual(draws, soft_draws)
        pool = RoleImportancePool(draws)
        masses = dict((FactorizedBeliefState._key(w), weight) for w, weight in pool.posterior(
            target, (*facts, soft)))
        direct = Counter()
        for p in draws:
            direct[FactorizedBeliefState._key(p.world)] += target.weight(p.world, (*facts, soft)) / p.density
        self.assertEqual(masses, direct)

    def test_invalid_variant_policy_is_rejected(self):
        for value in ("posterior_magic", None, True, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                MatrixWorldSampler().propose_roles(evidence(), (), 1, rng=random.Random(1),
                                                  variant_policy=value)
            with self.subTest(state=value), self.assertRaises(ValueError):
                FactorizedBeliefState(matrix_variant_policy=value)

    def test_subplot_order_does_not_change_prior_or_map_weight(self):
        scenario = ScenarioLibrary().get("official-btx-06-secret-that-was-kept")
        setup = PublicEvidence.from_view(Game(scenario).protagonist_team_view())
        target = RolePosteriorTarget(setup)
        world = HiddenWorldHypothesis.from_scenario(scenario)
        reordered = replace(world, subplots=tuple(reversed(world.subplots)))
        self.assertGreater(target.prior_weight(world), 0)
        self.assertEqual(target.weight(world, ()), target.weight(reordered, ()))
