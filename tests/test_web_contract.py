"""Stage 0 fixtures stay valid, deterministic examples of protocol v1."""

import json
from pathlib import Path
import unittest

from tragedy_sim.service import PROTOCOL_VERSION


FIXTURES = Path(__file__).parents[1] / "web" / "fixtures" / "protocol-v1"


class WebContractFixtureTests(unittest.TestCase):
    def fixture(self, name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def test_every_fixture_is_protocol_v1_plain_json(self):
        files = list(FIXTURES.glob("*.json"))
        self.assertGreaterEqual(len(files), 5)
        for path in files:
            with self.subTest(path=path.name):
                payload = self.fixture(path.name)
                self.assertEqual(payload["protocol_version"], PROTOCOL_VERSION)
                json.dumps(payload, allow_nan=False)

    def test_public_fixture_excludes_secrets_and_private_engine_records(self):
        created = self.fixture("btx-created.json")
        public = created["view"]["state"]
        self.assertNotIn("secret", public)
        serialized = json.dumps(public, ensure_ascii=False)
        self.assertNotIn("resolution_traces", serialized)
        self.assertNotIn("activation_history", serialized)
        self.assertIn("timing", public)
        self.assertIn("timepoint", public)
        self.assertIn("phase_name", public)

    def test_private_fixture_and_actions_are_structured_not_text_driven(self):
        private = self.fixture("btx-mastermind-view.json")["state"]
        self.assertIn("secret", private)
        actions = self.fixture("btx-day-start-actions.json")["actions"]
        self.assertEqual(actions[0]["type"], "next")
        self.assertIn("id", actions[0])
        self.assertNotIn("effects", actions[0])


if __name__ == "__main__":
    unittest.main()
