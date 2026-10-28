"""P0 threat classification tests."""

import unittest
from types import SimpleNamespace

from tragedy_sim.composition import BeliefSnapshot
from tragedy_sim.day_game.threats import classify_threats


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


if __name__ == "__main__":
    unittest.main()
