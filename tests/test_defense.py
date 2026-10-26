"""Pluggable defense obligation tests."""

import unittest

from tragedy_sim.defense import (CounterThresholdModel, CounterThresholdScheduler,
                                 DefenseContext, DefenseModule, IncidentModelRegistry,
                                 ScheduledIncidentProvider)


def context():
    return DefenseContext(
        view={"round": 4, "characters": {"rich": {"paranoia": 3, "paranoia_limit": 3}}},
        scenario={"incidents": [{"day": 5, "kind": "suicide", "culprit": "rich"}]},
        horizon_days=3,
    )


class CustomThreatModel:
    def extract(self, context, incident):
        from tragedy_sim.defense import DefenseObligation
        return (DefenseObligation("custom", int(incident["day"]), "custom", "rich",
                                  "paranoia", 1, 2, 1, 2),)


class DefenseModuleTests(unittest.TestCase):
    def test_suicide_model_extracts_a_counter_obligation(self):
        obligations = ScheduledIncidentProvider().extract(context())
        self.assertEqual(len(obligations), 1)
        self.assertEqual(obligations[0].target, "rich")
        self.assertEqual(obligations[0].need, 1)

    def test_scheduler_covered_and_unmet(self):
        provider = ScheduledIncidentProvider()
        context_ = context()
        obligations = provider.extract(context_)
        scheduler = CounterThresholdScheduler()
        covered = scheduler.assess(obligations,
                                   [{"card": "p-1", "target": "rich"}], context_)
        self.assertEqual(covered.covered, ("5:suicide:rich",))
        self.assertEqual(covered.unmet, ())
        self.assertEqual(covered.urgent, ("5:suicide:rich",))
        unmet = scheduler.assess(obligations,
                                 [{"card": "p-1", "target": "other"}], context_)
        self.assertEqual(unmet.unmet, ("5:suicide:rich",))

    def test_custom_incident_model_is_pluggable(self):
        registry = IncidentModelRegistry()
        registry.register("custom", CustomThreatModel())
        provider = ScheduledIncidentProvider(registry)
        context_ = DefenseContext(
            view={"round": 4, "characters": {"rich": {"paranoia": 1, "paranoia_limit": 3}}},
            scenario={"incidents": [{"day": 6, "kind": "custom", "culprit": "rich"}]},
            horizon_days=3,
        )
        obligations = provider.extract(context_)
        self.assertEqual(len(obligations), 1)
        self.assertEqual(obligations[0].kind, "custom")

    def test_unknown_incident_kind_is_ignored(self):
        provider = ScheduledIncidentProvider()
        context_ = DefenseContext(
            view={"round": 4, "characters": {}},
            scenario={"incidents": [{"day": 5, "kind": "unknown", "culprit": "rich"}]},
        )
        self.assertEqual(provider.extract(context_), ())

    def test_module_assesses_extracted_obligations(self):
        module = DefenseModule(ScheduledIncidentProvider())
        assessment = module.assess(context(), [{"card": "p-1", "target": "rich"}])
        self.assertEqual(assessment.score, 2.0)

    def test_invalid_safety_margin_is_rejected(self):
        with self.assertRaises(ValueError):
            CounterThresholdModel("paranoia", safety_margin=0)


if __name__ == "__main__":
    unittest.main()
