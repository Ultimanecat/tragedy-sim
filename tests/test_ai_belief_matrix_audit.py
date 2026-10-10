from copy import deepcopy
import unittest

from benchmarks.ai_belief_matrix_audit import audit_view
from tragedy_sim import Game
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.witness import FsbtxWitnessCompiler


class MatrixAuditTests(unittest.TestCase):
    def setUp(self):
        self.game = Game(ScenarioLibrary().get("official-btx-04-young-womens-battlefield"))
        self.view = self.game.protagonist_team_view()

    def test_real_setup_preserved_and_incident_domains_equal(self):
        result = audit_view(self.view, FsbtxWitnessCompiler().compile(self.view), self.game.scenario)
        self.assertEqual(result["false_hard_exclusions"], [])
        self.assertTrue(result["culprit_sampler_equal"])
        self.assertLessEqual(result["propagated_role_cells"], result["unary_role_cells"])

    def test_diagnostic_truth_does_not_change_inferred_domains(self):
        witnesses = FsbtxWitnessCompiler().compile(self.view)
        before = deepcopy(self.view)
        public = audit_view(self.view, witnesses)
        diagnostic = audit_view(self.view, witnesses, self.game.scenario)
        for result in (public, diagnostic):
            result.pop("projection_ms")
        self.assertEqual(public, diagnostic)
        self.assertEqual(self.view, before)


if __name__ == "__main__":
    unittest.main()
