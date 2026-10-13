from copy import deepcopy
import random
import unittest
from unittest.mock import patch

from tragedy_sim import Game
from tragedy_sim.belief import DarkCardBelief, FactorizedBeliefState, PublicEvidence
from tragedy_sim.belief import HiddenWorldHypothesis
from tragedy_sim.belief_dark_constraints import dark_card_domains
from tragedy_sim.belief_matrix_sampler import MatrixWorldSampler
from tragedy_sim.cards import deck
from tragedy_sim.scenario import validate_scenario
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.witness import FsbtxWitnessMatcher
from tests.test_belief_matrix import witness


class MatrixSamplerTests(unittest.TestCase):
    def test_corrected_matrix_proposals_replace_unknown_density_legacy_pool(self):
        scenario = ScenarioLibrary().get("official-btx-06-secret-that-was-kept")
        view = Game(scenario).protagonist_team_view()
        view["known_plots"] = ["bomb", "friends", "threads"]
        evidence = PublicEvidence.from_view(view)
        weak_scenario = deepcopy(scenario)
        weak_scenario["cast"]["rich"] = "ordinary"
        weak_scenario["cast"]["patient"] = "witch"
        weak = HiddenWorldHypothesis.from_scenario(validate_scenario(weak_scenario))
        facts = (witness("role_is", "informer", "conspiracy"),
                 witness("role_is", "worker", "friend"))
        for enabled in (False, True):
            state = FactorizedBeliefState(seed=1, matrix_proposals=enabled)
            with patch.object(state.sampler, "sample", return_value=(weak,)):
                posterior = state.role_posterior(evidence, facts)
            self.assertEqual(state.matrix_recovery_attempts, 0)
            self.assertEqual(state.matrix_proposal_attempts, int(enabled))
            if enabled:
                self.assertGreater(len(posterior), 1)
                self.assertTrue(any(dict(world.roles)["rich"] == "witch"
                                    for world, _ in posterior))
                self.assertGreater(state.matrix_proposal_worlds, 0)
            else:
                self.assertEqual(len(posterior), 1)
            for world, _ in posterior:
                self.assertTrue(FsbtxWitnessMatcher().matches(world, facts))
                world.materialize(evidence)
            rng_before = state.rng.getstate()
            summary = state.proposal_summary()
            self.assertEqual(state.rng.getstate(), rng_before)
            self.assertEqual(summary, state.proposal_summary())
            self.assertEqual(summary["role_candidates"], len(posterior))

    def test_normal_proposals_preserve_exact_small_cast_path(self):
        scenario = ScenarioLibrary().get("official-fs-01-first-script")
        evidence = PublicEvidence.from_view(Game(scenario).protagonist_team_view())
        original = FactorizedBeliefState(seed=2)
        enabled = FactorizedBeliefState(seed=2, matrix_proposals=True)
        self.assertEqual(original.sample(evidence, (), 8, rng=random.Random(3)),
                         enabled.sample(evidence, (), 8, rng=random.Random(3)))
        self.assertTrue(enabled._exact_roles)
        self.assertEqual(enabled.matrix_proposal_attempts, 0)

    def test_normal_proposals_do_not_relax_incompatible_hard_counts(self):
        scenario = ScenarioLibrary().get("official-btx-06-secret-that-was-kept")
        view = Game(scenario).protagonist_team_view()
        view["known_plots"] = ["bomb", "friends", "threads"]
        evidence = PublicEvidence.from_view(view)
        facts = (witness("role_is", "rich", "witch"),
                 witness("role_is", "patient", "witch"))
        state = FactorizedBeliefState(matrix_recovery=False, matrix_proposals=True)
        with patch.object(state.sampler, "sample", return_value=()):
            result = state.sample(evidence, facts, 8, rng=random.Random(3))
        self.assertEqual(result.reason, "no_compatible_factor")
        self.assertEqual(state.matrix_proposal_worlds, 0)

    def test_normal_proposal_flag_requires_boolean(self):
        with self.assertRaises(ValueError):
            FactorizedBeliefState(matrix_proposals=1)

    def setUp(self):
        self.scenario = ScenarioLibrary().get("official-fs-01-first-script")
        self.scenario["cast"]["patient"] = "ordinary"
        self.view = Game(validate_scenario(self.scenario)).protagonist_team_view()
        self.view["known_plots"] = ["murder_plan", "ripper"]
        self.evidence = PublicEvidence.from_view(self.view)
        self.facts = (witness("role_is", "girl", "key"),)

    def test_constructed_worlds_are_legal_hard_compatible_and_diverse(self):
        worlds = MatrixWorldSampler().sample(self.evidence, self.facts, 12, rng=random.Random(9))
        self.assertEqual(len(worlds), 12)
        self.assertGreater(len({world.roles for world in worlds}), 1)
        for world in worlds:
            self.assertEqual(dict(world.roles)["girl"], "key")
            self.assertTrue(FsbtxWitnessMatcher().matches(world, self.facts))
            self.assertEqual(world.materialize(self.evidence)["module"], "FS")

    def test_old_paths_empty_matrix_recovery_can_be_ablated(self):
        results = []
        for enabled in (False, True):
            state = FactorizedBeliefState(seed=3, matrix_recovery=enabled)
            with patch.object(state.sampler, "sample", return_value=()):
                result = state.sample(self.evidence, self.facts, 12, rng=random.Random(4))
            results.append(result)
            self.assertEqual(state.matrix_recovery_attempts, int(enabled))
            if enabled:
                self.assertGreater(state.matrix_recovery_worlds, 0)
                self.assertFalse(state._exact_roles)
        self.assertEqual(results[0].reason, "no_compatible_factor")
        self.assertEqual(len(results[1].worlds), 12)
        self.assertIsNone(results[1].reason)

    def test_successful_legacy_proposals_preserve_fixed_seed_results(self):
        results = []
        for enabled in (False, True):
            state = FactorizedBeliefState(seed=1, matrix_recovery=enabled)
            results.append(state.sample(self.evidence, self.facts, 12, rng=random.Random(5)))
            self.assertEqual(state.matrix_recovery_attempts, 0)
        self.assertEqual(results[0], results[1])

    def test_contradictory_hard_counts_are_not_relaxed(self):
        contradictory = (*self.facts, witness("role_is", "doctor", "key"))
        self.assertEqual(MatrixWorldSampler().sample(
            self.evidence, contradictory, 12, rng=random.Random(4)), ())

    def test_copycat_recovery_respects_extra_role_and_full_validator(self):
        scenario = deepcopy(self.scenario)
        scenario["cast"]["copycat"] = "key"
        scenario["character_options"] = {"copycat": {"role_source": "girl"}}
        view = Game(validate_scenario(scenario)).protagonist_team_view()
        view["known_plots"] = ["murder_plan", "ripper"]
        facts = (*self.facts, witness("role_is", "copycat", "key"))
        evidence = PublicEvidence.from_view(view)
        worlds = MatrixWorldSampler().sample(evidence, facts, 8, rng=random.Random(5))
        self.assertEqual(len(worlds), 8)
        for world in worlds:
            self.assertEqual(sum(role == "key" for _, role in world.roles), 2)
            world.materialize(evidence)

    def test_full_matcher_rejects_relations_not_fully_propagated(self):
        with patch("tragedy_sim.belief_matrix_sampler.FsbtxWitnessMatcher.matches", return_value=False):
            self.assertEqual(MatrixWorldSampler().sample(
                self.evidence, self.facts, 4, rng=random.Random(7), max_attempts=8), ())

    def test_dark_matrix_constraints_preserve_seeded_sampling_and_physical_uniqueness(self):
        pending = [{"actor": "m", "target": "girl"},
                   {"actor": "m", "target": "hospital"},
                   {"actor": "m", "target": "doctor"}]
        hands = {"m": list(deck("m", "FS"))}
        _, domains, _ = dark_card_domains({"module": "FS", "pending": pending})
        for seed in range(30):
            original = DarkCardBelief.sample(pending, hands, rng=random.Random(seed))
            constrained = DarkCardBelief.sample(pending, hands, rng=random.Random(seed),
                                                card_domains={int(slot): values for slot, values in domains.items()})
            self.assertEqual(original, constrained)
            self.assertEqual(len({card for _, card, _ in constrained}), 3)
        self.assertEqual(hands["m"], list(deck("m", "FS")))

    def test_dark_constraints_are_enforced_for_forced_history(self):
        pending = [{"actor": "m", "target": "girl"}]
        self.assertIsNone(DarkCardBelief.sample(pending, {"m": ["h", "v"]},
            rng=random.Random(2), historical_cards={0: "h"}, card_domains={0: {"v"}}))
