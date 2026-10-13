from collections import Counter
from dataclasses import replace
from itertools import product
from math import prod
import random
import unittest
from unittest.mock import patch

from tragedy_sim import Game
from tragedy_sim.belief import FactorizedBeliefState, PublicEvidence
from tragedy_sim.belief_culprit_constraints import culprit_domains
from tragedy_sim.belief_culprit_posterior import JointCulpritPosterior, joint_culprit_posterior
from tragedy_sim.belief_matrix import BeliefContradiction, BeliefMatrixProjection, HardStatus
from tragedy_sim.scenario_library import ScenarioLibrary
from tests.test_belief_matrix import witness


def enumerate_assignments(schedule, domains, weights):
    """Independent product/repeat-rule reference; no suffix DP."""
    result = {}
    for choices in product(*(domains[day] for day, _ in schedule)):
        kinds = {}
        for (_, kind), cid in zip(schedule, choices):
            kinds.setdefault(cid, []).append(kind)
        if any(len(values) > 1 and any(kind != "serial_murder" for kind in values)
               for values in kinds.values()):
            continue
        result[choices] = prod(weights[day][cid] for (day, _), cid in zip(schedule, choices))
    total = sum(result.values())
    return {key: weight / total for key, weight in result.items()} if total else {}


class JointCulpritTests(unittest.TestCase):
    def test_marginals_and_actual_draws_match_conditional_product_reference(self):
        schedule = ((1, "serial_murder"), (2, "suicide"), (3, "serial_murder"))
        domains = {1: ("girl", "doctor", "maiden"), 2: ("girl", "doctor"),
                   3: ("girl", "doctor", "maiden")}
        weights = {1: {"girl": 4, "doctor": 1, "maiden": 2},
                   2: {"girl": 1, "doctor": 3},
                   3: {"girl": 1, "doctor": 2, "maiden": 1}}
        reference = enumerate_assignments(schedule, domains, weights)
        posterior = JointCulpritPosterior(schedule, domains, weights)
        marginals = posterior.marginals()
        for index, (day, _) in enumerate(schedule):
            for cid in domains[day]:
                self.assertAlmostEqual(marginals[day][cid], sum(
                    p for choice, p in reference.items() if choice[index] == cid), places=12)
            self.assertAlmostEqual(sum(marginals[day].values()), 1)
        rng = random.Random(11)
        draws = Counter(tuple(posterior.sample(rng).values()) for _ in range(20000))
        self.assertEqual(draws.keys(), reference.keys())
        for choice, probability in reference.items():
            self.assertLess(abs(draws[choice] / 20000 - probability), 0.012)

    def test_global_domains_propagate_future_known_culprit_without_soft_exclusion(self):
        schedule = ((1, "suicide"), (2, "hospital"))
        facts = (witness("culprit_is", "2", "doctor"),)
        domains = culprit_domains(("girl", "doctor"), schedule, {}, facts)
        self.assertEqual(domains, {1: ("girl",), 2: ("doctor",)})
        view = {"module": "FS", "characters": {"girl": {}, "doctor": {}},
                "schedule": [{"day": day, "kind": kind} for day, kind in schedule]}
        matrix = BeliefMatrixProjection.from_view(view, facts)
        self.assertEqual(matrix.culprits["1"]["girl"].hard_status, HardStatus.ALWAYS)
        self.assertEqual(matrix.culprits["1"]["doctor"].hard_status, HardStatus.NEVER)
        contradictory = (*facts, witness("culprit_is", "1", "doctor"))
        self.assertEqual(culprit_domains(("girl", "doctor"), schedule, {}, contradictory),
                         {1: (), 2: ()})
        with self.assertRaises(BeliefContradiction):
            BeliefMatrixProjection.from_view(view, contradictory)

    def test_serial_repeats_allowed_but_any_mixed_repeat_is_rejected(self):
        for kinds, valid in ((("serial_murder", "serial_murder"), True),
                             (("serial_murder", "suicide"), False),
                             (("suicide", "serial_murder"), False),
                             (("suicide", "hospital"), False)):
            schedule = tuple(enumerate(kinds, 1))
            posterior = JointCulpritPosterior(schedule, {1: ("girl",), 2: ("girl",)})
            self.assertEqual(bool(posterior.partition), valid)
            self.assertEqual(posterior.sample(random.Random(0)) is not None, valid)

    def test_joint_sampler_never_needs_repeat_rejection_in_tight_schedule(self):
        scenario = ScenarioLibrary().get("official-fs-01-first-script")
        evidence = PublicEvidence.from_view(Game(scenario).protagonist_team_view())
        evidence = replace(evidence, schedule=tuple(
            (index, "suicide") for index in range(1, 5)))
        state = FactorizedBeliefState(seed=3, joint_culprits=True)
        # A valid complete role library is independent of hypothetical events.
        posterior = state.role_posterior(replace(evidence, schedule=()), ())
        # Ignore stale incident placeholders to exercise four-day composition.
        roles = tuple((replace(world, incidents=tuple(
            (day, kind, kind, evidence.characters[day - 1]) for day, kind in evidence.schedule)), weight)
                      for world, weight in posterior)
        with patch.object(state, "role_posterior", return_value=roles):
            result = state.sample(evidence, (), 64, rng=random.Random(7))
        self.assertEqual(len(result.worlds), 64)
        for world in result.worlds:
            self.assertEqual(len({row[3] for row in world.incidents}), 4)
            world.materialize(evidence)
        diagnostic = state.proposal_summary()["culprit_posterior"]
        self.assertEqual(diagnostic["version"], "legal-joint-culprits-v1")
        diagnostic["feasible"] = False
        self.assertTrue(state.proposal_summary()["culprit_posterior"]["feasible"])

    def test_empty_schedule_contradiction_and_invalid_weights(self):
        empty = JointCulpritPosterior((), {})
        self.assertEqual(empty.sample(random.Random(1)), {})
        self.assertEqual(empty.marginals(), {})
        schedule = ((1, "suicide"), (2, "suicide"), (3, "suicide"))
        impossible = JointCulpritPosterior(schedule, dict.fromkeys((1, 2, 3), ("girl", "doctor")))
        self.assertFalse(impossible.partition)
        self.assertEqual(impossible.support(), {1: (), 2: (), 3: ()})
        for value in (0, -1, float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                JointCulpritPosterior(((1, "suicide"),), {1: ("girl",)}, {1: {"girl": value}})
        with self.assertRaises(ValueError):
            FactorizedBeliefState(joint_culprits=1)

    def test_cache_and_projection_are_rng_free_and_deterministic(self):
        schedule = ((1, "suicide"), (2, "serial_murder"))
        domains = {1: ("girl", "doctor"), 2: ("girl", "doctor")}
        first = joint_culprit_posterior(schedule, domains)
        self.assertIs(first, joint_culprit_posterior(schedule, domains))
        self.assertEqual(first.support(), domains)
        rng = random.Random(3)
        before = rng.getstate()
        first.support(); first.marginals(); first.diagnostics()
        self.assertEqual(rng.getstate(), before)
