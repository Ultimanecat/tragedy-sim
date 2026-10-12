"""Proposal coverage for newly imported standard FS/BTX scripts."""
from dataclasses import replace
import random
import unittest

from tragedy_sim import Game
from tragedy_sim.belief import ConstraintBeliefSampler, FactorizedBeliefState, PublicEvidence
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.witness import FsbtxWitnessCompiler


class ImportedAiBeliefTests(unittest.TestCase):
    def setUp(self):
        self.scenario = ScenarioLibrary().get("official-tragic-aiplay-fs-02g")
        self.view = Game(self.scenario).protagonist_team_view()
        self.evidence = replace(PublicEvidence.from_view(self.view),
                                known_plots=("avenger", "hideous"),
                                known_culprits=((2, "worker"), (3, "maiden")))

    def test_small_cast_exact_library_covers_zero_one_two_optional_curmudgeons(self):
        tracker = FactorizedBeliefState(capacity=100_000, seed=0, matrix_recovery=False)
        posterior = tracker.role_posterior(self.evidence, ())
        amounts = {sum(role == "curmudgeon" for _, role in world.roles)
                   for world, _ in posterior}
        self.assertEqual(amounts, {0, 1, 2})
        self.assertTrue(tracker._exact_roles)
        actual = tuple(sorted(self.scenario["cast"].items()))
        self.assertTrue(any(world.roles == actual for world, _ in posterior))

    def test_revealed_curmudgeon_does_not_need_recovery_to_enter_exact_library(self):
        view = {**self.view, "known_plots": ["avenger", "hideous"],
                "protagonist_knowledge": {"roles": self.scenario["cast"]},
                "known_culprits": {"2": "worker", "3": "maiden"}}
        evidence = PublicEvidence.from_view(view)
        tracker = FactorizedBeliefState(seed=0, matrix_recovery=False)
        result = tracker.sample(evidence, FsbtxWitnessCompiler().compile(view),
                                4, rng=random.Random(0))
        self.assertEqual(len(result.worlds), 4)
        self.assertTrue(tracker._exact_roles)
        self.assertEqual(tracker.matrix_recovery_attempts, 0)
        self.assertTrue(all(dict(world.roles) == self.scenario["cast"] for world in result.worlds))

    def test_constructive_prior_can_generate_optional_curmudgeons(self):
        worlds = ConstraintBeliefSampler().sample(self.evidence, 64, rng=random.Random(0))
        self.assertTrue(any("curmudgeon" in dict(world.roles).values() for world in worlds))
        self.assertTrue(all(world.materialize(self.evidence) for world in worlds))

    def test_optional_counts_use_the_same_plot_prior_in_map_and_exact_library(self):
        tracker = FactorizedBeliefState(capacity=100_000, seed=0, matrix_recovery=False)
        posterior = tracker.role_posterior(self.evidence, ())
        solved = tracker.exact_role_map(self.evidence, ())
        self.assertEqual(solved.plot_sets, 1)
        self.assertEqual(solved.compatible_count, len(posterior))
        self.assertEqual(solved.ranked[0][1], posterior[0][1])
        revealed = replace(self.evidence, known_roles=tuple(sorted(self.scenario["cast"].items())))
        solved = tracker.exact_role_map(revealed, ())
        self.assertEqual(dict(solved.selected.roles), self.scenario["cast"])

    def test_full_reveals_of_all_five_imported_baselines_are_sampleable(self):
        library = ScenarioLibrary()
        for sid in ("official-tragic-aiplay-fs-02g", "official-tragic-aiplay-btx-01g",
                    "official-tragic-aiplay-btx-02g", "community-tragic-aiplay-btx-08",
                    "community-tragic-aiplay-btx-45"):
            with self.subTest(scenario=sid):
                scenario = library.get(sid)
                view = Game(scenario).protagonist_team_view()
                view["known_plots"] = [scenario["main_plot"], *scenario["subplots"]]
                view["protagonist_knowledge"] = {"roles": scenario["cast"]}
                view["known_culprits"] = {str(item["day"]): item["culprit"]
                                           for item in scenario["incidents"]}
                evidence = PublicEvidence.from_view(view)
                witnesses = FsbtxWitnessCompiler().compile(view)
                tracker = FactorizedBeliefState(seed=0, matrix_recovery=False)
                result = tracker.sample(evidence, witnesses, 4, rng=random.Random(0))
                self.assertEqual(len(result.worlds), 4)
                self.assertTrue(all(dict(world.roles) == scenario["cast"] for world in result.worlds))
                self.assertEqual(dict(tracker.exact_role_map(evidence, witnesses).selected.roles),
                                 scenario["cast"])


if __name__ == "__main__":
    unittest.main()
