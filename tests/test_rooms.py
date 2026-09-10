"""Room lifecycle, authority and LAN transport tests."""

from http.client import HTTPConnection
import json
from threading import Thread
import unittest

from tragedy_sim.rooms import RoomService, WAITING_TTL
from tragedy_sim.replay import ReplayArchive
from tragedy_sim.server import create_server
from tragedy_sim.service import ServiceError


class RoomServiceTests(unittest.TestCase):
    def setUp(self):
        self.rooms = RoomService()
        self.created = self.rooms.create({
            "module": "BTX", "nickname": "房主", "seat": "m", "spectators": True,
        })
        self.code = self.created["room"]["code"]
        self.host = self.created["credential"]["admin_token"]
        self.tokens = {"m": self.created["credential"]["room_token"]}

    def join_all(self):
        for seat in "abc":
            joined = self.rooms.join(self.code, {"nickname": f"玩家 {seat.upper()}", "seat": seat})
            self.tokens[seat] = joined["credential"]["room_token"]

    def test_join_ready_start_and_private_game_authority(self):
        self.join_all()
        with self.assertRaises(ServiceError) as early:
            self.rooms.game_view(self.code, token=self.tokens["m"])
        self.assertEqual(early.exception.code, "ROOM_NOT_STARTED")
        for seat in "mabc":
            self.rooms.ready(self.code, {"ready": True}, token=self.tokens[seat])
        started = self.rooms.start(self.code, token=self.host)
        self.assertEqual(started["room"]["status"], "playing")
        self.assertNotIn("session_id", json.dumps(started))

        mastermind = self.rooms.game_view(self.code, token=self.tokens["m"])
        protagonist = self.rooms.game_view(self.code, token=self.tokens["a"])
        self.assertIn("secret", mastermind["state"])
        self.assertNotIn("secret", protagonist["state"])
        waiting_actions = self.rooms.game_actions(self.code, token=self.tokens["a"])
        self.assertEqual(waiting_actions["actor"], "a")
        self.assertEqual(waiting_actions["actions"], [])

        actions = self.rooms.game_actions(self.code, token=self.tokens["m"])
        result = self.rooms.game_command(self.code, {
            "action_id": actions["actions"][0]["id"],
            "expected_revision": actions["revision"],
        }, token=self.tokens["m"])
        self.assertEqual(result["revision"], 1)
        update = self.rooms.updates(self.code, started["room"]["revision"], 0,
                                    token=self.tokens["a"])
        self.assertTrue(update["game_changed"])
        self.assertFalse(update["room_changed"])

    def test_lobby_validation_kick_leave_and_close(self):
        joined = self.rooms.join(self.code, {"nickname": "Alice", "seat": "a"})
        alice = joined["credential"]["room_token"]
        public = self.rooms.get(self.code)
        self.assertEqual(public["room"]["seats"]["a"]["nickname"], "Alice")
        self.assertNotIn("credential", public)
        with self.assertRaises(ServiceError) as occupied:
            self.rooms.join(self.code, {"nickname": "Other", "seat": "a"})
        self.assertEqual(occupied.exception.code, "SEAT_OCCUPIED")
        with self.assertRaises(ServiceError) as not_host:
            self.rooms.start(self.code, token=alice)
        self.assertEqual(not_host.exception.code, "FORBIDDEN")

        self.rooms.leave(self.code, token=alice)
        self.assertIsNone(self.rooms.get(self.code)["room"]["seats"]["a"])
        joined = self.rooms.join(self.code, {"nickname": "Alice", "seat": "a"})
        self.rooms.kick(self.code, {"seat": "a"}, token=self.host)
        with self.assertRaises(ServiceError) as revoked:
            self.rooms.get(self.code, token=joined["credential"]["room_token"])
        self.assertEqual(revoked.exception.code, "FORBIDDEN")
        self.rooms.close(self.code, token=self.host)
        with self.assertRaises(ServiceError) as missing:
            self.rooms.get(self.code)
        self.assertEqual(missing.exception.code, "ROOM_NOT_FOUND")

    def test_start_requires_four_ready_players(self):
        with self.assertRaises(ServiceError) as not_full:
            self.rooms.start(self.code, token=self.host)
        self.assertEqual(not_full.exception.code, "ROOM_NOT_FULL")
        self.join_all()
        with self.assertRaises(ServiceError) as not_ready:
            self.rooms.start(self.code, token=self.host)
        self.assertEqual(not_ready.exception.code, "PLAYERS_NOT_READY")

    def test_four_room_tokens_can_complete_a_match_and_export_replay(self):
        self.join_all()
        for seat in "mabc":
            self.rooms.ready(self.code, {"ready": True}, token=self.tokens[seat])
        self.rooms.start(self.code, token=self.host)
        for _ in range(600):
            public = self.rooms.game_view(self.code)
            if public["state"]["winner"]:
                break
            actor = public["state"]["controller"]
            actions = self.rooms.game_actions(self.code, token=self.tokens[actor])
            self.assertTrue(actions["actions"])
            self.rooms.game_command(self.code, {
                "action_id": actions["actions"][0]["id"],
                "expected_revision": actions["revision"],
            }, token=self.tokens[actor])
        else:
            self.fail("LAN room did not reach a formal result")
        self.assertEqual(self.rooms.get(self.code)["room"]["status"], "finished")
        self.assertIn("TRAGEDY_LOOPER_REPLAY", self.rooms.game_replay(self.code, token=self.host))

    def test_inactive_waiting_rooms_expire(self):
        now = [100.0]
        rooms = RoomService(clock=lambda: now[0])
        created = rooms.create({"module": "FS", "nickname": "Host", "seat": "m"})
        now[0] += WAITING_TTL + 1
        with self.assertRaises(ServiceError) as expired:
            rooms.get(created["room"]["code"])
        self.assertEqual(expired.exception.code, "ROOM_NOT_FOUND")


class ReducedPlayerRoomTests(unittest.TestCase):
    def make_room(self, count, module="BTX"):
        rooms = RoomService()
        created = rooms.create({"module": module, "nickname": "Mastermind", "seat": "m",
                                "protagonist_count": count})
        code = created["room"]["code"]
        tokens = {"m": created["credential"]["room_token"]}
        for seat in "abc"[:count]:
            joined = rooms.join(code, {"nickname": f"Hero {seat.upper()}", "seat": seat})
            tokens[seat] = joined["credential"]["room_token"]
        for token in tokens.values():
            rooms.ready(code, {"ready": True}, token=token)
        admin = created["credential"]["admin_token"]
        rooms.start(code, token=admin)
        return rooms, code, tokens, admin

    @staticmethod
    def act_first_available(rooms, code, tokens):
        available = []
        for participant, token in tokens.items():
            actions = rooms.game_actions(code, token=token)
            if actions["actions"]:
                available.append((participant, token, actions))
        if len(available) != 1:
            raise AssertionError(f"expected one human controller, got {[item[0] for item in available]}")
        _, token, actions = available[0]
        offer = actions["actions"][0]
        rooms.game_command(code, {"action_id": offer["id"],
                                  "expected_revision": actions["revision"]}, token=token)
        return offer

    def test_one_protagonist_controls_all_three_logical_hands_and_completes(self):
        rooms, code, tokens, admin = self.make_room(1)
        view = rooms.game_view(code, token=tokens["a"])["state"]
        self.assertEqual(set(view["controlled_hands"]), {"a", "b", "c"})
        for _ in range(600):
            if rooms.game_view(code)["state"]["winner"]:
                break
            self.act_first_available(rooms, code, tokens)
        else:
            self.fail("two-person match did not finish")
        replay = rooms.game_replay(code, token=admin)
        self.assertIn('"nickname":"Hero A"', replay)
        self.assertIn('"actor":"b"', replay)
        ReplayArchive.parse(replay)

    def test_two_protagonists_alternate_leader_and_delegate_c_card_only(self):
        rooms, code, tokens, _ = self.make_room(2)
        self.assertEqual(rooms.get(code)["room"]["human_leader"], "a")
        self.act_first_available(rooms, code, tokens)  # day start
        for _ in range(3):
            self.assertEqual(self.act_first_available(rooms, code, tokens)["actor"], "m")

        a_actions = rooms.game_actions(code, token=tokens["a"])
        self.assertEqual({offer["actor"] for offer in a_actions["actions"]}, {"a"})
        self.assertEqual(rooms.game_actions(code, token=tokens["b"])["actions"], [])
        rooms.game_command(code, {"action_id": a_actions["actions"][0]["id"],
                                  "expected_revision": a_actions["revision"]}, token=tokens["a"])

        b_actions = rooms.game_actions(code, token=tokens["b"])
        self.assertEqual({offer["actor"] for offer in b_actions["actions"]}, {"b"})
        self.assertEqual(rooms.game_actions(code, token=tokens["a"])["actions"], [])
        rooms.game_command(code, {"action_id": b_actions["actions"][0]["id"],
                                  "expected_revision": b_actions["revision"]}, token=tokens["b"])

        c_actions = rooms.game_actions(code, token=tokens["a"])
        self.assertEqual({offer["actor"] for offer in c_actions["actions"]}, {"c"})
        self.assertEqual(rooms.game_actions(code, token=tokens["b"])["actions"], [])
        self.assertIn("c", rooms.game_view(code, token=tokens["a"])["state"]["controlled_hands"])
        self.assertNotIn("c", rooms.game_view(code, token=tokens["b"])["state"]["controlled_hands"])
        rooms.game_command(code, {"action_id": c_actions["actions"][0]["id"],
                                  "expected_revision": c_actions["revision"]}, token=tokens["a"])

        for _ in range(100):
            if rooms.get(code)["room"]["human_leader"] == "b":
                break
            self.act_first_available(rooms, code, tokens)
        else:
            self.fail("human leader did not alternate")
        state_a = rooms.game_view(code, token=tokens["a"])["state"]
        state_b = rooms.game_view(code, token=tokens["b"])["state"]
        self.assertNotIn("c", state_a["controlled_hands"])
        self.assertIn("c", state_b["controlled_hands"])
        for _ in range(600):
            if rooms.game_view(code)["state"]["winner"]:
                break
            self.act_first_available(rooms, code, tokens)
        else:
            self.fail("three-person match did not finish")

    def test_last_liar_requires_three_protagonist_players(self):
        rooms = RoomService()
        for count in (1, 2):
            with self.assertRaises(ServiceError) as rejected:
                rooms.create({"module": "LL", "nickname": "Host", "seat": "m",
                              "protagonist_count": count})
            self.assertEqual(rejected.exception.code, "PLAYER_COUNT_NOT_SUPPORTED")
        accepted = rooms.create({"module": "LL", "nickname": "Host", "seat": "m",
                                 "protagonist_count": 3})
        self.assertEqual(accepted["room"]["required_seats"], ["m", "a", "b", "c"])

    def test_room_command_rejects_invalid_field_types(self):
        rooms, code, tokens, _ = self.make_room(1)
        with self.assertRaises(ServiceError) as rejected:
            rooms.game_command(code, {"action_id": [], "expected_revision": "zero"},
                               token=tokens["a"])
        self.assertEqual(rejected.exception.code, "INVALID_REQUEST")


class RoomHttpTests(unittest.TestCase):
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
        headers, encoded = {}, None
        if body is not None:
            encoded = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = "Bearer " + token
        self.connection.request(method, path, body=encoded, headers=headers)
        response = self.connection.getresponse()
        raw = response.read()
        content = raw.decode("utf-8")
        return response.status, json.loads(content) if content else None

    def test_http_room_lifecycle(self):
        status, created = self.request("POST", "/v1/rooms", {
            "module": "FS", "nickname": "Host", "seat": "m", "spectators": False,
        })
        self.assertEqual(status, 201)
        code = created["room"]["code"]
        status, public = self.request("GET", f"/v1/rooms/{code}")
        self.assertEqual((status, public["room"]["module"]), (200, "FS"))
        status, joined = self.request("POST", f"/v1/rooms/{code}/join",
                                      {"nickname": "Alice", "seat": "a"})
        self.assertEqual(status, 201)
        token = joined["credential"]["room_token"]
        status, ready = self.request("POST", f"/v1/rooms/{code}/ready",
                                     {"ready": True}, token=token)
        self.assertEqual((status, ready["room"]["seats"]["a"]["ready"]), (200, True))
        status, forbidden = self.request("GET", f"/v1/rooms/{code}/game/view")
        self.assertEqual((status, forbidden["error"]["code"]), (403, "FORBIDDEN"))


if __name__ == "__main__":
    unittest.main()
