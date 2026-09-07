"""Versioned JSON application boundary around the deterministic game engine.

The domain model deliberately knows nothing about HTTP.  Frontends and future AI
workers consume this service, while transport adapters only translate JSON and
authentication headers.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import secrets
from threading import RLock
from typing import Any
from uuid import uuid4

from .cards import COUNTER_NAMES, LOCATIONS, deck
from .catalog import (CHARACTERS, INCIDENT_NAMES, INCIDENT_RULES, MODULES, PLOTS,
                      PLOT_RULES, ROLE_NAMES, ROLE_RULES, TRAIT_NAMES)
from .engine import RuleError
from .game import Game
from .i18n import label, normalize_language
from .replay import dumps as replay_dumps
from .scenario import example_scenario, validate_scenario


PROTOCOL_VERSION = 1
SEATS = ("m", "a", "b", "c")


class ServiceError(ValueError):
    """Transport-neutral error with a stable code and safe public details."""

    def __init__(self, code: str, message: str, *, status: int = 400,
                 details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}

    def payload(self) -> dict[str, Any]:
        return {"protocol_version": PROTOCOL_VERSION,
                "error": {"code": self.code, "message": self.message,
                          "details": deepcopy(self.details)}}


@dataclass
class _Session:
    game: Game
    tokens: dict[str, str]
    admin_token: str
    revision: int = 0
    lock: RLock = field(default_factory=RLock)


def _json_copy(value: Any) -> Any:
    """Enforce that the public protocol contains plain JSON values only."""
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _language(value: str) -> str:
    try:
        return normalize_language(value)
    except (AttributeError, ValueError) as exc:
        raise ServiceError("UNSUPPORTED_LANGUAGE", str(exc)) from exc


class GameService:
    """In-memory application service shared by local and HTTP clients."""

    def __init__(self):
        self._sessions: dict[str, _Session] = {}
        self._lock = RLock()

    def create_game(self, request: dict[str, Any] | None = None, *, game: Game | None = None) -> dict[str, Any]:
        request = {} if request is None else request
        if not isinstance(request, dict):
            raise ServiceError("INVALID_REQUEST", "请求必须是 JSON 对象")
        if game is not None and request:
            raise ServiceError("INVALID_REQUEST", "不能同时传入现有对局和创建参数")
        if game is not None and not isinstance(game, Game):
            raise ServiceError("INVALID_REQUEST", "现有对局必须是 Game 对象")
        try:
            if game is None:
                allowed = {"module", "scenario", "snapshot"}
                if set(request) - allowed or sum(key in request for key in allowed) > 1:
                    raise ServiceError("INVALID_REQUEST", "只能指定 module、scenario 或 snapshot 中的一项")
                if "snapshot" in request:
                    game = self._game_from_snapshot(request["snapshot"])
                elif "scenario" in request:
                    game = Game(validate_scenario(request["scenario"]))
                else:
                    module = request.get("module", "FS")
                    if not isinstance(module, str):
                        raise ServiceError("INVALID_REQUEST", "module 必须是字符串")
                    game = Game(example_scenario(module))
        except ServiceError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ServiceError("INVALID_SCENARIO", str(exc)) from exc
        session_id = uuid4().hex
        tokens = {seat: secrets.token_urlsafe(24) for seat in SEATS}
        record = _Session(game=game, tokens=tokens, admin_token=secrets.token_urlsafe(32),
                          revision=len(game.history))
        with self._lock:
            self._sessions[session_id] = record
        return _json_copy({
            "protocol_version": PROTOCOL_VERSION,
            "session_id": session_id,
            "revision": record.revision,
            "credentials": {"admin": record.admin_token, "seats": tokens},
            "view": self._view_payload(session_id, record, "spectator"),
        })

    def list_modules(self, language: str = "zh") -> dict[str, Any]:
        language = _language(language)
        return _json_copy({
            "protocol_version": PROTOCOL_VERSION,
            "language": language,
            "modules": [{"id": module, "name": label("modules", module, language, fallback=spec.name),
                         "cli_supported": spec.cli_supported,
                         "gui_supported": spec.gui_supported,
                         "final_guess": spec.final_guess,
                         "early_final_guess": spec.early_final_guess}
                        for module, spec in MODULES.items()],
        })

    def get_catalog(self, module: str, language: str = "zh") -> dict[str, Any]:
        if module not in MODULES:
            raise ServiceError("MODULE_NOT_FOUND", "规则集不存在", status=404)
        language = _language(language)
        spec = MODULES[module]
        role_ids = {"ordinary"}
        for plot in spec.plots:
            role_ids.update(PLOTS[plot][2])
        if "hideous" in spec.plots:
            role_ids.add("curmudgeon")
        return _json_copy({
            "protocol_version": PROTOCOL_VERSION,
            "language": language,
            "module": {"id": module, "name": label("modules", module, language, fallback=spec.name),
                       "subplot_count": spec.subplot_count,
                       "capabilities": {"final_guess": spec.final_guess,
                                        "early_final_guess": spec.early_final_guess}},
            "locations": [{"id": key, "name": label("locations", key, language, fallback=value)} for key, value in LOCATIONS.items()],
            "counters": [{"id": key, "name": label("counters", key, language, fallback=value)} for key, value in COUNTER_NAMES.items()],
            "plots": [{"id": plot, "name": PLOTS[plot][0], "type": PLOTS[plot][1],
                       "rule": PLOT_RULES[plot], "roles": PLOTS[plot][2]}
                      for plot in spec.plots],
            "roles": [{"id": role, "name": label("roles", role, language, fallback=ROLE_NAMES[role]), "rule": ROLE_RULES[role]}
                      for role in ROLE_NAMES if role in role_ids],
            "incidents": [{"id": kind, "name": label("incidents", kind, language, fallback=INCIDENT_NAMES[kind]),
                           "rule": INCIDENT_RULES[kind]} for kind in spec.incidents],
            "characters": [{"id": cid, **asdict(CHARACTERS[cid]),
                            "name": label("characters", cid, language, fallback=CHARACTERS[cid].name),
                            "traits": [{"id": trait, "name": label("traits", trait, language, fallback=TRAIT_NAMES[trait])}
                                       for trait in CHARACTERS[cid].traits]}
                           for cid in spec.characters],
            "cards": {actor: [{"id": cid, **asdict(card)} for cid, card in deck(actor, module).items()]
                      for actor in SEATS},
        })

    def _game_from_snapshot(self, snapshot: Any) -> Game:
        if (not isinstance(snapshot, dict) or set(snapshot) != {"version", "scenario", "commands"}
                or snapshot["version"] != 1 or not isinstance(snapshot["commands"], list)):
            raise ServiceError("INVALID_SNAPSHOT", "存档结构或版本不受支持")
        try:
            game = Game(snapshot["scenario"])
            for raw in snapshot["commands"]:
                if not isinstance(raw, dict) or "actor" not in raw or "action" not in raw:
                    raise ServiceError("INVALID_SNAPSHOT", "存档包含无效命令")
                command = dict(raw)
                game.dispatch(command.pop("actor"), command.pop("action"), **command)
            return game
        except ServiceError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ServiceError("INVALID_SNAPSHOT", f"无法重演存档：{exc}") from exc

    def _session(self, session_id: str) -> _Session:
        with self._lock:
            result = self._sessions.get(session_id)
        if result is None:
            raise ServiceError("SESSION_NOT_FOUND", "对局不存在或已经关闭", status=404)
        return result

    @staticmethod
    def _authorized(record: _Session, token: str | None, seat: str | None = None,
                    *, admin=False) -> bool:
        if not isinstance(token, str):
            return False
        if secrets.compare_digest(token, record.admin_token):
            return True
        if admin or seat not in record.tokens:
            return False
        return secrets.compare_digest(token, record.tokens[seat])

    def _require(self, record: _Session, token: str | None, seat: str | None = None,
                 *, admin=False) -> None:
        if not self._authorized(record, token, seat, admin=admin):
            raise ServiceError("FORBIDDEN", "访问令牌无权执行此操作", status=403)

    @staticmethod
    def _token_actors(record: _Session, token: str | None) -> tuple[str, ...]:
        """Resolve command authority before inspecting any seat's legal actions."""
        if not isinstance(token, str):
            raise ServiceError("FORBIDDEN", "访问令牌无权执行此操作", status=403)
        if secrets.compare_digest(token, record.admin_token):
            return SEATS
        for seat, seat_token in record.tokens.items():
            if secrets.compare_digest(token, seat_token):
                return (seat,)
        raise ServiceError("FORBIDDEN", "访问令牌无权执行此操作", status=403)

    @staticmethod
    def _view_payload(session_id: str, record: _Session, viewer: str, language: str = "zh") -> dict[str, Any]:
        return {"protocol_version": PROTOCOL_VERSION, "session_id": session_id,
                "revision": record.revision, "viewer": viewer,
                "state": record.game.view(viewer, language)}

    def get_view(self, session_id: str, viewer="spectator", *, token: str | None = None,
                 language: str = "zh") -> dict[str, Any]:
        language = _language(language)
        record = self._session(session_id)
        if viewer != "spectator":
            if viewer not in SEATS:
                raise ServiceError("INVALID_VIEWER", "viewer 必须是 spectator 或有效座位")
            self._require(record, token, viewer)
        with record.lock:
            return _json_copy(self._view_payload(session_id, record, viewer, language))

    def _action_label(self, game: Game, command: dict[str, Any]) -> str:
        action = command["action"]
        if action == "choose":
            options = game.options(command["actor"])
            index = command["index"]
            return options[index - 1]["label"]
        if action == "play":
            return f"{deck(command['actor'], game.module)[command['card']].name} → {game.name(command['target'])}"
        if action == "guess":
            return f"{game.name(command['character'])}是{ROLE_NAMES[command['role']]}"
        if action == "final":
            return "提前进入最终猜测"
        return {"next": "进入下一阶段", "resolve": "揭示并结算行动牌"}.get(action, action)

    def _action_offer(self, session_id: str, record: _Session,
                      command: dict[str, Any]) -> dict[str, Any]:
        action = command["action"]
        parameters = {key: value for key, value in command.items()
                      if key not in ("actor", "action", "index")}
        fingerprint = {"session": session_id, "revision": record.revision,
                       "command": command}
        action_id = hashlib.sha256(_canonical(fingerprint).encode("utf-8")).hexdigest()[:24]
        return {"id": action_id, "actor": command["actor"], "type": action,
                "parameters": parameters, "label": self._action_label(record.game, command)}

    def _offers(self, session_id: str, record: _Session, actor: str) -> list[tuple[dict, dict]]:
        commands = record.game.legal_actions(actor)
        return [(self._action_offer(session_id, record, command), command) for command in commands]

    def get_actions(self, session_id: str, actor: str, *, token: str | None) -> dict[str, Any]:
        if actor not in SEATS:
            raise ServiceError("INVALID_ACTOR", "actor 必须是有效座位")
        record = self._session(session_id)
        self._require(record, token, actor)
        with record.lock:
            return _json_copy({"protocol_version": PROTOCOL_VERSION, "session_id": session_id,
                               "revision": record.revision, "actor": actor,
                               "actions": [offer for offer, _ in self._offers(session_id, record, actor)]})

    def dispatch(self, session_id: str, request: dict[str, Any], *, token: str | None) -> dict[str, Any]:
        if not isinstance(request, dict) or set(request) != {"action_id", "expected_revision"}:
            raise ServiceError("INVALID_REQUEST", "命令需要 action_id 和 expected_revision")
        action_id, expected = request["action_id"], request["expected_revision"]
        if not isinstance(action_id, str) or type(expected) is not int:
            raise ServiceError("INVALID_REQUEST", "命令字段类型无效")
        record = self._session(session_id)
        with record.lock:
            actors = self._token_actors(record, token)
            if expected != record.revision:
                raise ServiceError("STALE_REVISION", "对局状态已经改变，请刷新后重试", status=409,
                                   details={"expected": expected, "current": record.revision})
            matches = [(offer, command) for seat in actors
                       for offer, command in self._offers(session_id, record, seat)
                       if offer["id"] == action_id]
            if not matches:
                raise ServiceError("ACTION_NOT_AVAILABLE", "该行动在当前状态下不可用", status=409)
            offer, command = matches[0]
            try:
                record.game.dispatch(command["actor"], command["action"],
                                     **{key: value for key, value in command.items()
                                        if key not in ("actor", "action")})
            except RuleError as exc:
                raise ServiceError("RULE_VIOLATION", str(exc), status=409) from exc
            record.revision += 1
            return _json_copy({"protocol_version": PROTOCOL_VERSION,
                               "session_id": session_id, "revision": record.revision,
                               "accepted_action": offer,
                               "view": self._view_payload(session_id, record, "spectator")})

    def get_snapshot(self, session_id: str, *, token: str | None) -> dict[str, Any]:
        record = self._session(session_id)
        self._require(record, token, admin=True)
        with record.lock:
            snapshot = {"version": 1, "scenario": record.game.scenario,
                        "commands": record.game.history}
            return _json_copy({"protocol_version": PROTOCOL_VERSION,
                               "session_id": session_id, "revision": record.revision,
                               "snapshot": snapshot})

    def get_replay(self, session_id: str, *, token: str | None, language: str = "zh") -> str:
        language = _language(language)
        record = self._session(session_id)
        self._require(record, token, admin=True)
        with record.lock:
            try:
                return replay_dumps(record.game, language)
            except RuleError as exc:
                raise ServiceError("REPLAY_NOT_READY", str(exc), status=409) from exc

    def delete_game(self, session_id: str, *, token: str | None) -> dict[str, Any]:
        record = self._session(session_id)
        self._require(record, token, admin=True)
        with record.lock:
            with self._lock:
                self._sessions.pop(session_id, None)
        return {"protocol_version": PROTOCOL_VERSION, "session_id": session_id, "deleted": True}

    def unsafe_game(self, session_id: str) -> Game:
        """Compatibility escape hatch for legacy tests; never exposed by HTTP."""
        return self._session(session_id).game


class LocalGameClient:
    """Python frontend client using exactly the same JSON service contract."""

    def __init__(self, service: GameService, created: dict[str, Any], language: str = "zh"):
        self.service = service
        self.session_id = created["session_id"]
        self.admin_token = created["credentials"]["admin"]
        self.seat_tokens = dict(created["credentials"]["seats"])
        self.revision = created["revision"]
        self.language = normalize_language(language)

    @classmethod
    def from_game(cls, game: Game | None = None) -> "LocalGameClient":
        service = GameService()
        return cls(service, service.create_game(game=game or Game()))

    @classmethod
    def from_scenario(cls, scenario: dict[str, Any]) -> "LocalGameClient":
        service = GameService()
        return cls(service, service.create_game({"scenario": scenario}))

    @classmethod
    def from_snapshot_file(cls, path: str | Path) -> "LocalGameClient":
        snapshot = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        service = GameService()
        return cls(service, service.create_game({"snapshot": snapshot}))

    @property
    def game(self) -> Game:
        return self.service.unsafe_game(self.session_id)

    def view(self, viewer="spectator") -> dict[str, Any]:
        token = None if viewer == "spectator" else self.seat_tokens[viewer]
        payload = self.service.get_view(self.session_id, viewer, token=token, language=self.language)
        self.revision = payload["revision"]
        return payload["state"]

    def actions(self, actor: str) -> list[dict[str, Any]]:
        payload = self.service.get_actions(self.session_id, actor, token=self.seat_tokens[actor])
        self.revision = payload["revision"]
        return payload["actions"]

    def dispatch_id(self, actor: str, action_id: str) -> dict[str, Any]:
        payload = self.service.dispatch(
            self.session_id, {"action_id": action_id, "expected_revision": self.revision},
            token=self.seat_tokens[actor])
        self.revision = payload["revision"]
        return payload

    def dispatch(self, actor: str, action: str, **parameters) -> dict[str, Any]:
        offers = self.actions(actor)
        candidates = [offer for offer in offers if offer["type"] == action]
        if action == "choose" and "index" in parameters:
            index = parameters["index"]
            candidates = candidates[index - 1:index] if type(index) is int and index > 0 else []
        else:
            candidates = [offer for offer in candidates if offer["parameters"] == parameters]
        if len(candidates) != 1:
            raise RuleError("该操作不在服务端返回的当前合法行动中")
        return self.dispatch_id(actor, candidates[0]["id"])

    def save(self, path: str | Path) -> None:
        snapshot = self.service.get_snapshot(self.session_id, token=self.admin_token)["snapshot"]
        with Path(path).open("x", encoding="utf-8") as stream:
            json.dump(snapshot, stream, ensure_ascii=False, indent=2)

    def save_replay(self, path: str | Path) -> None:
        text = self.service.get_replay(self.session_id, token=self.admin_token, language=self.language)
        with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
