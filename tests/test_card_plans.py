"""Atomic full-side placement, authority and unchanged single-card contracts."""

from copy import deepcopy
from http.client import HTTPConnection
import json
from threading import Thread
import unittest
from unittest.mock import patch

from tragedy_sim.service import GameService, ServiceError
from tragedy_sim.rooms import RoomService
from tragedy_sim.server import create_server


def choose_plays(plan):
    result = []
    for slot in plan["slots"]:
        for offer in slot["actions"]:
            card, target = offer["parameters"]["card"], offer["parameters"]["target"]
            used = sum(p["actor"] == offer["actor"] and p["card"] == card for p in result)
            if (all(p["target"] != target for p in result)
                    and used < plan["constraints"]["card_limits"][offer["actor"]][card]):
                result.append({"actor": offer["actor"], "card": card, "target": target})
                break
        else:
            raise AssertionError("No valid plan")
    return result


class CardPlanTests(unittest.TestCase):
    def setup_game(self, module="BTX"):
        self.service = GameService()
        created = self.service.create_game({"module": module})
        self.sid, self.admin = created["session_id"], created["credentials"]["admin"]
        self.tokens = created["credentials"]["seats"]
        actions = self.service.get_actions(self.sid, "m", token=self.tokens["m"])
        self.service.dispatch(self.sid, {"action_id": actions["actions"][0]["id"],
                                       "expected_revision": actions["revision"]}, token=self.tokens["m"])

    def submit(self, actor, plays=None, token=None, revision=None):
        plan = self.service.get_card_plan(self.sid, actor, token=token or self.admin)
        return self.service.dispatch_card_plan(self.sid, {
            "actor": actor, "expected_revision": plan["revision"] if revision is None else revision,
            "plays": choose_plays(plan) if plays is None else plays,
        }, token=token or self.admin)

    def test_both_sides_in_all_rulesets_match_single_card_execution_and_snapshot(self):
        for module in ("FS", "BTX", "MZ", "MC", "HSA", "WM", "AHR", "LL"):
            with self.subTest(module=module):
                self.setup_game(module)
                for actor in ("m", "a"):
                    original = self.service.unsafe_game(self.sid)
                    plan = self.service.get_card_plan(self.sid, actor, token=self.admin)
                    plays = choose_plays(plan)
                    expected = original.clone()
                    for play in plays:
                        expected.dispatch(play["actor"], "play", card=play["card"], target=play["target"])
                    result = self.submit(actor, plays)
                    actual = self.service.unsafe_game(self.sid)
                    self.assertEqual(actual.history, expected.history)
                    self.assertEqual(actual.view("m"), expected.view("m"))
                    self.assertEqual(actual.decisions, expected.decisions)
                    self.assertEqual(result["revision"], plan["revision"] + 3)
                    self.assertEqual(len(result["accepted_actions"]), 3)
                snapshot = self.service.get_snapshot(self.sid, token=self.admin)["snapshot"]
                restored = self.service._game_from_snapshot(snapshot)
                self.assertEqual(restored.view("m"), self.service.unsafe_game(self.sid).view("m"))

    def test_invalid_second_or_third_card_rolls_back_all_state_and_logs(self):
        self.setup_game()
        plan = self.service.get_card_plan(self.sid, "m", token=self.admin)
        game = self.service.unsafe_game(self.sid)
        before = deepcopy(game.__dict__)
        for index in (1, 2):
            plays = choose_plays(plan)
            plays[index]["target"] = plays[0]["target"]
            with self.assertRaises(ServiceError) as error:
                self.submit("m", plays)
            self.assertEqual(error.exception.code, "RULE_VIOLATION")
            self.assertIs(self.service.unsafe_game(self.sid), game)
            self.assertEqual(game.history, before["history"])
            self.assertEqual(game.state, before["state"])
            self.assertEqual(game.decisions, before["decisions"])
            self.assertEqual(self.service.get_view(self.sid)["revision"], plan["revision"])

    def test_bad_cards_order_requests_tokens_and_duplicate_submission(self):
        self.setup_game()
        plan = self.service.get_card_plan(self.sid, "m", token=self.admin)
        for field, value in (("card", "not-a-card"), ("actor", "a")):
            plays = choose_plays(plan)
            plays[2][field] = value
            with self.assertRaises(ServiceError):
                self.submit("m", plays)
        plays = choose_plays(plan)
        plays[2]["card"] = plays[0]["card"]
        with self.assertRaises(ServiceError):
            self.submit("m", plays)
        with self.assertRaises(ServiceError) as stale:
            self.submit("m", revision=0)
        self.assertEqual(stale.exception.code, "STALE_REVISION")
        with self.assertRaises(ServiceError):
            self.service.get_card_plan(self.sid, "m", token=self.tokens["a"])
        self.submit("m", token=self.tokens["m"])
        with self.assertRaises(ServiceError) as duplicate:
            self.service.dispatch_card_plan(self.sid, {"actor": "m", "plays": choose_plays(plan),
                "expected_revision": plan["revision"]}, token=self.tokens["m"])
        self.assertEqual(duplicate.exception.code, "STALE_REVISION")
        with self.assertRaises(ServiceError):
            self.service.get_card_plan(self.sid, "a", token=self.tokens["a"])
        with self.assertRaises(ServiceError):
            self.service.dispatch_card_plan(self.sid, {"actor": "a", "plays": []}, token=self.admin)

    def test_red_plan_follows_rotating_engine_order(self):
        self.setup_game()
        self.submit("m")
        self.service.unsafe_game(self.sid).protagonist_order = ("b", "c", "a")
        plan = self.service.get_card_plan(self.sid, "a", token=self.admin)
        self.assertEqual([slot["actor"] for slot in plan["slots"]], ["b", "c", "a"])
        result = self.submit("a")
        self.assertEqual([offer["actor"] for offer in result["accepted_actions"]], ["b", "c", "a"])

    def test_http_get_and_post_card_plan(self):
        self.setup_game()
        server = create_server(port=0, service=self.service)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_port)
        try:
            headers = {"Authorization": f"Bearer {self.tokens['m']}", "Content-Type": "application/json"}
            connection.request("GET", f"/v1/games/{self.sid}/card-plan?actor=m", headers=headers)
            response = connection.getresponse()
            plan = json.loads(response.read())
            self.assertEqual(response.status, 200)
            connection.request("POST", f"/v1/games/{self.sid}/card-plan", json.dumps({
                "actor": "m", "expected_revision": plan["revision"], "plays": choose_plays(plan),
            }), headers)
            response = connection.getresponse()
            result = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertEqual(len(result["accepted_actions"]), 3)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join()

    def test_plan_options_are_private_read_only_and_partial_legacy_remains_usable(self):
        self.setup_game()
        before = self.service.get_view(self.sid)
        self.service.get_card_plan(self.sid, "m", token=self.tokens["m"])
        self.assertEqual(self.service.get_view(self.sid), before)
        offer = self.service.get_actions(self.sid, "m", token=self.tokens["m"])["actions"][0]
        self.service.dispatch(self.sid, {"action_id": offer["id"], "expected_revision": before["revision"]}, token=self.tokens["m"])
        self.assertEqual(len(self.service.get_view(self.sid)["state"]["pending"]), 1)
        with self.assertRaises(ServiceError):
            self.service.get_card_plan(self.sid, "m", token=self.tokens["m"])
        self.assertTrue(self.service.get_actions(self.sid, "m", token=self.tokens["m"])["actions"])


class RoomCardPlanTests(unittest.TestCase):
    def setup_room(self, count):
        self.rooms = RoomService()
        created = self.rooms.create({"module": "BTX", "nickname": "Host", "seat": "m", "protagonist_count": count})
        self.code = created["room"]["code"]
        self.host = created["credential"]["admin_token"]
        self.tokens = {"m": created["credential"]["room_token"]}
        for seat in "abc"[:count]:
            joined = self.rooms.join(self.code, {"nickname": seat, "seat": seat})
            self.tokens[seat] = joined["credential"]["room_token"]
        for token in self.tokens.values():
            self.rooms.ready(self.code, {"ready": True}, token=token)
        self.rooms.start(self.code, token=self.host)
        actions = self.rooms.game_actions(self.code, token=self.tokens["m"])
        self.rooms.game_command(self.code, {"action_id": actions["actions"][0]["id"], "expected_revision": actions["revision"]}, token=self.tokens["m"])

    def submit(self, actor):
        plan = self.rooms.game_card_plan(self.code, token=self.tokens[actor])
        return self.rooms.game_submit_card_plan(self.code, {"actor": actor, "expected_revision": plan["revision"],
            "plays": choose_plays(plan)}, token=self.tokens[actor])

    def test_two_player_private_planning_and_one_atomic_update(self):
        self.setup_room(1)
        before = self.rooms.game_view(self.code, token=self.tokens["a"])
        self.rooms.game_card_plan(self.code, token=self.tokens["m"])
        self.assertEqual(self.rooms.game_view(self.code, token=self.tokens["a"]), before)
        result = self.submit("m")
        red_view = self.rooms.game_view(self.code, token=self.tokens["a"])
        self.assertEqual(red_view["revision"], before["revision"] + 3)
        self.assertEqual(len(red_view["state"]["pending"]), 3)
        self.assertTrue(all(play["card"] is None for play in red_view["state"]["pending"]))
        self.assertEqual(result["view"]["state"]["phase"], "protagonists")
        before_red = self.rooms.game_view(self.code, token=self.tokens["m"])
        self.rooms.game_card_plan(self.code, token=self.tokens["a"])
        self.assertEqual(self.rooms.game_view(self.code, token=self.tokens["m"]), before_red)
        result = self.submit("a")
        self.assertEqual(result["view"]["state"]["phase"], "reveal")
        self.assertEqual(len(self.rooms._room(self.code).executors), 7)

    def test_failed_plan_never_publishes_and_success_publishes_complete_state_once(self):
        self.setup_room(1)
        room = self.rooms._room(self.code)
        plan = self.rooms.game_card_plan(self.code, token=self.tokens["m"])
        before = self.rooms.game_view(self.code, token=self.tokens["m"])
        plays = choose_plays(plan)
        invalid = deepcopy(plays)
        invalid[2]["target"] = invalid[0]["target"]
        with patch.object(room.changed, "notify_all", wraps=room.changed.notify_all) as notify:
            with self.assertRaises(ServiceError):
                self.rooms.game_submit_card_plan(self.code, {
                    "actor": "m", "expected_revision": plan["revision"], "plays": invalid,
                }, token=self.tokens["m"])
            notify.assert_not_called()
            self.assertEqual(self.rooms.game_view(self.code, token=self.tokens["m"]), before)
            self.assertEqual(len(room.executors), 1)
            self.submit("m")
            notify.assert_called_once()
        self.assertEqual(len(self.rooms.game_view(self.code)["state"]["pending"]), 3)

    def test_three_and_four_player_red_batch_forbidden_and_single_step_unchanged(self):
        for count in (2, 3):
            with self.subTest(count=count):
                self.setup_room(count)
                self.submit("m")
                with self.assertRaises(ServiceError) as error:
                    self.rooms.game_card_plan(self.code, token=self.tokens["a"])
                self.assertEqual(error.exception.code, "FORBIDDEN")
                with self.assertRaises(ServiceError):
                    self.rooms.game_submit_card_plan(self.code, {"actor": "a"}, token=self.tokens["a"])
                actions = self.rooms.game_actions(self.code, token=self.tokens["a"])
                self.assertTrue(actions["actions"])
                result = self.rooms.game_command(self.code, {"action_id": actions["actions"][0]["id"],
                    "expected_revision": actions["revision"]}, token=self.tokens["a"])
                self.assertEqual(len(result["view"]["state"]["pending"]), 4)

    def test_room_http_token_authority_and_batch_transport(self):
        self.setup_room(1)
        server = create_server(port=0, service=self.rooms.games, room_service=self.rooms)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_port)
        try:
            headers = {"Authorization": f"Bearer {self.tokens['m']}", "Content-Type": "application/json"}
            path = f"/v1/rooms/{self.code}/game/card-plan"
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            plan = json.loads(response.read())
            self.assertEqual(response.status, 200)
            request = {"actor": "m", "expected_revision": plan["revision"], "plays": choose_plays(plan)}
            connection.request("POST", path, json.dumps(request), {
                **headers, "Authorization": f"Bearer {self.tokens['a']}",
            })
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 403)
            connection.request("POST", path, json.dumps(request), headers)
            response = connection.getresponse()
            result = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertEqual(result["view"]["state"]["phase"], "protagonists")
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
