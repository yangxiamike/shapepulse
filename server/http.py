from __future__ import annotations

import gzip
import json
import threading
import uuid
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
        "industry": "industries",
        "industries": "industries",
        "market_cap_min": "market_cap_min_yi",
        "market_cap_min_yi": "market_cap_min_yi",
        "market_cap_max": "market_cap_max_yi",
        "market_cap_max_yi": "market_cap_max_yi",
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


class ScreenJobManager:
    def __init__(self, service: MarketService):
        self.service = service
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def start(self, options: dict[str, Any], save_history: bool) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        with self._lock:
            if len(self._jobs) >= 24:
                oldest = next(iter(self._jobs))
                self._jobs.pop(oldest, None)
            self._jobs[job_id] = {
                "job_id": job_id,
                "status": "running",
                "stage": "准备本地数据",
                "completed": 0,
                "total": 1,
                "result": None,
                "error": None,
            }

        def update(stage: str, completed: int, total: int) -> None:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None:
                    job.update(stage=stage, completed=completed, total=max(total, 1))

        def work() -> None:
            try:
                result = self.service.screen(options, save_history, update)
                with self._lock:
                    self._jobs[job_id].update(
                        status="complete",
                        stage="筛选完成",
                        completed=1,
                        total=1,
                        result=result,
                    )
            except Exception as exc:
                with self._lock:
                    self._jobs[job_id].update(
                        status="error",
                        stage="筛选失败",
                        error={"type": type(exc).__name__, "message": str(exc)},
                    )

        threading.Thread(target=work, name=f"screen-{job_id[:8]}", daemon=True).start()
        return self.get(job_id) or {"job_id": job_id, "status": "running"}

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else dict(job)


def make_handler(service: MarketService):
    jobs = ScreenJobManager(service)

    class MarketRequestHandler(BaseHTTPRequestHandler):
        server_version = "ManualMarket/1.2"

        def log_message(self, fmt: str, *args) -> None:
            print(f"{self.address_string()} - {fmt % args}")

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            compressed = len(body) >= 32_768 and "gzip" in self.headers.get(
                "Accept-Encoding", ""
            ).lower()
            if compressed:
                body = gzip.compress(body, compresslevel=1)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            if compressed:
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Vary", "Accept-Encoding")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header(
                "Access-Control-Allow-Methods",
                "GET, POST, PATCH, DELETE, OPTIONS",
            )
            timings = payload.get("timings") if isinstance(payload, dict) else None
            if isinstance(timings, dict):
                entries = []
                for name, value in timings.items():
                    if name.endswith("_ms") and isinstance(value, (int, float)):
                        entries.append(f'{name.removesuffix("_ms")};dur={float(value):.1f}')
                if entries:
                    self.send_header("Server-Timing", ", ".join(entries))
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
                query = parse_qs(parsed.query, keep_blank_values=True)
                path = parsed.path.rstrip("/") or "/"
                if path == "/api/health":
                    self._send(HTTPStatus.OK, service.health())
                elif path == "/api/search":
                    term = _first(query, "q", "")
                    limit = int(_first(query, "limit", "20"))
                    self._send(HTTPStatus.OK, service.search(term, limit))
                elif path == "/api/industries":
                    self._send(HTTPStatus.OK, service.industries())
                elif path == "/api/templates":
                    self._send(HTTPStatus.OK, service.templates())
                elif path.startswith("/api/templates/"):
                    suffix = unquote(path.removeprefix("/api/templates/"))
                    if suffix.endswith("/stocks"):
                        template_id = suffix.removesuffix("/stocks").rstrip("/")
                        self._send(
                            HTTPStatus.OK,
                            service.template_stocks(
                                template_id,
                                _first(query, "limit", "100"),
                                _first(query, "include_bars", "1"),
                            ),
                        )
                    else:
                        self._send(HTTPStatus.OK, service.template(suffix))
                elif path == "/api/industry-strength":
                    self._send(
                        HTTPStatus.OK,
                        service.industry_strength(
                            _first(query, "pattern", "breakout"),
                            _first(query, "end_date"),
                        ),
                    )
                elif path == "/api/pattern/pool":
                    self._send(
                        HTTPStatus.OK,
                        service.pattern_pool(
                            _first(query, "category", ""), _first(query, "limit", "200")
                        ),
                    )
                elif path.startswith("/api/stock/"):
                    code = unquote(path.removeprefix("/api/stock/"))
                    mark_viewed = _first(query, "mark_viewed", "0").lower() in {"1", "true", "yes"}
                    result = service.stock(code, mark_viewed)
                    if result is None:
                        self._send(HTTPStatus.NOT_FOUND, {"error": "stock_not_found", "code": code})
                    else:
                        self._send(HTTPStatus.OK, result)
                elif path.startswith("/api/pattern/"):
                    code = unquote(path.removeprefix("/api/pattern/"))
                    result = service.pattern(
                        code, int(_first(query, "history_limit", "10"))
                    )
                    if result is None:
                        self._send(HTTPStatus.NOT_FOUND, {"error": "stock_not_found", "code": code})
                    else:
                        self._send(HTTPStatus.OK, result)
                elif path.startswith("/api/bars/"):
                    code = unquote(path.removeprefix("/api/bars/"))
                    limit_raw = _first(query, "limit")
                    result = service.bars(
                        code,
                        start_date=_first(query, "start"),
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
                elif path == "/api/screen/snapshots":
                    self._send(
                        HTTPStatus.OK,
                        service.saved_snapshots(
                            int(_first(query, "page", "1")),
                            int(_first(query, "page_size", "20")),
                        ),
                    )
                elif path.startswith("/api/screen/snapshots/"):
                    run_id = unquote(path.removeprefix("/api/screen/snapshots/"))
                    self._send(HTTPStatus.OK, service.saved_snapshot(run_id))
                elif path.startswith("/api/screen/jobs/"):
                    job_id = unquote(path.removeprefix("/api/screen/jobs/"))
                    result = jobs.get(job_id)
                    if result is None:
                        self._send(HTTPStatus.NOT_FOUND, {"error": "job_not_found"})
                    else:
                        self._send(HTTPStatus.OK, result)
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
                    save_history = bool(body.pop("save_history", False))
                    self._send(HTTPStatus.OK, service.screen(body, save_history))
                elif path == "/api/screen/start":
                    save_history = bool(body.pop("save_history", False))
                    self._send(HTTPStatus.ACCEPTED, jobs.start(body, save_history))
                elif path == "/api/screen/snapshots":
                    token = body.get("screen_token")
                    filters = body.get("filters")
                    if filters is not None and not isinstance(filters, dict):
                        raise ValueError("filters must be an object")
                    if token is None and filters is None:
                        filters = body
                    self._send(
                        HTTPStatus.CREATED,
                        service.save_screen_snapshot(
                            None if token is None else str(token), filters
                        ),
                    )
                elif path == "/api/templates":
                    self._send(
                        HTTPStatus.CREATED,
                        service.create_template(body),
                    )
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

        def do_PATCH(self) -> None:
            try:
                path = (urlparse(self.path).path.rstrip("/") or "/")
                body = self._read_json()
                if path.startswith("/api/templates/"):
                    template_id = unquote(path.removeprefix("/api/templates/"))
                    self._send(
                        HTTPStatus.OK,
                        service.rename_template(template_id, body),
                    )
                else:
                    self._send(
                        HTTPStatus.NOT_FOUND, {"error": "not_found", "path": path}
                    )
            except Exception as exc:
                self._handle_error(exc)

        def do_DELETE(self) -> None:
            try:
                path = (urlparse(self.path).path.rstrip("/") or "/")
                if path.startswith("/api/templates/"):
                    template_id = unquote(path.removeprefix("/api/templates/"))
                    self._send(
                        HTTPStatus.OK,
                        service.delete_template(template_id),
                    )
                else:
                    self._send(
                        HTTPStatus.NOT_FOUND, {"error": "not_found", "path": path}
                    )
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
