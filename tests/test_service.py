"""Contract tests for the in-process JSON boundary and HTTP transport."""

from http.client import HTTPConnection
import json
from threading import Thread
import unittest

from tragedy_sim.server import create_server
from tragedy_sim.service import GameService, LocalGameClient, PROTOCOL_VERSION, ServiceError


class GameServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = GameService()
        self.created = self.service.create_game({"module": "BTX"})
        self.session_id = self.created["session_id"]
        self.tokens = self.created["credentials"]["seats"]
        self.admin = self.created["credentials"]["admin"]

    def test_views_are_json_and_private_views_require_the_matching_token(self):
        public = self.service.get_view(self.session_id)
        self.assertEqual(public["protocol_version"], PROTOCOL_VERSION)
        json.dumps(public, allow_nan=False)
        private = self.service.get_view(self.session_id, "m", token=self.tokens["m"])
        self.assertIn("secret", private["state"])
        with self.assertRaisesRegex(ServiceError, "访问令牌") as caught:
            self.service.get_view(self.session_id, "m", token=self.tokens["a"])
        self.assertEqual(caught.exception.code, "FORBIDDEN")
        public["state"]["characters"]["student"]["alive"] = False
        self.assertTrue(self.service.get_view(self.session_id)["state"]["characters"]["student"]["alive"])

    def test_public_catalog_is_complete_and_json_serializable(self):
        modules = self.service.list_modules()
        self.assertIn("MC", {item["id"] for item in modules["modules"]})
        catalog = self.service.get_catalog("MC")
        self.assertEqual(len(catalog["plots"]), 12)
        self.assertEqual(len(catalog["incidents"]), 11)
        self.assertIn("henchman", {item["id"] for item in catalog["characters"]})
        self.assertIn("m", catalog["cards"])
        json.dumps(catalog, allow_nan=False)

    def test_action_ids_revision_and_no_internal_effects_cross_boundary(self):
        first = self.service.get_actions(self.session_id, "m", token=self.tokens["m"])
        second = self.service.get_actions(self.session_id, "m", token=self.tokens["m"])
        self.assertEqual(first, second)
        action = first["actions"][0]
        self.assertEqual(action["type"], "next")
        self.assertNotIn("effects", json.dumps(action))
        result = self.service.dispatch(
            self.session_id,
            {"action_id": action["id"], "expected_revision": first["revision"]},
            token=self.tokens["m"])
        self.assertEqual(result["revision"], 1)
        self.assertEqual(result["view"]["state"]["phase"], "mastermind")
        with self.assertRaises(ServiceError) as caught:
            self.service.dispatch(
                self.session_id,
                {"action_id": action["id"], "expected_revision": first["revision"]},
                token=self.tokens["m"])
        self.assertEqual(caught.exception.code, "STALE_REVISION")
        self.assertEqual(caught.exception.status, 409)

    def test_wrong_seat_cannot_dispatch_and_snapshot_round_trips(self):
        actions = self.service.get_actions(self.session_id, "m", token=self.tokens["m"])
        command = {"action_id": actions["actions"][0]["id"],
                   "expected_revision": actions["revision"]}
        with self.assertRaises(ServiceError) as caught:
            self.service.dispatch(self.session_id, command, token=self.tokens["a"])
        self.assertEqual(caught.exception.code, "ACTION_NOT_AVAILABLE")
        with self.assertRaises(ServiceError) as missing_token:
            self.service.dispatch(self.session_id, command, token=None)
        self.assertEqual(missing_token.exception.code, "FORBIDDEN")
        stale_probe = dict(command, expected_revision=-1)
        with self.assertRaises(ServiceError) as unauthenticated_probe:
            self.service.dispatch(self.session_id, stale_probe, token=None)
        self.assertEqual(unauthenticated_probe.exception.code, "FORBIDDEN")
        self.service.dispatch(self.session_id, command, token=self.tokens["m"])
        snapshot = self.service.get_snapshot(self.session_id, token=self.admin)["snapshot"]
        restored = self.service.create_game({"snapshot": snapshot})
        restored_view = self.service.get_view(restored["session_id"])["state"]
        original_view = self.service.get_view(self.session_id)["state"]
        self.assertEqual(restored_view, original_view)
        with self.assertRaises(ServiceError) as replay_error:
            self.service.get_replay(self.session_id, token=self.admin)
        self.assertEqual(replay_error.exception.code, "REPLAY_NOT_READY")
        with self.assertRaises(ServiceError) as snapshot_error:
            self.service.create_game({"snapshot": {"version": 1, "scenario": {}, "commands": []}})
        self.assertEqual(snapshot_error.exception.code, "INVALID_SNAPSHOT")

    def test_local_client_dispatches_by_protocol_offer(self):
        client = LocalGameClient.from_scenario(self.service.unsafe_game(self.session_id).scenario)
        self.assertEqual(client.view()["phase"], "day_start")
        client.dispatch("m", "next")
        self.assertEqual(client.view()["phase"], "mastermind")


class HttpTransportTests(unittest.TestCase):
    def setUp(self):
        self.server = create_server("127.0.0.1", 0)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)

    def tearDown(self):
        self.connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, method, path, body=None, token=None):
        headers = {}
        encoded = None
        if body is not None:
            encoded = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = "Bearer " + token
        self.connection.request(method, path, body=encoded, headers=headers)
        response = self.connection.getresponse()
        raw = response.read()
        return response.status, json.loads(raw.decode("utf-8"))

    def test_health_create_public_view_and_authenticated_action(self):
        status, health = self.request("GET", "/v1/health")
        self.assertEqual((status, health["status"]), (200, "ok"))
        status, modules = self.request("GET", "/v1/modules")
        self.assertEqual(status, 200)
        self.assertIn("BTX", {item["id"] for item in modules["modules"]})
        status, created = self.request("POST", "/v1/games", {"module": "FS"})
        self.assertEqual(status, 201)
        session_id = created["session_id"]
        mastermind = created["credentials"]["seats"]["m"]

        status, public = self.request("GET", f"/v1/games/{session_id}/view")
        self.assertEqual((status, public["viewer"]), (200, "spectator"))
        status, forbidden = self.request("GET", f"/v1/games/{session_id}/view?viewer=m")
        self.assertEqual((status, forbidden["error"]["code"]), (403, "FORBIDDEN"))

        status, actions = self.request("GET", f"/v1/games/{session_id}/actions?actor=m",
                                       token=mastermind)
        self.assertEqual(status, 200)
        status, accepted = self.request(
            "POST", f"/v1/games/{session_id}/commands",
            {"action_id": actions["actions"][0]["id"],
             "expected_revision": actions["revision"]}, token=mastermind)
        self.assertEqual((status, accepted["revision"]), (200, 1))


if __name__ == "__main__":
    unittest.main()
