"""Small standard-library HTTP transport for :mod:`tragedy_sim.service`."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import ipaddress
from pathlib import Path
import socket
from collections import defaultdict, deque
from threading import Lock
import time
from urllib.parse import parse_qs, unquote, urlparse

from .rooms import RoomService
from .service import GameService, PROTOCOL_VERSION, ServiceError


MAX_BODY = 1_000_000
DEFAULT_WEB_ROOT = Path(__file__).resolve().parent.parent / "web" / "dist"


class TragedyHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64


def make_handler(service: GameService, rooms: RoomService | None = None, *, allowed_origins: tuple[str, ...] = (),
                 static_root: Path | None = None):
    web_root = static_root.resolve() if static_root and static_root.is_dir() else None
    rooms = rooms or RoomService(service)
    request_times: dict[tuple[str, bool], deque[float]] = defaultdict(deque)
    rate_lock = Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "TragedySim/1"

        def log_message(self, format, *args):
            return None

        def _origin(self):
            origin = self.headers.get("Origin")
            return origin if origin and origin in allowed_origins else None

        def _headers(self, status, content_type="application/json; charset=utf-8", length=0,
                     cache_control="no-store"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", cache_control)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self'; style-src 'self'; "
                             "img-src 'self' data:; connect-src 'self'")
            origin = self._origin()
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.end_headers()

        def _send_json(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._headers(status, length=len(body))
            self.wfile.write(body)

        def _send_text(self, status, value):
            body = value.encode("utf-8")
            self._headers(status, "text/plain; charset=utf-8", len(body))
            self.wfile.write(body)

        def _error(self, exc):
            if isinstance(exc, ServiceError):
                self._send_json(exc.status, exc.payload())
            else:
                self._send_json(500, {"protocol_version": PROTOCOL_VERSION,
                                      "error": {"code": "INTERNAL_ERROR",
                                                "message": "服务器内部错误", "details": {}}})

        def _token(self):
            value = self.headers.get("Authorization", "")
            return value[7:] if value.startswith("Bearer ") else None

        def _json_body(self):
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                raise ServiceError("INVALID_REQUEST", "请求缺少 Content-Length")
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise ServiceError("INVALID_REQUEST", "Content-Length 无效") from exc
            if not 0 <= length <= MAX_BODY:
                raise ServiceError("REQUEST_TOO_LARGE", "请求体过大", status=413)
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ServiceError("INVALID_JSON", "请求体不是有效 UTF-8 JSON") from exc

        def _route(self):
            parsed = urlparse(self.path)
            parts = [part for part in parsed.path.split("/") if part]
            return parsed, parts

        def _rate_limit(self):
            if not self.path.startswith("/v1/"):
                return
            now = time.monotonic()
            address = self.client_address[0]
            authenticated = self.headers.get("Authorization", "").startswith("Bearer ")
            with rate_lock:
                recent = request_times[(address, authenticated)]
                while recent and now - recent[0] > 60:
                    recent.popleft()
                limit = 5000 if authenticated else 360
                if len(recent) >= limit:
                    raise ServiceError("RATE_LIMITED", "请求过于频繁，请稍后重试", status=429)
                recent.append(now)

        def _send_static(self, path):
            if web_root is None:
                return False
            relative = unquote(path).lstrip("/") or "index.html"
            candidate = (web_root / relative).resolve()
            if not candidate.is_relative_to(web_root):
                raise ServiceError("ROUTE_NOT_FOUND", "接口不存在", status=404)
            if not candidate.is_file():
                candidate = web_root / "index.html"
            if not candidate.is_file():
                return False
            body = candidate.read_bytes()
            content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
                content_type += "; charset=utf-8"
            cache_control = ("public, max-age=31536000, immutable"
                             if relative.startswith("game-assets/") and candidate.suffix == ".webp"
                             else "no-store")
            self._headers(200, content_type, len(body), cache_control)
            self.wfile.write(body)
            return True

        def do_OPTIONS(self):
            origin = self._origin()
            if not origin:
                self._send_json(403, ServiceError("ORIGIN_FORBIDDEN", "不允许该网页来源", status=403).payload())
                return
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Vary", "Origin")
            self.end_headers()

        def do_GET(self):
            try:
                parsed, parts = self._route()
                self._rate_limit()
                if not parts or parts[0] != "v1":
                    if self._send_static(parsed.path):
                        return
                    raise ServiceError("ROUTE_NOT_FOUND", "接口不存在", status=404)
                if parts == ["v1", "health"]:
                    self._send_json(200, {"protocol_version": PROTOCOL_VERSION, "status": "ok"})
                    return
                if parts == ["v1", "modules"]:
                    language = parse_qs(parsed.query).get("lang", ["zh"])[0]
                    self._send_json(200, service.list_modules(language))
                    return
                if len(parts) == 3 and parts[:2] == ["v1", "catalog"]:
                    language = parse_qs(parsed.query).get("lang", ["zh"])[0]
                    self._send_json(200, service.get_catalog(parts[2], language))
                    return
                if len(parts) >= 3 and parts[:2] == ["v1", "rooms"]:
                    code = parts[2]
                    query = parse_qs(parsed.query)
                    if len(parts) == 3:
                        self._send_json(200, rooms.get(code, token=self._token()))
                        return
                    if len(parts) == 4 and parts[3] == "updates":
                        try:
                            room_revision = int(query.get("room_revision", ["-1"])[0])
                            game_revision = int(query.get("game_revision", ["-1"])[0])
                        except ValueError as exc:
                            raise ServiceError("INVALID_REQUEST", "revision 必须是整数") from exc
                        self._send_json(200, rooms.updates(code, room_revision, game_revision,
                                                           token=self._token()))
                        return
                    if len(parts) == 5 and parts[3] == "game":
                        resource = parts[4]
                        if resource == "view":
                            language = query.get("lang", ["zh"])[0]
                            self._send_json(200, rooms.game_view(code, token=self._token(), language=language))
                        elif resource == "actions":
                            self._send_json(200, rooms.game_actions(code, token=self._token()))
                        elif resource == "snapshot":
                            self._send_json(200, rooms.game_snapshot(code, token=self._token()))
                        elif resource == "replay":
                            language = query.get("lang", ["zh"])[0]
                            self._send_text(200, rooms.game_replay(code, token=self._token(), language=language))
                        else:
                            raise ServiceError("ROUTE_NOT_FOUND", "接口不存在", status=404)
                        return
                if len(parts) != 4 or parts[:2] != ["v1", "games"]:
                    raise ServiceError("ROUTE_NOT_FOUND", "接口不存在", status=404)
                session_id, resource = parts[2], parts[3]
                query = parse_qs(parsed.query)
                if resource == "view":
                    viewer = query.get("viewer", ["spectator"])[0]
                    language = query.get("lang", ["zh"])[0]
                    result = service.get_view(session_id, viewer, token=self._token(), language=language)
                    self._send_json(200, result)
                elif resource == "actions":
                    actor = query.get("actor", [""])[0]
                    self._send_json(200, service.get_actions(session_id, actor, token=self._token()))
                elif resource == "snapshot":
                    self._send_json(200, service.get_snapshot(session_id, token=self._token()))
                elif resource == "replay":
                    language = query.get("lang", ["zh"])[0]
                    self._send_text(200, service.get_replay(session_id, token=self._token(), language=language))
                else:
                    raise ServiceError("ROUTE_NOT_FOUND", "接口不存在", status=404)
            except Exception as exc:
                self._error(exc)

        def do_POST(self):
            try:
                _, parts = self._route()
                self._rate_limit()
                if parts == ["v1", "games"]:
                    self._send_json(201, service.create_game(self._json_body()))
                    return
                if len(parts) == 4 and parts[:2] == ["v1", "games"] and parts[3] == "commands":
                    result = service.dispatch(parts[2], self._json_body(), token=self._token())
                    self._send_json(200, result)
                    return
                if parts == ["v1", "rooms"]:
                    self._send_json(201, rooms.create(self._json_body()))
                    return
                if len(parts) == 4 and parts[:2] == ["v1", "rooms"]:
                    code, action = parts[2], parts[3]
                    if action == "join":
                        result, status = rooms.join(code, self._json_body()), 201
                    elif action == "ready":
                        result, status = rooms.ready(code, self._json_body(), token=self._token()), 200
                    elif action == "start":
                        result, status = rooms.start(code, token=self._token()), 200
                    elif action == "leave":
                        result, status = rooms.leave(code, token=self._token()), 200
                    elif action == "kick":
                        result, status = rooms.kick(code, self._json_body(), token=self._token()), 200
                    else:
                        raise ServiceError("ROUTE_NOT_FOUND", "接口不存在", status=404)
                    self._send_json(status, result)
                    return
                if len(parts) == 5 and parts[:2] == ["v1", "rooms"] and parts[3:] == ["game", "commands"]:
                    self._send_json(200, rooms.game_command(parts[2], self._json_body(), token=self._token()))
                    return
                raise ServiceError("ROUTE_NOT_FOUND", "接口不存在", status=404)
            except Exception as exc:
                self._error(exc)

        def do_DELETE(self):
            try:
                _, parts = self._route()
                self._rate_limit()
                if len(parts) == 3 and parts[:2] == ["v1", "games"]:
                    self._send_json(200, service.delete_game(parts[2], token=self._token()))
                    return
                if len(parts) == 3 and parts[:2] == ["v1", "rooms"]:
                    self._send_json(200, rooms.close(parts[2], token=self._token()))
                    return
                raise ServiceError("ROUTE_NOT_FOUND", "接口不存在", status=404)
            except Exception as exc:
                self._error(exc)

    return Handler


def create_server(host="127.0.0.1", port=8765, *, service=None, room_service=None, allowed_origins=(),
                  static_root: str | Path | None = DEFAULT_WEB_ROOT):
    service = service or GameService()
    room_service = room_service or RoomService(service)
    root = Path(static_root) if static_root is not None else None
    return TragedyHTTPServer((host, port), make_handler(
        service, room_service, allowed_origins=tuple(allowed_origins), static_root=root))


def _lan_addresses(port: int) -> list[str]:
    addresses = set()
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = item[4][0]
            if ipaddress.ip_address(address).is_private and not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass
    return [f"http://{address}:{port}/" for address in sorted(addresses)]


def serve(host="127.0.0.1", port=8765, *, allowed_origins=(), lan=False):
    server = create_server(host, port, allowed_origins=allowed_origins)
    port = server.server_port
    print(f"Tragedy Sim Web：http://127.0.0.1:{port}/")
    if lan:
        addresses = _lan_addresses(port)
        if addresses:
            print("同一 Wi-Fi 的手机请打开：")
            for address in addresses:
                print(f"  {address}")
        else:
            print("未自动发现局域网 IPv4 地址；请用 ipconfig 查询主机地址。")
        print("若手机无法访问，请允许 Python 通过 Windows 防火墙，并确认 Wi-Fi 未启用访客/客户端隔离。")
    print(f"JSON 健康检查：http://127.0.0.1:{port}/v1/health")
    print("按 Ctrl+C 停止；关闭进程后内存中的房间会消失。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="悲剧轮回 JSON/HTTP 游戏服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--allow-origin", action="append", default=[])
    parser.add_argument("--lan", action="store_true", help="监听局域网并显示可分享地址")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port 必须在 1–65535 之间")
    host = "0.0.0.0" if args.lan else args.host
    serve(host, args.port, allowed_origins=args.allow_origin, lan=args.lan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
