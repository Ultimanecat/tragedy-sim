"""LAN room lifecycle layered over the versioned game service."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import secrets
from threading import Condition, RLock
import time
from typing import Any

from .catalog import MODULES
from .service import GameService, PROTOCOL_VERSION, SEATS, ServiceError


ROOM_ALPHABET = "0123456789"
WAITING_TTL = 2 * 60 * 60
PLAYING_TTL = 24 * 60 * 60
FINISHED_TTL = 6 * 60 * 60
PRESENCE_TTL = 12


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


@dataclass
class _Occupant:
    nickname: str
    token: str
    ready: bool = False
    last_seen: float = field(default_factory=time.monotonic)


@dataclass
class _Room:
    code: str
    module: str
    session_id: str
    game_tokens: dict[str, str]
    game_admin: str
    admin_token: str
    protagonist_count: int
    spectators: bool
    created_at: float
    last_activity: float
    seats: dict[str, _Occupant | None]
    status: str = "waiting"
    revision: int = 0
    human_leader: str = "a"
    logical_leader: str = "a"
    executors: list[dict[str, Any]] = field(default_factory=list)
    lock: RLock = field(default_factory=RLock)
    changed: Condition = field(init=False, repr=False)
    closed: bool = False

    def __post_init__(self) -> None:
        self.changed = Condition(self.lock)


def _object(request: Any, allowed: set[str], required: set[str] = frozenset()) -> dict[str, Any]:
    if not isinstance(request, dict) or set(request) - allowed or not required.issubset(request):
        raise ServiceError("INVALID_REQUEST", "请求字段无效")
    return request


def _nickname(value: Any) -> str:
    if not isinstance(value, str):
        raise ServiceError("INVALID_NICKNAME", "昵称必须是字符串")
    value = value.strip()
    if not 1 <= len(value) <= 24 or any(ord(char) < 32 for char in value):
        raise ServiceError("INVALID_NICKNAME", "昵称长度必须为 1–24 个可见字符")
    return value


def _seat(value: Any) -> str:
    if value not in SEATS:
        raise ServiceError("INVALID_SEAT", "座位必须是 m、a、b 或 c")
    return value


def _protagonist_count(value: Any, module: str) -> int:
    if type(value) is not int or value not in (1, 2, 3):
        raise ServiceError("INVALID_PLAYER_COUNT", "主人公玩家人数必须是 1、2 或 3")
    if module == "LL" and value != 3:
        raise ServiceError("PLAYER_COUNT_NOT_SUPPORTED", "Last Liar 必须由三名主人公玩家参与", status=409)
    return value


class RoomService:
    """Owns lobby state while delegating every game rule to ``GameService``."""

    def __init__(self, games: GameService | None = None, *, clock=time.monotonic):
        self.games = games or GameService()
        self._rooms: dict[str, _Room] = {}
        self._lock = RLock()
        self._clock = clock

    def _cleanup(self) -> None:
        now = self._clock()
        expired: list[_Room] = []
        with self._lock:
            for code, room in list(self._rooms.items()):
                ttl = {"waiting": WAITING_TTL, "playing": PLAYING_TTL,
                       "finished": FINISHED_TTL}[room.status]
                if now - room.last_activity > ttl:
                    expired.append(self._rooms.pop(code))
        for room in expired:
            with room.changed:
                room.closed = True
                room.changed.notify_all()
            try:
                self.games.delete_game(room.session_id, token=room.game_admin)
            except ServiceError:
                pass

    def _new_code(self) -> str:
        for _ in range(100):
            code = "".join(secrets.choice(ROOM_ALPHABET) for _ in range(6))
            if code not in self._rooms:
                return code
        raise ServiceError("ROOM_CAPACITY", "暂时无法分配房间码", status=503)

    def _room(self, code: str) -> _Room:
        self._cleanup()
        if not isinstance(code, str):
            raise ServiceError("ROOM_NOT_FOUND", "房间不存在或已经关闭", status=404)
        with self._lock:
            room = self._rooms.get(code)
        if room is None:
            raise ServiceError("ROOM_NOT_FOUND", "房间不存在或已经关闭", status=404)
        return room

    def _occupant(self, room: _Room, token: str | None, *, touch=True) -> tuple[str, _Occupant]:
        if not isinstance(token, str):
            raise ServiceError("FORBIDDEN", "房间令牌无权执行此操作", status=403)
        for seat, occupant in room.seats.items():
            if occupant and secrets.compare_digest(token, occupant.token):
                if touch:
                    occupant.last_seen = self._clock()
                    room.last_activity = occupant.last_seen
                return seat, occupant
        raise ServiceError("FORBIDDEN", "房间令牌无权执行此操作", status=403)

    @staticmethod
    def _bump(room: _Room) -> None:
        room.revision += 1
        room.changed.notify_all()

    @staticmethod
    def _require_admin(room: _Room, token: str | None) -> None:
        if not isinstance(token, str) or not secrets.compare_digest(token, room.admin_token):
            raise ServiceError("FORBIDDEN", "仅房主可以执行此操作", status=403)

    def _sync_status(self, room: _Room) -> int:
        view = self.games.get_view(room.session_id)
        leader = view["state"]["leader"]
        if leader != room.logical_leader:
            room.logical_leader = leader
            if room.protagonist_count == 2:
                room.human_leader = "b" if room.human_leader == "a" else "a"
            elif room.protagonist_count == 3:
                room.human_leader = leader
            self._bump(room)
        if room.status == "playing" and view["state"]["winner"]:
            room.status = "finished"
            self._bump(room)
        return view["revision"]

    def _payload(self, room: _Room, *, token: str | None = None) -> dict[str, Any]:
        game_revision = self._sync_status(room)
        now = self._clock()
        own_seat = None
        is_host = False
        if isinstance(token, str):
            for seat, occupant in room.seats.items():
                if occupant and secrets.compare_digest(token, occupant.token):
                    own_seat = seat
                    break
            is_host = secrets.compare_digest(token, room.admin_token)
        required = ("m", *SEATS[1:1 + room.protagonist_count])
        return _json_copy({
            "protocol_version": PROTOCOL_VERSION,
            "room": {
                "code": room.code, "module": room.module, "status": room.status,
                "revision": room.revision, "game_revision": game_revision,
                "spectators": room.spectators, "protagonist_count": room.protagonist_count,
                "required_seats": list(required), "human_leader": room.human_leader,
                "logical_leader": room.logical_leader,
                "ready_to_start": all(room.seats[seat] and room.seats[seat].ready for seat in required),
                "seats": {seat: (None if occupant is None else {
                    "nickname": occupant.nickname, "ready": occupant.ready,
                    "connected": now - occupant.last_seen <= PRESENCE_TTL,
                }) for seat, occupant in room.seats.items()},
            },
            "self": None if own_seat is None else {"seat": own_seat},
            "is_host": is_host,
        })

    def create(self, request: Any) -> dict[str, Any]:
        request = _object(request, {"module", "nickname", "seat", "spectators", "protagonist_count"},
                          {"module", "nickname", "seat"})
        module = request["module"]
        if module not in MODULES:
            raise ServiceError("MODULE_NOT_FOUND", "规则集不存在", status=404)
        count = _protagonist_count(request.get("protagonist_count", 3), module)
        nickname, seat = _nickname(request["nickname"]), _seat(request["seat"])
        if seat not in ("m", *SEATS[1:1 + count]):
            raise ServiceError("SEAT_UNAVAILABLE", "该人数模式没有这个参与者席位", status=409)
        spectators = request.get("spectators", True)
        if type(spectators) is not bool:
            raise ServiceError("INVALID_REQUEST", "spectators 必须是布尔值")
        created = self.games.create_game({"module": module})
        now = self._clock()
        player_token = secrets.token_urlsafe(24)
        room = _Room(
            code="", module=module, session_id=created["session_id"],
            game_tokens=created["credentials"]["seats"],
            game_admin=created["credentials"]["admin"],
            admin_token=secrets.token_urlsafe(32), protagonist_count=count, spectators=spectators,
            created_at=now, last_activity=now,
            seats={key: None for key in SEATS},
        )
        room.seats[seat] = _Occupant(nickname, player_token, last_seen=now)
        self._cleanup()
        with self._lock:
            room.code = self._new_code()
            self._rooms[room.code] = room
        with room.lock:
            result = self._payload(room, token=player_token)
        result["credential"] = {"room_token": player_token,
                                "admin_token": room.admin_token, "seat": seat}
        result["is_host"] = True
        return _json_copy(result)

    def get(self, code: str, *, token: str | None = None) -> dict[str, Any]:
        room = self._room(code)
        with room.lock:
            if token:
                try:
                    self._occupant(room, token)
                except ServiceError:
                    self._require_admin(room, token)
                    room.last_activity = self._clock()
            return self._payload(room, token=token)

    def join(self, code: str, request: Any) -> dict[str, Any]:
        request = _object(request, {"nickname", "seat"}, {"nickname", "seat"})
        nickname, seat = _nickname(request["nickname"]), _seat(request["seat"])
        room = self._room(code)
        with room.lock:
            if room.status != "waiting":
                raise ServiceError("ROOM_ALREADY_STARTED", "房间已经开始，不能再入座", status=409)
            if room.seats[seat] is not None:
                raise ServiceError("SEAT_OCCUPIED", "该座位已经有人", status=409)
            if seat not in ("m", *SEATS[1:1 + room.protagonist_count]):
                raise ServiceError("SEAT_UNAVAILABLE", "该人数模式没有这个参与者席位", status=409)
            token = secrets.token_urlsafe(24)
            room.seats[seat] = _Occupant(nickname, token, last_seen=self._clock())
            room.last_activity = self._clock()
            self._bump(room)
            result = self._payload(room, token=token)
            result["credential"] = {"room_token": token, "seat": seat}
            return _json_copy(result)

    def ready(self, code: str, request: Any, *, token: str | None) -> dict[str, Any]:
        request = _object(request, {"ready"}, {"ready"})
        if type(request["ready"]) is not bool:
            raise ServiceError("INVALID_REQUEST", "ready 必须是布尔值")
        room = self._room(code)
        with room.lock:
            _, occupant = self._occupant(room, token)
            if room.status != "waiting":
                raise ServiceError("ROOM_ALREADY_STARTED", "房间已经开始", status=409)
            if occupant.ready != request["ready"]:
                occupant.ready = request["ready"]
                self._bump(room)
            return self._payload(room, token=token)

    def start(self, code: str, *, token: str | None) -> dict[str, Any]:
        room = self._room(code)
        with room.lock:
            self._require_admin(room, token)
            if room.status != "waiting":
                raise ServiceError("ROOM_ALREADY_STARTED", "房间已经开始", status=409)
            required = ("m", *SEATS[1:1 + room.protagonist_count])
            if any(room.seats[seat] is None for seat in required):
                raise ServiceError("ROOM_NOT_FULL", "所需参与者全部入座后才能开始", status=409)
            if any(not room.seats[seat].ready for seat in required):
                raise ServiceError("PLAYERS_NOT_READY", "所有玩家准备后才能开始", status=409)
            room.status = "playing"
            room.last_activity = self._clock()
            self._bump(room)
            return self._payload(room, token=token)

    def leave(self, code: str, *, token: str | None) -> dict[str, Any]:
        room = self._room(code)
        with room.lock:
            seat, _ = self._occupant(room, token, touch=False)
            if room.status != "waiting":
                raise ServiceError("ROOM_ALREADY_STARTED", "对局开始后不能释放座位", status=409)
            room.seats[seat] = None
            self._bump(room)
            room.last_activity = self._clock()
            return self._payload(room)

    def kick(self, code: str, request: Any, *, token: str | None) -> dict[str, Any]:
        request = _object(request, {"seat"}, {"seat"})
        seat = _seat(request["seat"])
        room = self._room(code)
        with room.lock:
            self._require_admin(room, token)
            if room.status != "waiting":
                raise ServiceError("ROOM_ALREADY_STARTED", "对局开始后不能释放座位", status=409)
            if room.seats[seat] is not None:
                room.seats[seat] = None
                self._bump(room)
            room.last_activity = self._clock()
            return self._payload(room, token=token)

    def updates(self, code: str, room_revision: int, game_revision: int,
                *, token: str | None = None) -> dict[str, Any]:
        if type(room_revision) is not int or type(game_revision) is not int:
            raise ServiceError("INVALID_REQUEST", "revision 必须是整数")
        result = self.get(code, token=token)
        result["room_changed"] = result["room"]["revision"] != room_revision
        result["game_changed"] = result["room"]["game_revision"] != game_revision
        return _json_copy(result)

    def wait_for_updates(self, code: str, room_revision: int, game_revision: int, *,
                         token: str | None = None, timeout: float = 15.0) -> dict[str, Any]:
        """Wait for a room/game revision change, returning a heartbeat on timeout."""
        if type(room_revision) is not int or type(game_revision) is not int:
            raise ServiceError("INVALID_REQUEST", "revision 必须是整数")
        if not isinstance(timeout, (int, float)) or not 0 <= timeout <= 30:
            raise ServiceError("INVALID_REQUEST", "timeout 必须在 0–30 秒之间")
        room = self._room(code)
        deadline = time.monotonic() + timeout
        with room.changed:
            if token:
                try:
                    self._occupant(room, token)
                except ServiceError:
                    self._require_admin(room, token)
                    room.last_activity = self._clock()
            while True:
                if room.closed:
                    raise ServiceError("ROOM_NOT_FOUND", "房间不存在或已经关闭", status=404)
                result = self._payload(room, token=token)
                result["room_changed"] = result["room"]["revision"] != room_revision
                result["game_changed"] = result["room"]["game_revision"] != game_revision
                if result["room_changed"] or result["game_changed"]:
                    return _json_copy(result)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return _json_copy(result)
                room.changed.wait(remaining)

    @staticmethod
    def _card_actors(room: _Room, participant: str) -> tuple[str, ...]:
        if participant == "m":
            return ("m",)
        if room.protagonist_count == 1:
            return ("a", "b", "c")
        if room.protagonist_count == 2:
            return (participant, "c") if participant == room.human_leader else (participant,)
        return (participant,)

    @staticmethod
    def _can_control(room: _Room, participant: str, offer: dict[str, Any], state: dict[str, Any]) -> bool:
        actor = offer["actor"]
        if participant == "m":
            return actor == "m"
        if room.protagonist_count == 1:
            return actor in SEATS[1:]
        if room.protagonist_count == 3:
            return actor == participant
        if offer["type"] == "play":
            return actor == participant or (actor == "c" and participant == room.human_leader)
        if actor == state["leader"]:
            return participant == room.human_leader
        return actor == participant

    def _participant_offers(self, room: _Room, participant: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        public = self.games.get_view(room.session_id)
        offers: list[dict[str, Any]] = []
        for actor in SEATS:
            response = self.games.get_actions(room.session_id, actor, token=room.game_admin)
            offers.extend(offer for offer in response["actions"]
                          if self._can_control(room, participant, offer, public["state"]))
        return public, offers

    def game_view(self, code: str, *, token: str | None = None, language="zh") -> dict[str, Any]:
        room = self._room(code)
        with room.lock:
            if token:
                seat, _ = self._occupant(room, token)
                viewer, game_token = seat, room.game_tokens[seat]
            elif room.spectators:
                viewer, game_token = "spectator", None
            else:
                raise ServiceError("FORBIDDEN", "该房间不允许旁观", status=403)
            if room.status == "waiting":
                raise ServiceError("ROOM_NOT_STARTED", "房间尚未开始", status=409)
            result = self.games.get_view(room.session_id, viewer, token=game_token, language=language)
            if viewer == "spectator":
                return result
            state = result["state"]
            card_actors = self._card_actors(room, seat)
            controlled_hands = {}
            private_views = {}
            for actor in card_actors:
                private = self.games.get_view(room.session_id, actor,
                                              token=room.game_tokens[actor], language=language)
                private_views[actor] = private["state"]
                controlled_hands[actor] = private["state"]["hand"]
            for index, placement in enumerate(state["pending"]):
                actor = placement["actor"]
                if actor in private_views:
                    placement["card"] = private_views[actor]["pending"][index]["card"]
            state["controlled_hands"] = controlled_hands
            state["participant"] = {
                "seat": seat, "human_leader": room.human_leader,
                "is_human_leader": seat == room.human_leader,
                "card_actors": list(card_actors),
            }
            return _json_copy(result)

    def game_actions(self, code: str, *, token: str | None) -> dict[str, Any]:
        room = self._room(code)
        with room.lock:
            seat, _ = self._occupant(room, token)
            if room.status == "waiting":
                raise ServiceError("ROOM_NOT_STARTED", "房间尚未开始", status=409)
            public, offers = self._participant_offers(room, seat)
            return _json_copy({"protocol_version": PROTOCOL_VERSION,
                               "session_id": room.session_id, "revision": public["revision"],
                               "actor": seat, "controlled_actors": sorted({o["actor"] for o in offers}),
                               "actions": offers})

    def game_command(self, code: str, request: Any, *, token: str | None) -> dict[str, Any]:
        room = self._room(code)
        with room.lock:
            seat, occupant = self._occupant(room, token)
            if room.status != "playing":
                raise ServiceError("ROOM_NOT_PLAYING", "房间当前不能提交行动", status=409)
            if not isinstance(request, dict) or set(request) != {"action_id", "expected_revision"}:
                raise ServiceError("INVALID_REQUEST", "命令需要 action_id 和 expected_revision")
            if not isinstance(request["action_id"], str) or type(request["expected_revision"]) is not int:
                raise ServiceError("INVALID_REQUEST", "命令字段类型无效")
            public, offers = self._participant_offers(room, seat)
            if request["expected_revision"] != public["revision"]:
                raise ServiceError("STALE_REVISION", "对局状态已经改变，请刷新后重试", status=409,
                                   details={"expected": request["expected_revision"],
                                            "current": public["revision"]})
            if request["action_id"] not in {offer["id"] for offer in offers}:
                raise ServiceError("ACTION_NOT_AVAILABLE", "该行动不属于当前参与者", status=409)
            result = self.games.dispatch(room.session_id, request, token=room.game_admin)
            accepted = result["accepted_action"]
            room.executors.append({"decision": len(room.executors) + 1,
                                   "participant": seat, "nickname": occupant.nickname,
                                   "actor": accepted["actor"]})
            room.last_activity = self._clock()
            self._sync_status(room)
            room.changed.notify_all()
            return result

    def game_snapshot(self, code: str, *, token: str | None) -> dict[str, Any]:
        room = self._room(code)
        with room.lock:
            self._require_admin(room, token)
            return self.games.get_snapshot(room.session_id, token=room.game_admin)

    def game_replay(self, code: str, *, token: str | None, language="zh") -> str:
        room = self._room(code)
        with room.lock:
            self._require_admin(room, token)
            replay = self.games.get_replay(room.session_id, token=room.game_admin, language=language)
            actor_lines = ["# 房间执行者记录：participant 是真人席位，actor 是规则引擎逻辑席位。"]
            actor_lines.extend("# ROOM_ACTOR\t" + json.dumps(item, ensure_ascii=False,
                                                               separators=(",", ":"), sort_keys=True)
                               for item in room.executors)
            lines = replay.splitlines()
            lines[3:3] = actor_lines
            return "\n".join(lines) + "\n"

    def close(self, code: str, *, token: str | None) -> dict[str, Any]:
        room = self._room(code)
        with room.lock:
            self._require_admin(room, token)
            self.games.delete_game(room.session_id, token=room.game_admin)
            room.closed = True
            room.changed.notify_all()
            with self._lock:
                self._rooms.pop(room.code, None)
        return {"protocol_version": PROTOCOL_VERSION, "room_code": room.code, "deleted": True}
