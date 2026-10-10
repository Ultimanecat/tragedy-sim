from collections import Counter
from copy import deepcopy
import unittest

from tragedy_sim import Game
from tragedy_sim.belief_matrix import BeliefMatrixProjection, BeliefContradiction, HardStatus
from tragedy_sim.scenario import example_scenario, validate_scenario
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.witness import FsbtxWitnessCompiler
from tests.test_belief_matrix import witness


class PlotConstraintTests(unittest.TestCase):
    def setUp(self):
        self.scenario = ScenarioLibrary().get("official-fs-01-first-script")
        self.view = Game(self.scenario).protagonist_team_view()
        self.view["known_plots"] = ["murder_plan", "ripper"]

    def test_known_plots_give_exact_counts_and_unique_role_exclusion(self):
        projection = BeliefMatrixProjection.from_view(self.view, (witness("role_is", "girl", "key"),))
        self.assertEqual(projection.main_plots["murder_plan"].hard_status, HardStatus.ALWAYS)
        self.assertEqual(projection.main_plots["avenger"].hard_status, HardStatus.NEVER)
        self.assertEqual(projection.subplot_exists["ripper"].hard_status, HardStatus.ALWAYS)
        self.assertEqual(projection.role_count_bounds["key"].minimum, 1)
        self.assertEqual(projection.role_count_bounds["key"].maximum, 1)
        for cid in self.scenario["cast"]:
            self.assertEqual(projection.roles[cid]["key"].hard_status,
                             HardStatus.ALWAYS if cid == "girl" else HardStatus.NEVER)

    def test_exactly_one_role_propagates_disjunction_without_picking_a_side(self):
        projection = BeliefMatrixProjection.from_view(self.view, (
            witness("role_pressure", "key", {"candidates": ("girl", "doctor")}),))
        for cid in self.scenario["cast"]:
            self.assertEqual(projection.roles[cid]["key"].hard_status,
                             HardStatus.UNKNOWN if cid in {"girl", "doctor"} else HardStatus.NEVER)
        self.assertEqual(len(projection.any_of), 1)

    def test_last_remaining_holder_becomes_always(self):
        projection = BeliefMatrixProjection.from_view(self.view, tuple(
            witness("role_not_in", cid, ("key",)) for cid in self.scenario["cast"] if cid != "girl"))
        self.assertEqual(projection.roles["girl"]["key"].hard_status, HardStatus.ALWAYS)

    def test_soft_plot_evidence_does_not_remove_plot_candidates(self):
        from tragedy_sim.witness_types import WitnessStrength
        view = {**self.view, "known_plots": []}
        baseline = BeliefMatrixProjection.from_view(view, ())
        soft = BeliefMatrixProjection.from_view(view, (
            witness("plot_present", "murder_plan", True, WitnessStrength.SOFT),))
        self.assertEqual(baseline.plot_candidates, soft.plot_candidates)

    def test_conflicting_count_or_plot_facts_have_no_variants(self):
        for facts in ((witness("role_is", "girl", "key"), witness("role_is", "doctor", "key")),
                      (witness("plot_not_present", "ripper", True),)):
            with self.subTest(facts=facts), self.assertRaises(BeliefContradiction):
                BeliefMatrixProjection.from_view(self.view, facts)

    def test_irregular_extra_role_is_counted_without_consuming_plot_slot(self):
        scenario = deepcopy(self.scenario)
        scenario["cast"]["irregular"] = "friend"
        view = Game(validate_scenario(scenario)).protagonist_team_view()
        view["known_plots"] = ["murder_plan", "ripper"]
        projection = BeliefMatrixProjection.from_view(view, (witness("role_is", "irregular", "friend"),))
        self.assertEqual(projection.role_count_bounds["friend"].minimum, 1)
        self.assertEqual(projection.role_count_bounds["friend"].maximum, 1)
        self.assertEqual(projection.role_count_bounds["key"].maximum, 1)

    def test_copycat_duplicate_does_not_consume_a_second_plot_slot(self):
        scenario = deepcopy(self.scenario)
        scenario["cast"]["copycat"] = "key"
        scenario["character_options"] = {"copycat": {"role_source": "girl"}}
        view = Game(validate_scenario(scenario)).protagonist_team_view()
        view["known_plots"] = ["murder_plan", "ripper"]
        projection = BeliefMatrixProjection.from_view(view, (witness("role_is", "copycat", "key"),))
        self.assertEqual(projection.role_count_bounds["key"].minimum, 2)
        self.assertEqual(projection.role_count_bounds["key"].maximum, 2)

    def test_hideous_optional_curmudgeon_is_not_falsely_excluded(self):
        scenario = deepcopy(self.scenario)
        scenario["subplots"] = ["hideous"]
        scenario["cast"]["maiden"] = "friend"
        scenario["cast"]["student"] = "curmudgeon"
        view = Game(validate_scenario(scenario)).protagonist_team_view()
        view["known_plots"] = ["murder_plan", "hideous"]
        projection = BeliefMatrixProjection.from_view(view, (witness("role_is", "student", "curmudgeon"),))
        self.assertEqual(projection.roles["student"]["curmudgeon"].hard_status, HardStatus.ALWAYS)
        self.assertEqual(projection.role_count_bounds["curmudgeon"].minimum, 1)

    def test_all_recorded_fs_btx_truths_survive_public_and_revealed_views(self):
        library = ScenarioLibrary()
        for summary in library.list():
            if summary["module"] not in {"FS", "BTX"}:
                continue
            scenario = library.get(summary["id"])
            for revealed in (False, True):
                with self.subTest(scenario=scenario["id"], revealed=revealed):
                    view = Game(scenario).protagonist_team_view()
                    if revealed:
                        view["known_plots"] = [scenario["main_plot"], *scenario["subplots"]]
                        view["protagonist_knowledge"] = {"roles": scenario["cast"]}
                    projection = BeliefMatrixProjection.from_view(view, FsbtxWitnessCompiler().compile(view))
                    actual_counts = Counter(scenario["cast"].values())
                    for cid, role in scenario["cast"].items():
                        self.assertNotEqual(projection.roles[cid][role].hard_status, HardStatus.NEVER)
                        for possible, cell in projection.roles[cid].items():
                            if cell.hard_status == HardStatus.ALWAYS:
                                self.assertEqual(possible, role)
                    for role, bounds in projection.role_count_bounds.items():
                        self.assertLessEqual(bounds.minimum, actual_counts[role])
                        self.assertGreaterEqual(bounds.maximum, actual_counts[role])
