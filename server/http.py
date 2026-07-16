from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .service import MarketService


def _first(query: dict[str, list[str]], name: str, default: Any = None) -> Any:
    values = query.get(name)
    return default if not values else values[0]


def _screen_options(query: dict[str, list[str]]) -> dict[str, Any]:
    mapping = {
        "board": "board",
        "boards": "boards",
        "market_cap": "market_cap_yi",
        "market_cap_yi": "market_cap_yi",
        "operator": "market_cap_operator",
        "market_cap_operator": "market_cap_operator",
        "exclude_st": "exclude_st",
        "top_k": "top_k",
        "mode": "mode",
    }
    return {
        target: _first(query, source)
        for source, target in mapping.items()
        if source in query
    }


def make_handler(service: MarketService):
    class MarketRequestHandler(BaseHTTPRequestHandler):
        server_version = "ManualMarket/1.0"

        def log_message(self, fmt: str, *args) -> None:
            print(f"{self.address_string()} - {fmt % args}")

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length == 0:
                return {}
            if length > 1_000_000:
                raise ValueError("request body is too large")
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            return payload

        def do_OPTIONS(self) -> None:
            self._send(HTTPStatus.NO_CONTENT, {})

        def do_GET(self) -> None:
            try:
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)
                path = parsed.path.rstrip("/") or "/"
                if path == "/api/health":
                    self._send(HTTPStatus.OK, service.health())
                elif path == "/api/search":
                    term = _first(query, "q", "")
                    limit = int(_first(query, "limit", "20"))
                    self._send(HTTPStatus.OK, service.search(term, limit))
                elif path.startswith("/api/stock/"):
                    code = unquote(path.removeprefix("/api/stock/"))
                    mark_viewed = _first(query, "mark_viewed", "0").lower() in {"1", "true", "yes"}
                    result = service.stock(code, mark_viewed)
                    if result is None:
                        self._send(HTTPStatus.NOT_FOUND, {"error": "stock_not_found", "code": code})
                    else:
                        self._send(HTTPStatus.OK, result)
                elif path.startswith("/api/bars/"):
                    code = unquote(path.removeprefix("/api/bars/"))
                    limit_raw = _first(query, "limit")
                    result = service.bars(
                        code,
                        start_date=_first(query, "start", "20150101"),
                        end_date=_first(query, "end"),
                        adjust=_first(query, "adjust", "qfq"),
                        period=_first(query, "period", "1d"),
                        limit=None if limit_raw is None else int(limit_raw),
                    )
                    if result is None:
                        self._send(HTTPStatus.NOT_FOUND, {"error": "stock_not_found", "code": code})
                    else:
                        self._send(HTTPStatus.OK, result)
                elif path == "/api/screen":
                    self._send(HTTPStatus.OK, service.screen(_screen_options(query), False))
                elif path == "/api/state":
                    self._send(
                        HTTPStatus.OK,
                        service.state(int(_first(query, "history_limit", "20"))),
                    )
                else:
                    self._send(HTTPStatus.NOT_FOUND, {"error": "not_found", "path": path})
            except Exception as exc:
                self._handle_error(exc)

        def do_POST(self) -> None:
            try:
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/") or "/"
                body = self._read_json()
                if path == "/api/screen":
                    save_history = bool(body.pop("save_history", True))
                    self._send(HTTPStatus.OK, service.screen(body, save_history))
                elif path == "/api/state":
                    code = str(body.get("code", body.get("ts_code", ""))).strip()
                    action = str(body.get("action", "")).strip().lower()
                    if not code or not action:
                        raise ValueError("code and action are required")
                    self._send(HTTPStatus.OK, service.update_state(code, action))
                else:
                    self._send(HTTPStatus.NOT_FOUND, {"error": "not_found", "path": path})
            except Exception as exc:
                self._handle_error(exc)

        def _handle_error(self, exc: Exception) -> None:
            if isinstance(exc, (ValueError, json.JSONDecodeError)):
                status = HTTPStatus.BAD_REQUEST
                kind = "invalid_request"
            elif isinstance(exc, LookupError):
                status = HTTPStatus.NOT_FOUND
                kind = "not_found"
            elif isinstance(exc, FileNotFoundError):
                status = HTTPStatus.SERVICE_UNAVAILABLE
                kind = "local_data_missing"
            else:
                status = HTTPStatus.INTERNAL_SERVER_ERROR
                kind = "internal_error"
            self._send(status, {"error": kind, "message": str(exc)})

    return MarketRequestHandler


def serve(service: MarketService, host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(service))
    print(f"手动跟踪市场 API: http://{host}:{port}")
    print("仅使用本机 zer0share 数据；按 Ctrl+C 停止。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
