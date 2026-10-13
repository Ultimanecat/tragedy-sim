from collections import Counter
from dataclasses import replace
from itertools import permutations
import random
import unittest
from unittest.mock import patch

from tragedy_sim.belief import (
    ConstraintBeliefSampler, FactorizedBeliefState, HiddenWorldHypothesis, PublicEvidence,
)
from tragedy_sim.belief_posterior import RolePosteriorTarget
from tragedy_sim.engine import RuleError
from tragedy_sim.scenario import validate_scenario
from tragedy_sim.witness import PublicWitness, WitnessStrength


def evidence(module="FS"):
    return PublicEvidence(module, 1, 1, True, ("doctor", "girl", "maiden", "student"),
                          (), (), (), ())


def enumerate_printed(setup):
    """Independent permutation/validator reference; no matrix DP."""
    worlds = {}
    for main, subs, slots in ConstraintBeliefSampler._plot_slot_sets(setup):
        if sum(slots.values()) > len(setup.characters):
            continue
        bag = list(slots.elements()) + ["ordinary"] * (len(setup.characters) - sum(slots.values()))
        for roles in set(permutations(bag)):
            try:
                scenario = validate_scenario({
                    "id": "prior-reference", "title": "reference", "module": setup.module,
                    "days": 1, "loops": 1, "table_talk": True,
                    "main_plot": main, "subplots": list(subs),
                    "cast": dict(zip(setup.characters, roles)), "incidents": [],
                })
            except RuleError:
                continue
            world = HiddenWorldHypothesis.from_scenario(scenario)
            worlds[FactorizedBeliefState._key(world)] = world
    return tuple(worlds.values())


class RolePosteriorTests(unittest.TestCase):
    def test_initial_sizes_match_independent_validator_enumeration(self):
        for module in ("FS", "BTX"):
            with self.subTest(module=module):
                setup = evidence(module)
                worlds = enumerate_printed(setup)
                counts = Counter((w.main_plot, w.subplots) for w in worlds)
                target = RolePosteriorTarget(setup)
                self.assertEqual(target.plot_sizes, counts)
                masses = Counter()
                for world in worlds:
                    masses[world.main_plot, world.subplots] += target.weight(world, ())
                self.assertTrue(all(abs(value - 1.0) < 1e-12 for value in masses.values()))

    def test_observations_do_not_redefine_initial_prior(self):
        setup = evidence("BTX")
        observed = replace(setup, known_roles=(("girl", "key"),),
                           known_plots=("sign",), known_culprits=((1, "girl"),))
        self.assertEqual(RolePosteriorTarget(setup).plot_sizes,
                         RolePosteriorTarget(observed).plot_sizes)

    def test_finite_and_exact_reservoirs_use_the_same_world_target(self):
        setup = evidence("BTX")
        worlds = enumerate_printed(setup)
        soft = PublicWitness("plot_pressure", "bomb", True, 1, 1,
                             "loop_end", "test", WitnessStrength.SOFT)
        state = FactorizedBeliefState(seed=1)
        state.role_posterior(setup, (soft,))
        chosen = tuple(state._roles.values())[:20]
        state._roles = {state._key(w): w for w in chosen}
        state._exact_roles = False
        with patch.object(state, "_refresh_roles"):
            finite = state.role_posterior(setup, (soft,))
            state._exact_roles = True
            exact = state.role_posterior(setup, (soft,))
        self.assertEqual(finite, exact)
        target = RolePosteriorTarget(setup)
        self.assertTrue(all(weight == target.weight(world, (soft,)) for world, weight in finite))
        solved = state.exact_role_map(setup, (soft,))
        expected = max(worlds, key=lambda world: (
            target.weight(world, (soft,)), tuple(sorted(world.roles)), world.main_plot, world.subplots))
        self.assertEqual(solved.selected.roles, expected.roles)
        self.assertEqual(solved.selected.main_plot, expected.main_plot)
        self.assertEqual(solved.selected.subplots, expected.subplots)
        self.assertEqual(solved.ranked[0][1], target.weight(expected, (soft,)))

    def test_hard_support_and_unchanged_evidence_are_idempotent(self):
        setup = evidence()
        target = RolePosteriorTarget(setup)
        world = next(w for w in enumerate_printed(setup) if dict(w.roles)["girl"] != "ordinary")
        hard = PublicWitness("role_is", "girl", "ordinary", 1, 1, "query", "test")
        self.assertEqual(target.weight(world, (hard,)), 0.0)
        plot_world = next(w for w in enumerate_printed(setup) if w.main_plot == "murder_plan")
        soft = PublicWitness("plot_pressure", "murder_plan", True, 1, 1,
                             "loop_end", "test", WitnessStrength.SOFT)
        sizes = target.plot_sizes.copy()
        expected = target.prior_weight(plot_world) * 8.0
        for _ in range(10):
            self.assertEqual(target.weight(plot_world, (soft,)), expected)
        self.assertEqual(target.plot_sizes, sizes)

    def test_matrix_and_eviction_randomness_do_not_advance_legacy_proposals(self):
        state = FactorizedBeliefState(seed=17)
        before = state.rng.getstate()
        state.matrix_rng.random()
        state.eviction_rng.random()
        self.assertEqual(state.rng.getstate(), before)
        self.assertEqual(state.rng.random(), random.Random(17).random())

    def test_switching_to_an_unsupported_ruleset_clears_the_target(self):
        state = FactorizedBeliefState(seed=3)
        state.role_posterior(evidence(), ())
        self.assertIsNotNone(state.role_target)
        with (patch.object(state, "_enumerate_roles"),
              patch.object(state.sampler, "sample", return_value=())):
            state._refresh_roles(replace(evidence(), module="MC"), ())
        self.assertIsNone(state.role_target)
