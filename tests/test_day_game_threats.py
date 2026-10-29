"""P0 threat classification tests."""

import unittest
from types import SimpleNamespace

from tragedy_sim.composition import BeliefSnapshot
from tragedy_sim.day_game.threats import (ThreatAssessment, classify_threats,
                                          earliest_incident_lead,
                                          public_incidents, role_distribution,
                                          select_primary_threat, threat_priority)


def active_threat():
    return ThreatAssessment(
        target="girl", failure_kind="character_loss", role="key",
        confidence=1.0, severity=1.0, deadline=None, active_now=True,
        source="hard_role", hard=True)


def view():
    return {"round": 4, "characters": {
        "girl": {"alive": True, "present": True, "location": "school"},
        "rich": {"alive": True, "present": True, "location": "school"},
        "outsider": {"alive": True, "present": True, "location": "city"},
    }}


def scenario():
    return {"cast": {"girl": "key", "rich": "killer", "outsider": "friend"},
            "incidents": [{"day": 5, "kind": "suicide", "culprit": "rich"}]}


class ThreatClassificationTests(unittest.TestCase):
    def test_hard_roles_produce_hard_character_and_role_threats(self):
        snapshot = BeliefSnapshot((), None, known_roles={"girl": "key", "rich": "killer"})  # type: ignore[arg-type]
        threats = classify_threats(view=view(), snapshot=snapshot, scenario=scenario())
        kinds = {(item.failure_kind, item.target): item for item in threats}
        self.assertIn(("character_loss", "girl"), kinds)
        self.assertTrue(kinds[("character_loss", "girl")].hard)
        self.assertTrue(kinds[("character_loss", "girl")].active_now)
        self.assertIn(("role_threat", "rich"), kinds)
        self.assertEqual(kinds[("role_threat", "rich")].confidence, 1.0)

    def test_particle_roles_are_posterior_not_hard(self):
        worlds = (SimpleNamespace(roles={"girl": "key", "rich": "killer"}),
                  SimpleNamespace(roles={"girl": "key", "rich": "killer"}))
        snapshot = BeliefSnapshot(worlds, None)  # type: ignore[arg-type]
        threats = classify_threats(view=view(), snapshot=snapshot, scenario=scenario())
        girl = next(item for item in threats
                    if item.failure_kind == "character_loss" and item.target == "girl")
        self.assertFalse(girl.hard)
        self.assertEqual(girl.source, "posterior_role")
        self.assertEqual(girl.confidence, 1.0)

    def test_low_confidence_role_is_ignored(self):
        worlds = (SimpleNamespace(roles={"girl": "key"}),
                  SimpleNamespace(roles={"girl": "ordinary"}))
        snapshot = BeliefSnapshot(worlds, None)  # type: ignore[arg-type]
        threats = classify_threats(view=view(), snapshot=snapshot,
                                   role_threshold=0.6)
        self.assertFalse(any(item.failure_kind == "character_loss" and item.target == "girl"
                             for item in threats))

    def test_known_incident_culprit_is_hard(self):
        snapshot = BeliefSnapshot((), None, known_culprits={5: "rich"})  # type: ignore[arg-type]
        threats = classify_threats(view=view(), snapshot=snapshot, scenario=scenario())
        incident = next(item for item in threats if item.failure_kind == "incident")
        self.assertTrue(incident.hard)
        self.assertEqual(incident.deadline, 5)
        self.assertFalse(incident.active_now)
        self.assertEqual(incident.severity, 1.0)

    def test_unknown_culprit_does_not_read_scenario(self):
        snapshot = BeliefSnapshot((), None)  # type: ignore[arg-type]
        threats = classify_threats(view=view(), snapshot=snapshot, scenario=scenario())
        self.assertFalse(any(item.failure_kind == "incident" for item in threats))

    def test_invalid_threshold_is_rejected(self):
        with self.assertRaises(ValueError):
            classify_threats(view=view(), role_threshold=0)


class ThreatPriorityTests(unittest.TestCase):
    def test_known_roles_do_not_erase_particle_posterior(self):
        from types import SimpleNamespace
        worlds = (SimpleNamespace(roles={"girl": "key", "rich": "killer"}),
                  SimpleNamespace(roles={"girl": "ordinary", "rich": "killer"}))
        snapshot = BeliefSnapshot(worlds, None, known_roles={"rich": "killer"})  # type: ignore[arg-type]
        distribution = role_distribution(snapshot)
        self.assertEqual(distribution["rich"], {"killer": 1.0})
        self.assertAlmostEqual(distribution["girl"]["key"], 0.5)
        self.assertAlmostEqual(distribution["girl"]["ordinary"], 0.5)

    def test_earliest_incident_outranks_later_hard_threat(self):
        early = ThreatAssessment(
            target="informer", failure_kind="incident", role="murder",
            confidence=1.0, severity=1.0, deadline=3, active_now=False,
            source="known_culprit", hard=True)
        later = ThreatAssessment(
            target="rich", failure_kind="incident", role="suicide",
            confidence=1.0, severity=1.0, deadline=5, active_now=False,
            source="known_culprit", hard=True)
        self.assertIs(select_primary_threat((later, early), 1), early)
        self.assertLess(threat_priority(early, 1), threat_priority(later, 1))

    def test_active_hard_threat_outranks_future_incident(self):
        active = active_threat()
        future = ThreatAssessment(
            target="informer", failure_kind="incident", role="murder",
            confidence=1.0, severity=1.0, deadline=3, active_now=False,
            source="known_culprit", hard=True)
        self.assertIs(select_primary_threat((future, active), 1), active)

    def test_invalid_current_day_is_rejected(self):
        with self.assertRaises(ValueError):
            threat_priority(active_threat(), 0)


class PublicIncidentTests(unittest.TestCase):
    @staticmethod
    def view_with_schedule(round_=1):
        return {"round": round_, "schedule": [{"day": 3, "kind": "murder"},
                                              {"day": 5, "kind": "suicide"}]}

    def test_public_schedule_is_read_without_culprits(self):
        incidents = public_incidents(self.view_with_schedule(1))
        self.assertEqual([(item.day, item.kind) for item in incidents],
                         [(3, "murder"), (5, "suicide")])
        self.assertEqual([item.lead for item in incidents], [2, 4])

    def test_earliest_lead_ignores_past_incidents(self):
        self.assertEqual(earliest_incident_lead(self.view_with_schedule(1)), 2)
        self.assertEqual(earliest_incident_lead(self.view_with_schedule(3)), 0)
        self.assertEqual(earliest_incident_lead(self.view_with_schedule(5)), 0)
        self.assertIsNone(earliest_incident_lead(self.view_with_schedule(6)))

    def test_horizon_filter_and_validation(self):
        incidents = public_incidents(self.view_with_schedule(1), horizon_days=2)
        self.assertEqual([item.kind for item in incidents], ["murder"])
        with self.assertRaises(ValueError):
            public_incidents(self.view_with_schedule(1), horizon_days=0)


if __name__ == "__main__":
    unittest.main()
