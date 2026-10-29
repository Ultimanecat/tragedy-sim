"""Protocol-v1 fixture drift guard.

The Web tests consume hand-written JSON fixtures. This test regenerates the
service responses in memory and compares their structure with the fixtures, so a
field added on the Python side fails here instead of silently drifting.
"""

import json
import unittest
from pathlib import Path

from tragedy_sim.service import GameService

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "web" / "fixtures" / "protocol-v1"

# Fields that legitimately differ between a fresh session and the fixture.
VOLATILE = {
    "session_id", "revision", "message", "timepoint", "remaining",
    "scenario_id", "title", "language",
}


def _shape(value):
    """Return a comparable type skeleton: dict keys, list length, leaf types."""
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        if not value:
            return []
        # Compare the first element only; item counts vary with cast size.
        return [_shape(value[0])]
    return type(value).__name__


def _fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class ProtocolFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = GameService()
        cls.created = cls.service.create_game({"module": "BTX"})
        cls.session = cls.created["session_id"]
        cls.seat = cls.created["credentials"]["seats"]["m"]

    def assert_keys_cover(self, name, live, fixture):
        """Every live key must exist in the fixture with the same value type."""
        shape_live, shape_fix = _shape(live), _shape(fixture)
        missing = []
        mismatched = []

        def walk(a, b, path=""):
            if isinstance(a, dict) and isinstance(b, dict):
                for key in a:
                    if key in VOLATILE and path == "":
                        continue
                    if key not in b:
                        missing.append(f"{path}/{key}")
                    else:
                        walk(a[key], b[key], f"{path}/{key}")
            elif isinstance(a, list) and isinstance(b, list):
                if a and b:
                    walk(a[0], b[0], f"{path}[]")
            elif a != b:
                mismatched.append((path, a, b))

        walk(shape_live, shape_fix)
        self.assertEqual(missing, [], f"{name}: fixture missing keys {missing[:10]}")
        self.assertEqual(mismatched, [],
                         f"{name}: fixture type drift {mismatched[:10]}")

    def test_modules_fixture_matches_service(self):
        self.assert_keys_cover("modules.json", self.service.list_modules(),
                               _fixture("modules.json"))

    def test_catalog_fixture_matches_service(self):
        self.assert_keys_cover("btx-catalog.json",
                               self.service.get_catalog("BTX"),
                               _fixture("btx-catalog.json"))

    def test_created_fixture_matches_service(self):
        self.assert_keys_cover("btx-created.json", self.created,
                               _fixture("btx-created.json"))

    def test_mastermind_view_fixture_matches_service(self):
        view = self.service.get_view(self.session, "m", token=self.seat)
        self.assert_keys_cover("btx-mastermind-view.json", view,
                               _fixture("btx-mastermind-view.json"))

    def test_day_start_actions_fixture_matches_service(self):
        actions = self.service.get_actions(self.session, "m", token=self.seat)
        self.assert_keys_cover("btx-day-start-actions.json", actions,
                               _fixture("btx-day-start-actions.json"))


if __name__ == "__main__":
    unittest.main()
