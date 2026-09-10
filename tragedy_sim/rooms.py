"""LAN room lifecycle layered over the versioned game service."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import secrets
from threading import RLock
import time
from typing import Any

from .catalog import MODULES
from .service import GameService, PROTOCOL_VERSION, SEATS, ServiceError


ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
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
    spectators: bool
    created_at: float
    last_activity: float
    seats: dict[str, _Occupant | None]
    status: str = "waiting"
    revision: int = 0
    lock: RLock = field(default_factory=RLock)


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
            room = self._rooms.get(code.upper())
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
    def _require_admin(room: _Room, token: str | None) -> None:
        if not isinstance(token, str) or not secrets.compare_digest(token, room.admin_token):
            raise ServiceError("FORBIDDEN", "仅房主可以执行此操作", status=403)

    def _sync_status(self, room: _Room) -> int:
        view = self.games.get_view(room.session_id)
        if room.status == "playing" and view["state"]["winner"]:
            room.status = "finished"
            room.revision += 1
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
        return _json_copy({
            "protocol_version": PROTOCOL_VERSION,
            "room": {
                "code": room.code, "module": room.module, "status": room.status,
                "revision": room.revision, "game_revision": game_revision,
                "spectators": room.spectators,
                "seats": {seat: (None if occupant is None else {
                    "nickname": occupant.nickname, "ready": occupant.ready,
                    "connected": now - occupant.last_seen <= PRESENCE_TTL,
                }) for seat, occupant in room.seats.items()},
            },
            "self": None if own_seat is None else {"seat": own_seat},
            "is_host": is_host,
        })

    def create(self, request: Any) -> dict[str, Any]:
        request = _object(request, {"module", "nickname", "seat", "spectators"},
                          {"module", "nickname", "seat"})
        module = request["module"]
        if module not in MODULES:
            raise ServiceError("MODULE_NOT_FOUND", "规则集不存在", status=404)
        nickname, seat = _nickname(request["nickname"]), _seat(request["seat"])
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
            admin_token=secrets.token_urlsafe(32), spectators=spectators,
            created_at=now, last_activity=now,
            seats={key: None for key in SEATS},
        )
        room.seats[seat] = _Occupant(nickname, player_token, last_seen=now)
        self._cleanup()
        with self._lock:
            room.code = self._new_code()
            self._rooms[room.code] = room
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
            token = secrets.token_urlsafe(24)
            room.seats[seat] = _Occupant(nickname, token, last_seen=self._clock())
            room.last_activity = self._clock()
            room.revision += 1
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
                room.revision += 1
            return self._payload(room, token=token)

    def start(self, code: str, *, token: str | None) -> dict[str, Any]:
        room = self._room(code)
        with room.lock:
            self._require_admin(room, token)
            if room.status != "waiting":
                raise ServiceError("ROOM_ALREADY_STARTED", "房间已经开始", status=409)
            if any(occupant is None for occupant in room.seats.values()):
                raise ServiceError("ROOM_NOT_FULL", "四个座位坐满后才能开始", status=409)
            if any(not occupant.ready for occupant in room.seats.values() if occupant):
                raise ServiceError("PLAYERS_NOT_READY", "所有玩家准备后才能开始", status=409)
            room.status = "playing"
            room.last_activity = self._clock()
            room.revision += 1
            return self._payload(room, token=token)

    def leave(self, code: str, *, token: str | None) -> dict[str, Any]:
        room = self._room(code)
        with room.lock:
            seat, _ = self._occupant(room, token, touch=False)
            if room.status != "waiting":
                raise ServiceError("ROOM_ALREADY_STARTED", "对局开始后不能释放座位", status=409)
            room.seats[seat] = None
            room.revision += 1
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
                room.revision += 1
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
            return self.games.get_view(room.session_id, viewer, token=game_token, language=language)

    def game_actions(self, code: str, *, token: str | None) -> dict[str, Any]:
        room = self._room(code)
        with room.lock:
            seat, _ = self._occupant(room, token)
            if room.status == "waiting":
                raise ServiceError("ROOM_NOT_STARTED", "房间尚未开始", status=409)
            return self.games.get_actions(room.session_id, seat, token=room.game_tokens[seat])

    def game_command(self, code: str, request: Any, *, token: str | None) -> dict[str, Any]:
        room = self._room(code)
        with room.lock:
            seat, _ = self._occupant(room, token)
            if room.status != "playing":
                raise ServiceError("ROOM_NOT_PLAYING", "房间当前不能提交行动", status=409)
            result = self.games.dispatch(room.session_id, request, token=room.game_tokens[seat])
            room.last_activity = self._clock()
            self._sync_status(room)
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
            return self.games.get_replay(room.session_id, token=room.game_admin, language=language)

    def close(self, code: str, *, token: str | None) -> dict[str, Any]:
        room = self._room(code)
        with room.lock:
            self._require_admin(room, token)
            self.games.delete_game(room.session_id, token=room.game_admin)
            with self._lock:
                self._rooms.pop(room.code, None)
        return {"protocol_version": PROTOCOL_VERSION, "room_code": room.code, "deleted": True}
