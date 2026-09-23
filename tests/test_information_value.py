"""Information-potential shaping remains public, reachable and non-repeating."""

from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace
import unittest

from tragedy_sim.catalog import CHARACTERS
from tragedy_sim.information_value import InformationOpportunityEvaluator


def character(cid, *, goodwill=0, alive=True, present=True):
    definition = CHARACTERS[cid]
    return {
        "alive": alive, "present": present, "goodwill": goodwill,
        "location": definition.start, "traits": list(definition.traits),
        "paranoia": 0, "paranoia_limit": definition.limit,
        "abilities": [asdict(ability) for ability in definition.abilities],
        "territory": None,
    }


def view(cid, *, loop=1, day=1, goodwill=0):
    return {
        "loop": loop, "round": day, "days": 3,
        "characters": {cid: character(cid, goodwill=goodwill)},
        "team_hands": {"a": ["g1", "g2"], "b": ["g1", "g2"],
                       "c": ["g1", "g2"]},
        "known_roles": {}, "known_culprits": {}, "known_plots": [],
        "protagonist_knowledge": {}, "ability_loop_used": [],
        "schedule": [], "incidents": [],
    }


def worlds(cid):
    state = SimpleNamespace(characters={cid: SimpleNamespace(present=True)})
    return (
        SimpleNamespace(roles={cid: "ordinary"}, state=state,
                        scenario={"subplots": [], "incidents": []}),
        SimpleNamespace(roles={cid: "key"}, state=state,
                        scenario={"subplots": [], "incidents": []}),
    )


class InformationValueTests(unittest.TestCase):
    def test_minimum_loop_makes_first_loop_irregular_investment_worthless(self):
        first = view("irregular", loop=1)
        model = InformationOpportunityEvaluator(worlds("irregular"), first)
        self.assertEqual(model.potential(first), 0.0)

        later = view("irregular", loop=2)
        model = InformationOpportunityEvaluator(worlds("irregular"), later)
        self.assertGreater(model.potential(later), 0.0)
        later["known_roles"] = {"irregular": {"role": "key"}}
        self.assertEqual(model.potential(later), 0.0)

    def test_unreachable_threshold_has_no_final_day_value(self):
        final_day = view("worker", day=3)
        model = InformationOpportunityEvaluator(worlds("worker"), final_day)
        self.assertEqual(model.potential(final_day), 0.0)

    def test_goodwill_progress_advances_reachable_information(self):
        root = view("worker", day=1)
        model = InformationOpportunityEvaluator(worlds("worker"), root)
        tomorrow = deepcopy(root)
        tomorrow["round"] = 2
        tomorrow["characters"]["worker"]["goodwill"] = 2
        tomorrow["team_hands"]["a"].remove("g2")
        result = model.evaluate_cutoff(tomorrow, ())
        self.assertGreater(result.future_potential, 0.0)
        self.assertEqual(result.realized_information, 0.0)
        self.assertEqual(model.investment_targets(root, 2), ("worker",))

    def test_new_role_and_information_refusal_are_audited(self):
        root = view("worker")
        model = InformationOpportunityEvaluator(worlds("worker"), root)
        final = deepcopy(root)
        final["known_roles"] = {"worker": {"role": "key"}}
        result = model.evaluate_cutoff(final, ({
            "kind": "goodwill_refused", "ability_kind": "reveal",
        },))
        self.assertGreater(result.realized_information, 0.0)
        self.assertEqual(result.refusal_witness, 0.15)

    def test_used_once_ability_has_no_future_value(self):
        root = view("copycat", loop=2, goodwill=3)
        root["ability_loop_used"] = ["goodwill:copycat:identify"]
        model = InformationOpportunityEvaluator(worlds("copycat"), root)
        self.assertEqual(model.potential(root), 0.0)

    def test_confirmed_threads_prices_new_goodwill_but_not_existing_goodwill(self):
        root = view("worker", day=2)
        root.update(module="BTX", loops=3)
        final = deepcopy(root)
        final["round"] = 3
        final["characters"]["worker"]["goodwill"] = 2
        confirmed = InformationOpportunityEvaluator(
            worlds("worker"), root, threads_confirmed=True)
        unknown = InformationOpportunityEvaluator(worlds("worker"), root)
        result = confirmed.evaluate_cutoff(final, ())
        self.assertGreater(result.future_potential, 0.0)
        self.assertAlmostEqual(result.threads_carryover_risk, 0.003)
        final["characters"]["worker"]["alive"] = False
        self.assertAlmostEqual(confirmed.evaluate_cutoff(
            final, ()).threads_carryover_risk, 0.003)
        self.assertEqual(unknown.evaluate_cutoff(final, ()).threads_carryover_risk,
                         0.0)

        root["characters"]["worker"]["goodwill"] = 1
        self.assertEqual(InformationOpportunityEvaluator(
            worlds("worker"), root, threads_confirmed=True
        ).evaluate_cutoff(final, ()).threads_carryover_risk, 0.0)
        root["loop"] = root["loops"]
        self.assertEqual(InformationOpportunityEvaluator(
            worlds("worker"), root, threads_confirmed=True
        ).evaluate_cutoff(final, ()).threads_carryover_risk, 0.0)


if __name__ == "__main__":
    unittest.main()
