from copy import deepcopy
import json
import math
import unittest

from tragedy_sim.belief_matrix import (BeliefContradiction, BeliefMatrixProjection,
                                      HardStatus, role_domains)
from tragedy_sim.joint_mastermind import _PublicReplyEvaluator
from tragedy_sim.search import SearchBudget
from tragedy_sim.witness import FsbtxWitnessCompiler, PublicWitness, WitnessStrength


def witness(kind, subject, value, strength=WitnessStrength.HARD):
    return PublicWitness(kind, subject, value, 1, 1, "day_end", "unit_test", strength)


class BeliefMatrixTests(unittest.TestCase):
    def setUp(self):
        self.view = {"module": "BTX", "loop": 1, "round": 1,
                     "characters": {"girl": {}, "boy": {}, "doctor": {}},
                     "schedule": [{"day": 2, "kind": "suicide"}], "events": []}

    def test_hard_status_is_independent_of_sample_frequency(self):
        projection = BeliefMatrixProjection.from_view(
            self.view, (), role_counts=({"character": "girl", "counts": {"key": 12}},))
        self.assertEqual(projection.roles["girl"]["key"].approx_probability, 1)
        self.assertEqual(projection.roles["girl"]["key"].hard_status, HardStatus.UNKNOWN)
        self.assertEqual(projection.roles["girl"]["friend"].approx_probability, 0)
        self.assertEqual(projection.roles["girl"]["friend"].hard_status, HardStatus.UNKNOWN)
        self.assertIsNone(projection.roles["boy"]["key"].approx_probability)

    def test_unary_facts_and_rejections_are_auditable(self):
        projection = BeliefMatrixProjection.from_view(self.view, (
            witness("role_is", "girl", "key"),
            witness("role_not_in", "boy", ("key",)),
            witness("culprit_is", "2", "girl")))
        self.assertEqual(projection.roles["girl"]["key"].hard_status, HardStatus.ALWAYS)
        self.assertEqual(projection.roles["boy"]["key"].hard_status, HardStatus.NEVER)
        self.assertEqual(projection.culprits["2"]["girl"].hard_status, HardStatus.ALWAYS)
        self.assertEqual(projection.culprits["2"]["boy"].hard_status, HardStatus.NEVER)
        self.assertEqual(projection.role_exists["key"].hard_status, HardStatus.ALWAYS)
        self.assertIn("unit_test", projection.roles["boy"]["key"].sources)

    def test_incident_snapshot_thresholds_are_shared_with_sampler(self):
        from tragedy_sim.belief import FactorizedBeliefState, PublicEvidence
        snapshot = {cid: {"paranoia": 0, "alive": True, "present": True}
                    for cid in self.view["characters"]}
        snapshot["girl"]["paranoia"] = 99
        fact = witness("incident_happened", "2", {"kind": "suicide", "characters": snapshot})
        projection = BeliefMatrixProjection.from_view(self.view, (fact,))
        self.assertEqual(projection.culprits["2"]["girl"].hard_status, HardStatus.ALWAYS)
        self.assertEqual(projection.culprits["2"]["boy"].hard_status, HardStatus.NEVER)
        self.assertIn("unit_test", projection.culprits["2"]["girl"].sources)
        evidence = PublicEvidence.from_view({**self.view, "days": 2, "loops": 2})
        self.assertEqual(FactorizedBeliefState()._culprits(evidence, (fact,)), {2: ("girl",)})
        # Current counters can change; the recorded triggering snapshot stays authoritative.
        changed = deepcopy(self.view)
        changed["characters"]["boy"]["paranoia"] = 99
        self.assertEqual(BeliefMatrixProjection.from_view(changed, (fact,)).culprits,
                         projection.culprits)

    def test_ai_threshold_uses_all_counters(self):
        view = {**self.view, "characters": {"ai": {}, "girl": {}}}
        fact = witness("incident_happened", "2", {"kind": "suicide", "characters": {
            "ai": {"paranoia": 0, "goodwill": 99, "intrigue": 0, "guard": 0},
            "girl": {"paranoia": 0}}})
        projection = BeliefMatrixProjection.from_view(view, (fact,))
        self.assertEqual(projection.culprits["2"]["ai"].hard_status, HardStatus.ALWAYS)

    def test_soft_absence_and_missing_snapshot_do_not_exclude(self):
        for fact in (
            witness("incident_not_happened", "2", {"kind": "suicide"}, WitnessStrength.SOFT),
            witness("incident_happened", "2", {"kind": "suicide"})):
            with self.subTest(fact=fact):
                projection = BeliefMatrixProjection.from_view(self.view, (fact,))
                self.assertTrue(all(cell.hard_status == HardStatus.UNKNOWN
                                    for cell in projection.culprits["2"].values()))

    def test_replacement_culprit_maps_to_initial_cast(self):
        from tragedy_sim.belief_culprit_constraints import culprit_domains
        view = {**self.view, "characters": {"part_timer": {}, "part_timer_question": {}, "girl": {}}}
        facts = (witness("culprit_is", "2", "part_timer_question"),
                 witness("incident_happened", "2", {"kind": "suicide", "characters": {
                     "part_timer": {"paranoia": 0, "alive": False},
                     "part_timer_question": {"paranoia": 99, "present": True},
                     "girl": {"paranoia": 0}}}))
        projection = BeliefMatrixProjection.from_view(view, facts)
        self.assertEqual(projection.culprits["2"]["part_timer"].hard_status, HardStatus.ALWAYS)
        self.assertEqual(culprit_domains(("girl", "part_timer"), ((2, "suicide"),), {}, facts),
                         {2: ("part_timer",)})

    def test_impossible_incident_snapshot_is_explicit_contradiction(self):
        fact = witness("incident_happened", "2", {"kind": "suicide", "characters": {
            cid: {"paranoia": 0} for cid in self.view["characters"]}})
        with self.assertRaises(BeliefContradiction):
            BeliefMatrixProjection.from_view(self.view, (fact,))

    def test_disjunction_does_not_become_independent_facts(self):
        fact = witness("role_pressure", "key", {"candidates": ["girl", "boy"]})
        before = deepcopy(fact.value)
        projection = BeliefMatrixProjection.from_view(self.view, (fact,))
        self.assertEqual(len(projection.any_of), 1)
        self.assertEqual(projection.roles["doctor"]["key"].hard_status, HardStatus.UNKNOWN)
        self.assertEqual(projection.roles["girl"]["key"].hard_status, HardStatus.UNKNOWN)
        self.assertEqual(projection.any_of[0].atoms, (("roles", "girl", "key"), ("roles", "boy", "key")))
        self.assertEqual(projection.role_exists["key"].hard_status, HardStatus.ALWAYS)
        self.assertEqual(projection.role_count_bounds["key"].minimum, 1)
        self.assertEqual(projection.role_count_bounds["key"].maximum, 3)
        fact.value["candidates"].clear()
        self.assertEqual(projection.retained_witnesses[0].value, before)

    def test_soft_facts_never_set_hard_cells(self):
        projection = BeliefMatrixProjection.from_view(self.view, (
            witness("role_is", "girl", "key", WitnessStrength.SOFT),))
        self.assertEqual(projection.roles["girl"]["key"].hard_status, HardStatus.UNKNOWN)
        self.assertEqual(len(projection.retained_witnesses), 1)

    def test_virus_and_private_initial_identity_remain_distinct(self):
        fact = witness("role_is", "girl", "serial")
        projection = BeliefMatrixProjection.from_view(self.view, (fact,))
        self.assertEqual(projection.roles["girl"]["ordinary"].hard_status, HardStatus.UNKNOWN)
        self.assertEqual(projection.roles["girl"]["serial"].hard_status, HardStatus.UNKNOWN)
        view = {**self.view, "protagonist_knowledge": {"roles": {"girl": "ordinary"}}}
        exact = BeliefMatrixProjection.from_view(view, (fact,))
        self.assertEqual(exact.roles["girl"]["ordinary"].hard_status, HardStatus.ALWAYS)
        self.assertEqual(exact.roles["girl"]["serial"].hard_status, HardStatus.NEVER)
        # Original witness still carries the Virus plot requirement to matcher.
        self.assertEqual(exact.retained_witnesses[0], fact)

    def test_part_timer_replacement_is_not_an_extra_initial_column(self):
        view = {**self.view, "characters": {"part_timer": {}, "part_timer_question": {}}}
        projection = BeliefMatrixProjection.from_view(view, (
            witness("role_is", "part_timer_question", "key"),))
        self.assertEqual(set(projection.roles), {"part_timer"})
        self.assertEqual(projection.roles["part_timer"]["key"].hard_status, HardStatus.ALWAYS)

    def test_existence_uses_joint_assignments_not_marginal_sum(self):
        assignments = ({"girl": "key", "boy": "ordinary", "doctor": "ordinary"},
                       {"girl": "ordinary", "boy": "key", "doctor": "ordinary"})
        projection = BeliefMatrixProjection.from_view(
            self.view, (), role_assignments=assignments,
            role_counts=({"character": "girl", "counts": {"key": 1, "ordinary": 1}},
                         {"character": "boy", "counts": {"key": 1, "ordinary": 1}},
                         {"character": "doctor", "counts": {"ordinary": 2}}))
        self.assertEqual(projection.role_exists["ordinary"].approx_probability, 1)
        expected_count = sum(column["ordinary"].approx_probability for column in projection.roles.values())
        self.assertEqual(expected_count, 2)
        self.assertEqual(projection.role_exists["ordinary"].hard_status, HardStatus.UNKNOWN)

    def test_conflicting_hard_facts_and_impossible_samples_are_errors(self):
        facts = (witness("role_is", "girl", "key"), witness("role_is", "girl", "friend"))
        with self.assertRaises(BeliefContradiction):
            BeliefMatrixProjection.from_view(self.view, facts)
        with self.assertRaises(BeliefContradiction):
            BeliefMatrixProjection.from_view(self.view, facts[:1],
                role_counts=({"character": "girl", "counts": {"friend": 1}},))
        for count in (-1, float("nan"), float("inf")):
            with self.subTest(count=count), self.assertRaises(ValueError):
                BeliefMatrixProjection.from_view(self.view, (),
                    role_counts=({"character": "girl", "counts": {"key": count}},))

    def test_text_and_json_preserve_unknown_and_retained_constraints(self):
        projection = BeliefMatrixProjection.from_view(self.view, (
            witness("role_route_pressure", "loss", {"key": ["girl"], "factor": ["boy"]}),))
        exported = json.loads(json.dumps(projection.to_dict(), allow_nan=False))
        self.assertEqual(exported["roles"]["girl"]["key"]["hard_status"], "unknown")
        self.assertEqual(exported["any_of"][0]["witness"]["source"], "unit_test")
        self.assertIn("unknown", projection.to_text())
        self.assertIn("析取 hard", projection.to_text())

    def test_black_entropy_reuses_same_public_domains(self):
        view = {**self.view, "known_roles": {"girl": {"role": "friend"}}}
        roles, domains, _ = role_domains(view, FsbtxWitnessCompiler().compile(view))
        expected = sum(math.log(len(domain)) for domain in domains.values()) / (len(domains) * math.log(len(roles)))
        evaluator = _PublicReplyEvaluator(SearchBudget(node_limit=1), 0)
        self.assertAlmostEqual(evaluator._role_entropy(view), expected)
        self.assertEqual(domains["girl"], {"friend"})


if __name__ == "__main__":
    unittest.main()
