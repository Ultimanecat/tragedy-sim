"""Small standard-library HTTP transport for :mod:`tragedy_sim.service`."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .service import GameService, PROTOCOL_VERSION, ServiceError


MAX_BODY = 1_000_000
DEFAULT_WEB_ROOT = Path(__file__).resolve().parent.parent / "web" / "dist"


def make_handler(service: GameService, *, allowed_origins: tuple[str, ...] = (),
                 static_root: Path | None = None):
    web_root = static_root.resolve() if static_root and static_root.is_dir() else None

    class Handler(BaseHTTPRequestHandler):
        server_version = "TragedySim/1"

        def log_message(self, format, *args):
            return None

        def _origin(self):
            origin = self.headers.get("Origin")
            return origin if origin and origin in allowed_origins else None

        def _headers(self, status, content_type="application/json; charset=utf-8", length=0):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
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
            self._headers(200, content_type, len(body))
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
                if parts == ["v1", "games"]:
                    self._send_json(201, service.create_game(self._json_body()))
                    return
                if len(parts) == 4 and parts[:2] == ["v1", "games"] and parts[3] == "commands":
                    result = service.dispatch(parts[2], self._json_body(), token=self._token())
                    self._send_json(200, result)
                    return
                raise ServiceError("ROUTE_NOT_FOUND", "接口不存在", status=404)
            except Exception as exc:
                self._error(exc)

        def do_DELETE(self):
            try:
                _, parts = self._route()
                if len(parts) == 3 and parts[:2] == ["v1", "games"]:
                    self._send_json(200, service.delete_game(parts[2], token=self._token()))
                    return
                raise ServiceError("ROUTE_NOT_FOUND", "接口不存在", status=404)
            except Exception as exc:
                self._error(exc)

    return Handler


def create_server(host="127.0.0.1", port=8765, *, service=None, allowed_origins=(),
                  static_root: str | Path | None = DEFAULT_WEB_ROOT):
    service = service or GameService()
    root = Path(static_root) if static_root is not None else None
    return ThreadingHTTPServer((host, port), make_handler(
        service, allowed_origins=tuple(allowed_origins), static_root=root))


def serve(host="127.0.0.1", port=8765, *, allowed_origins=()):
    server = create_server(host, port, allowed_origins=allowed_origins)
    print(f"Tragedy Sim Web：http://{host}:{server.server_port}/")
    print(f"JSON 健康检查：http://{host}:{server.server_port}/v1/health")
    print("默认凭据按对局生成；按 Ctrl+C 停止。")
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
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port 必须在 1–65535 之间")
    serve(args.host, args.port, allowed_origins=args.allow_origin)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
