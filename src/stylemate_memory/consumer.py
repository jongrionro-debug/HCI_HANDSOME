"""Loopback-only consumer entry point. No directory listing or public user API."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sqlite3
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from .app import ConsumerService, _error
from .errors import StyleMateError
from .settings import ConsumerSettings


MAX_BODY_BYTES = 24000
ASSETS = {
    "/consumer.css": ("consumer.css", "text/css; charset=utf-8"),
    "/consumer.js": ("consumer.js", "text/javascript; charset=utf-8"),
    "/consumer-http.js": ("consumer-http.js", "text/javascript; charset=utf-8"),
}


def _decode(data: bytes) -> Any:
    def unique(pairs: Any) -> dict[str, Any]:
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate field")
            value[key] = item
        return value
    def constant(value: str) -> Any:
        raise ValueError("non-finite number")
    return json.loads(data.decode("utf-8"), object_pairs_hook=unique, parse_constant=constant)


def make_server(service: ConsumerService, port: int = 8766) -> ThreadingHTTPServer:
    root = Path(__file__).parent

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def _allowed(self) -> bool:
            hosts = self.headers.get_all("Host", [])
            origins = self.headers.get_all("Origin", [])
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            return (len(hosts) == 1 and hosts[0] in allowed and len(origins) <= 1
                    and (not origins or origins[0] == "http://" + hosts[0]))

        def _send(self, status: int, body: Any, content_type: str = "application/json; charset=utf-8") -> None:
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _fail(self, status: int, code: str) -> None:
            self._send(status, {"error": _error(StyleMateError(code))})

        def do_GET(self) -> None:
            if not self._allowed():
                self._fail(403, "invalid_input")
                return
            try:
                url = urlsplit(self.path)
                if url.scheme or url.netloc or url.fragment:
                    raise StyleMateError("invalid_input")
                query = parse_qs(url.query, keep_blank_values=True, strict_parsing=True)
                if url.path in ("/", "/index.html", "/consumer.html") and not query:
                    # E's fixture assets stay untouched. Only the served entry
                    # chooses A's real local command/state adapter.
                    html = (root / "consumer.html").read_text(encoding="utf-8")
                    html = html.replace('data-adapter="fixture"', 'data-adapter="http"').replace('./consumer.js', './consumer-http.js')
                    self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
                elif url.path in ASSETS and not query:
                    name, mime = ASSETS[url.path]
                    self._send(200, (root / name).read_bytes(), mime)
                elif url.path == "/api/state":
                    if set(query) - {"request_id"} or any(len(v) != 1 or not v[0] for v in query.values()):
                        raise StyleMateError("invalid_input")
                    self._send(200, service.state(query.get("request_id", [None])[0]))
                elif url.path.startswith("/api/images/"):
                    image_id = unquote(url.path[len("/api/images/"):])
                    if (set(query) != {"version"} or len(query["version"]) != 1
                            or not re.fullmatch(r"[1-9][0-9]{0,9}", query["version"][0])
                            or not image_id or "/" in image_id or "\\" in image_id or "\0" in image_id or image_id in (".", "..")):
                        raise StyleMateError("invalid_input")
                    data, mime = service.image(image_id, int(query["version"][0]))
                    self._send(200, data, mime)
                else:
                    self._fail(404, "not_found")
            except StyleMateError as exc:
                self._send(404 if exc.code == "not_found" else 409 if exc.code in ("stale_context", "version_conflict", "request_expired") else 400,
                           {"error": _error(exc)})
            except (ValueError, UnicodeError, RecursionError):
                self._fail(400, "invalid_input")
            except (OSError, sqlite3.Error, RuntimeError):
                self._fail(500, "storage_failed")

        def do_POST(self) -> None:
            self.close_connection = True
            if not self._allowed():
                self._fail(403, "invalid_input")
                return
            if self.path != "/api/command":
                self._fail(404, "not_found")
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
                self._fail(415, "invalid_input")
                return
            try:
                lengths = self.headers.get_all("Content-Length", [])
                if len(lengths) != 1 or self.headers.get("Transfer-Encoding") is not None:
                    raise ValueError
                length = int(lengths[0])
                if not 0 < length <= MAX_BODY_BYTES:
                    raise ValueError
                self.connection.settimeout(10)
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ValueError
                result = service.command(_decode(data))
                status = 400 if result["outcome"] == "rejected" else 202 if result["outcome"] == "accepted" else 200
                if result["error"] and result["error"]["code"] in ("version_conflict", "stale_context", "idempotency_conflict"):
                    status = 409
                self._send(status, result)
            except (ValueError, UnicodeError, RecursionError, TimeoutError):
                self._fail(400, "invalid_input")
            except (OSError, sqlite3.Error, RuntimeError):
                self._fail(500, "storage_failed")

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def add_options(parser: argparse.ArgumentParser, *, provider: bool = True) -> None:
    parser.add_argument("--db", help="외부 메모리 SQLite 경로 (STYLEMATE_DB)")
    parser.add_argument("--catalog-db", help="외부 상품 SQLite 경로 (STYLEMATE_CATALOG_DB)")
    parser.add_argument("--image-root", help="외부 로컬 이미지 root (STYLEMATE_IMAGE_ROOT)")
    parser.add_argument("--user", help="서버에 고정할 trusted user (STYLEMATE_USER_ID)")
    if provider:
        parser.add_argument("--provider", choices=("fake", "openai"), help="기본 fake; openai는 명시적 설정")
        parser.add_argument("--model", help="STYLEMATE_OPENAI_MODEL; 기본 gpt-6-luna")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LUMI 로컬 단일 테스터 소비자 서버")
    add_options(parser)
    parser.add_argument("--port", type=int, help="루프백 포트 (STYLEMATE_PORT; 기본 8766)")
    args = parser.parse_args(argv)
    try:
        settings = ConsumerSettings.from_options(args)
        return serve(settings)
    except StyleMateError as exc:
        print(json.dumps({"error": _error(exc)}, ensure_ascii=False))
        return 2
    except (OSError, sqlite3.Error, ValueError):
        print(json.dumps({"error": _error(StyleMateError("storage_failed"))}, ensure_ascii=False))
        return 2


def serve(settings: ConsumerSettings) -> int:
    with settings.open_service() as service:
        server = make_server(service, settings.port)
        print(f"LUMI consumer: http://127.0.0.1:{server.server_port} (provider={settings.provider})", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
