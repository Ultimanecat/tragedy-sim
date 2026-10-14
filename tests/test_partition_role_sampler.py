"""Independent enumeration, integer ranks and explicit posterior densities."""

from collections import Counter
from copy import deepcopy
from dataclasses import replace
from math import fsum
import random
import unittest
from unittest.mock import patch

from tragedy_sim.belief import FactorizedBeliefState
from tragedy_sim.belief_matrix_sampler import MatrixWorldSampler
from tragedy_sim.belief_partition_sampler import PartitionRoleSampler, _unrank_cast
from tragedy_sim.belief_posterior import RoleImportancePool, RolePosteriorTarget
from tragedy_sim.witness import FsbtxWitnessMatcher, PublicWitness, WitnessStrength
from tests.test_belief_posterior import evidence, enumerate_printed
from tests.test_role_support_solver import independent_extra_casts


class PartitionRoleSamplerTests(unittest.TestCase):
    def assert_independent_density(self, setup, facts=()):
        initial = replace(setup, known_roles=(), known_initial_roles=(), known_plots=(), known_culprits=())
        worlds = (independent_extra_casts(initial) if {"copycat", "irregular"} & set(initial.characters)
                  else enumerate_printed(initial))
        target = RolePosteriorTarget(setup)
        weights = [(world, target.weight(world, facts)) for world in worlds]
        total = fsum(weight for _, weight in weights)
        sampler = PartitionRoleSampler(setup, facts)
        self.assertTrue(sampler.partition.exact, sampler.diagnostics())
        self.assertAlmostEqual(sampler.partition.total_mass, total, places=11)
        for world, weight in weights:
            self.assertAlmostEqual(sampler.partition.role_probability_for(world), weight / total, places=12)
        # Each integer completion appears exactly once, across all partitions.
        actual = []
        for group in sampler.partition._groups:
            casts = [_unrank_cast(group, split=sampler.partition._split, rank=i)
                     for i in range(group.completions)]
            self.assertEqual(len(set(casts)), group.completions)
            self.assertTrue(all(group.contains(dict(cast)) for cast in casts))
            actual.extend(casts)
        expected = {world.roles for world, weight in weights if weight}
        self.assertEqual(len(actual), len(expected))
        self.assertEqual(set(actual), expected)
        self.assertAlmostEqual(fsum(sampler.partition.role_probability_for(world)
                                   for world, _ in weights), 1, places=12)
        return sampler

    def test_unranking_and_joint_density_equal_full_printed_enumeration(self):
        for module in ("FS", "BTX"):
            setup = evidence(module)
            soft = PublicWitness("role_pressure", "brain", {"candidates": ["girl", "doctor"]},
                                 1, 1, "incident", "test", WitnessStrength.SOFT)
            hard = PublicWitness("role_not_in", "maiden", ["brain"], 1, 1, "incident", "test")
            with self.subTest(module=module):
                sampler = self.assert_independent_density(setup, (hard, soft, soft))
                rng = random.Random(12)
                proposals = sampler.propose_roles(100, rng=rng)
                for proposal in proposals:
                    self.assertEqual(proposal.policy, "exact_partition")
                    self.assertEqual(proposal.density, sampler.partition.role_probability_for(proposal.world))
                pool = RoleImportancePool(proposals)
                diag = pool.diagnostics(sampler.target, sampler.role_witnesses)
                self.assertAlmostEqual(diag["effective_sample_size"], 100, places=10)

    def test_extra_identities_and_friend_genders_are_not_lost(self):
        for module, extra in (("FS", "copycat"), ("BTX", "irregular")):
            setup = replace(evidence(module), characters=(*evidence(module).characters, extra))
            facts = (PublicWitness("role_pressure", "friend", {"candidates": [extra, "girl"]},
                                   1, 1, "test", "test", WitnessStrength.SOFT),)
            with self.subTest(module=module, extra=extra):
                sampler = self.assert_independent_density(setup, facts)
                self.assertEqual(len(sampler.propose_roles(100, rng=random.Random(2))), 100)

    def test_current_initial_virus_and_disjunctive_routes(self):
        setup = replace(evidence("BTX"), known_roles=(("girl", "serial"),), known_plots=("virus",))
        fact = PublicWitness("mandatory_serial_route", "death", {
            "serial": ["doctor"], "virus_ordinary": ["maiden"]}, 1, 1, "day_end", "test", WitnessStrength.SOFT)
        sampler = self.assert_independent_density(setup, (fact,))
        draws = sampler.propose_roles(500, rng=random.Random(5))
        self.assertEqual({dict(p.world.roles)["girl"] for p in draws}, {"ordinary", "serial"})
        initial = replace(setup, known_initial_roles=(("girl", "ordinary"),))
        known = self.assert_independent_density(initial, (fact,))
        self.assertTrue(all(dict(p.world.roles)["girl"] == "ordinary"
                            for p in known.propose_roles(50, rng=random.Random(1))))

    def test_draws_follow_weights_keep_duplicates_and_reach_non_representatives(self):
        setup = replace(evidence(), characters=(*evidence().characters, "worker"),
                        known_plots=("avenger", "hideous"))
        facts = (PublicWitness("role_pressure", "friend", {"candidates": ["girl"]},
                               1, 1, "test", "test", WitnessStrength.SOFT),)
        sampler = PartitionRoleSampler(setup, facts)
        draws = sampler.propose_roles(4000, rng=random.Random(19))
        self.assertEqual(len(draws), 4000)
        counts = Counter(p.world.roles for p in draws)
        representatives = {group.representative for group in sampler.partition._groups}
        self.assertTrue(set(counts) - representatives)
        self.assertLess(len(counts), len(draws))
        expected = fsum(group.completions * group.per_cast_mass / sampler.partition.total_mass
                        for group in sampler.partition._groups
                        if dict(group.representative)["girl"] == "friend")
        actual = sum(dict(p.world.roles)["girl"] == "friend" for p in draws) / len(draws)
        self.assertLess(abs(actual - expected), 0.025)

    def test_partition_failures_and_bad_limits_cannot_draw_partial_results(self):
        setup = evidence()
        unknown = PublicWitness("unknown_cross_factor", "girl", {}, 1, 1, "test", "test")
        for sampler, status in ((PartitionRoleSampler(setup, node_limit=1), "work_limit"),
                                (PartitionRoleSampler(setup, (unknown,)), "unsupported_witness"),
                                (PartitionRoleSampler(replace(setup, module="MZ")), "unsupported_module")):
            with self.subTest(status=status):
                rng = random.Random(3)
                before = rng.getstate()
                self.assertEqual(sampler.partition.status, status)
                self.assertEqual(sampler.propose_roles(2, rng=rng), ())
                self.assertEqual(rng.getstate(), before)
        for count in (0, -1, True, "2"):
            with self.subTest(count=count), self.assertRaises(ValueError):
                PartitionRoleSampler(setup).propose_roles(count, rng=random.Random(1))

    def test_cache_switch_rng_repeatability_and_evidence_immutability(self):
        setup = evidence("BTX")
        fact = PublicWitness("role_pressure", "brain", {"candidates": ["doctor"]},
                             1, 1, "test", "test", WitnessStrength.SOFT)
        sampler = PartitionRoleSampler(setup, (fact,))
        before = deepcopy(sampler.partition.to_dict())
        def uncached(characters, domains, counts, split, genders):
            return FactorizedBeliefState._assignment_count(
                characters, dict(domains), Counter(dict(counts)),
                friend_gender_split=split, used_friend_genders=genders)
        rng_a, rng_b = random.Random(21), random.Random(21)
        with patch("tragedy_sim.belief_partition_sampler._completion_count_cached", side_effect=uncached):
            a = sampler.propose_roles(50, rng=rng_a)
        b = sampler.propose_roles(50, rng=rng_b)
        self.assertEqual(a, b)
        self.assertEqual(rng_a.getstate(), rng_b.getstate())
        fact.value["candidates"].append("girl")
        self.assertEqual(sampler.witnesses[0].value["candidates"], ["doctor"])
        self.assertEqual(sampler.partition.to_dict(), before)
        self.assertEqual(sampler.diagnostics()["draws"], 100)
        group = sampler.partition._groups[0]
        for rank in (-1, group.completions, True):
            with self.subTest(rank=rank), self.assertRaises(ValueError):
                _unrank_cast(group, split=sampler.partition._split, rank=rank)

    def test_action_worlds_are_fresh_not_resampled_from_diagnostic_pool(self):
        setup = replace(evidence(), days=2, schedule=((1, "suicide"), (2, "hospital")),
                        known_culprits=((2, "doctor"),))
        fact = PublicWitness("culprit_is", "1", "girl", 1, 1, "incident", "test")
        state = FactorizedBeliefState(capacity=1, matrix_proposals=True, joint_culprits=True,
                                      role_sampling_policy="exact_partition")
        result = state.sample(setup, (fact,), 100, rng=random.Random(17))
        self.assertEqual(len(result.worlds), 100)
        self.assertEqual(len(state._roles), 1)
        self.assertTrue({state._key(world) for world in result.worlds} - state._roles.keys())
        for world in result.worlds:
            self.assertTrue(FsbtxWitnessMatcher().matches(world, (fact,)))
            self.assertEqual([row[3] for row in world.incidents], ["girl", "doctor"])
            world.materialize(setup)
        diag = state.proposal_summary()
        self.assertEqual(diag["role_partition"]["draws"], 101)
        self.assertIsNone(diag["role_partition_fallback"])
        self.assertEqual(diag["importance"]["effective_sample_size"], 1)
        with patch("tragedy_sim.belief_partition_sampler.JointGuessProbabilitySolver.solve",
                   side_effect=AssertionError("same public partition should be reused")):
            state.role_posterior(setup, (fact,))

    def test_work_limit_fallback_preserves_default_batch_density_and_rng(self):
        from tragedy_sim import Game
        from tragedy_sim.belief import PublicEvidence
        from tragedy_sim.scenario_library import ScenarioLibrary
        setup = PublicEvidence.from_view(Game(ScenarioLibrary().get(
            "official-btx-06-secret-that-was-kept")).protagonist_team_view())
        baseline = FactorizedBeliefState(seed=13, matrix_proposals=True)
        experimental = FactorizedBeliefState(seed=13, matrix_proposals=True,
                                             role_sampling_policy="exact_partition",
                                             role_partition_node_limit=1)
        before = experimental.partition_rng.getstate()
        a, b = (state.role_posterior(setup, ()) for state in (baseline, experimental))
        self.assertEqual(a, b)
        self.assertEqual(baseline.matrix_rng.getstate(), experimental.matrix_rng.getstate())
        self.assertEqual(experimental.partition_rng.getstate(), before)
        self.assertEqual(experimental.proposal_summary()["role_partition_fallback"], "work_limit")

    def test_proven_empty_support_never_falls_back_to_a_nonempty_proposal(self):
        setup = replace(evidence(), known_initial_roles=(("girl", "brain"), ("doctor", "brain")))
        state = FactorizedBeliefState(matrix_proposals=True, role_sampling_policy="exact_partition")
        with patch.object(MatrixWorldSampler, "propose_roles", side_effect=AssertionError("empty is proven")):
            self.assertEqual(state.role_posterior(setup, ()), ())
        self.assertEqual(state.proposal_summary()["role_partition"]["partition"]["status"], "no_compatible_worlds")

    def test_explicit_default_keeps_action_and_all_sampling_rng_states(self):
        from benchmarks.ai_self_play import _policy_offer
        from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
        from tragedy_sim.search import SearchBudget
        from tests.test_particle_ensemble import protagonist_position
        game = protagonist_position()
        offers = [_policy_offer(game, action) for action in game.action_offers(game.controller)]
        choices, states = [], []
        for options in ({}, {"role_sampling_policy": "importance"}):
            policy = ParticleEnsembleProtagonistAgent(SearchBudget(node_limit=2, seed=2),
                                                       particle_count=2, rng_seed=2, **options)
            chosen = policy.choose_action(participant="team", view=deepcopy(game.protagonist_team_view()), offers=offers)
            choices.append(policy.decision_for_action(chosen))
            belief = policy.factorized_belief
            states.append((belief.rng.getstate(), belief.matrix_rng.getstate(), belief.partition_rng.getstate()))
        self.assertEqual(choices[0], choices[1])
        self.assertEqual(states[0], states[1])

    def test_invalid_policy_and_cli_forwarding(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from benchmarks import ai_self_play, ai_mastermind_matrix
        from benchmarks.ai_self_play import MatchResult
        from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
        for options in ({"role_sampling_policy": "unknown"}, {"role_partition_node_limit": True},
                        {"role_partition_node_limit": 0},
                        {"role_sampling_policy": "exact_partition", "matrix_proposals": False}):
            for constructor in (FactorizedBeliefState, ParticleEnsembleProtagonistAgent):
                with self.subTest(options=options, constructor=constructor), self.assertRaises(ValueError):
                    constructor(**options)
        with self.assertRaises(ValueError):
            ai_self_play.play("unused", 0, 1, 1, "fixed", "oracle_script",
                              role_sampling_policy="exact_partition", matrix_proposals=True)
        for module in (ai_self_play, ai_mastermind_matrix):
            argv = [module.__name__, "--scenario", "unused", "--games", "1", "--protagonists", "particle_ensemble",
                    "--role-sampling-policy", "exact_partition", "--role-partition-node-limit", "20"]
            if module is ai_self_play:
                argv.extend(["--strategy", "fixed"])
            def fake_play(*args, **kwargs):
                self.assertEqual(kwargs["role_sampling_policy"], "exact_partition")
                self.assertEqual(kwargs["role_partition_node_limit"], 20)
                return MatchResult("unused", "test", "BTX", 1, "standard", "fixed",
                                   "particle_ensemble", 0, "mastermind", 1, 1, 0, 0.0)
            with (patch("sys.argv", argv), patch.object(module, "play", side_effect=fake_play),
                  redirect_stdout(StringIO())):
                module.main()

    def test_fair_experimental_day_plan_materializes_and_executes_three_legal_cards(self):
        from benchmarks.ai_self_play import _policy_offer
        from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
        from tragedy_sim.search import SearchBudget
        from tests.test_particle_ensemble import protagonist_position
        game = protagonist_position()
        before = deepcopy(game.protagonist_team_view())
        policy = ParticleEnsembleProtagonistAgent(SearchBudget(node_limit=2, seed=5),
                                                  particle_count=3, rng_seed=5,
                                                  role_sampling_policy="exact_partition")
        offers = [_policy_offer(game, action) for action in game.action_offers(game.controller)]
        chosen = policy.choose_action(participant="team", view=deepcopy(before), offers=offers)
        decision = policy.decision_for_action(chosen)
        self.assertEqual(game.protagonist_team_view(), before)
        self.assertEqual(len(decision.card_plan), 3)
        self.assertIsNone(policy.last_trace.fallback)
        self.assertTrue(policy.factorized_belief.proposal_summary()["role_partition"]["partition"]["exact"])
        for play in decision.card_plan:
            game.dispatch(play.actor, "play", card=play.card, target=play.target)
        self.assertEqual(game.state.phase, "reveal")


if __name__ == "__main__":
    unittest.main()
