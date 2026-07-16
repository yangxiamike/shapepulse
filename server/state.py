from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS stock_state (
                    ts_code TEXT PRIMARY KEY,
                    viewed_at TEXT,
                    view_count INTEGER NOT NULL DEFAULT 0,
                    saved INTEGER NOT NULL DEFAULT 0,
                    saved_at TEXT,
                    pending INTEGER NOT NULL DEFAULT 0,
                    pending_at TEXT,
                    watchlist INTEGER NOT NULL DEFAULT 0,
                    watchlist_at TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS screen_runs (
                    run_id TEXT PRIMARY KEY,
                    snapshot_date TEXT NOT NULL,
                    filters_json TEXT NOT NULL,
                    result_count INTEGER NOT NULL,
                    category_counts_json TEXT NOT NULL DEFAULT '{}',
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recommendation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES screen_runs(run_id) ON DELETE CASCADE,
                    ts_code TEXT NOT NULL,
                    category TEXT NOT NULL,
                    category_label TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    score REAL NOT NULL,
                    reasons_json TEXT NOT NULL,
                    snapshot_date TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_history_run ON recommendation_history(run_id, rank);
                CREATE INDEX IF NOT EXISTS idx_history_code ON recommendation_history(ts_code, created_at);
                CREATE TABLE IF NOT EXISTS pattern_evaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES screen_runs(run_id) ON DELETE CASCADE,
                    ts_code TEXT NOT NULL,
                    status TEXT NOT NULL,
                    matches_json TEXT NOT NULL,
                    trade_date TEXT,
                    history_bars INTEGER NOT NULL DEFAULT 0,
                    warning TEXT,
                    snapshot_date TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_pattern_code
                    ON pattern_evaluations(ts_code, created_at DESC);
                """
            )
            run_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(screen_runs)")
            }
            if "category_counts_json" not in run_columns:
                connection.execute(
                    "ALTER TABLE screen_runs ADD COLUMN category_counts_json TEXT NOT NULL DEFAULT '{}'"
                )
            if "warnings_json" not in run_columns:
                connection.execute(
                    "ALTER TABLE screen_runs ADD COLUMN warnings_json TEXT NOT NULL DEFAULT '[]'"
                )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(stock_state)")}
            if "watchlist" not in columns:
                connection.execute("ALTER TABLE stock_state ADD COLUMN watchlist INTEGER NOT NULL DEFAULT 0")
            if "watchlist_at" not in columns:
                connection.execute("ALTER TABLE stock_state ADD COLUMN watchlist_at TEXT")

    def update(self, ts_code: str, action: str) -> dict[str, Any]:
        timestamp = now_iso()
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO stock_state(ts_code, updated_at) VALUES (?, ?)",
                (ts_code, timestamp),
            )
            if action == "viewed":
                connection.execute(
                    "UPDATE stock_state SET viewed_at=?, view_count=view_count+1, updated_at=? WHERE ts_code=?",
                    (timestamp, timestamp, ts_code),
                )
            elif action in {"save", "unsave"}:
                enabled = int(action == "save")
                connection.execute(
                    "UPDATE stock_state SET saved=?, saved_at=?, updated_at=? WHERE ts_code=?",
                    (enabled, timestamp if enabled else None, timestamp, ts_code),
                )
            elif action in {"pending", "unpending"}:
                enabled = int(action == "pending")
                connection.execute(
                    "UPDATE stock_state SET pending=?, pending_at=?, updated_at=? WHERE ts_code=?",
                    (enabled, timestamp if enabled else None, timestamp, ts_code),
                )
            elif action in {"watch", "unwatch"}:
                enabled = int(action == "watch")
                connection.execute(
                    "UPDATE stock_state SET watchlist=?, watchlist_at=?, updated_at=? WHERE ts_code=?",
                    (enabled, timestamp if enabled else None, timestamp, ts_code),
                )
            elif action == "clear":
                connection.execute("DELETE FROM stock_state WHERE ts_code=?", (ts_code,))
            else:
                raise ValueError("action must be viewed, save, unsave, pending, unpending, watch, unwatch, or clear")
        return self.for_code(ts_code)

    def for_code(self, ts_code: str) -> dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM stock_state WHERE ts_code=?", (ts_code,)
            ).fetchone()
        if row is None:
            return {"ts_code": ts_code, "viewed": False, "view_count": 0, "saved": False, "pending": False, "watchlist": False}
        item = dict(row)
        item["viewed"] = bool(item.pop("viewed_at"))
        item["saved"] = bool(item["saved"])
        item["pending"] = bool(item["pending"])
        item["watchlist"] = bool(item.get("watchlist", 0))
        return item

    def record_screen(
        self,
        snapshot_date: str,
        filters: dict,
        results: list[dict],
        evaluations: list[dict] | None = None,
        category_counts: dict[str, int] | None = None,
        warnings: list[str] | None = None,
    ) -> str:
        run_id = uuid.uuid4().hex
        timestamp = now_iso()
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO screen_runs(
                    run_id, snapshot_date, filters_json, result_count,
                    category_counts_json, warnings_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    snapshot_date,
                    json.dumps(filters, ensure_ascii=False, sort_keys=True),
                    len(results),
                    json.dumps(category_counts or {}, ensure_ascii=False),
                    json.dumps(warnings or [], ensure_ascii=False),
                    timestamp,
                ),
            )
            connection.executemany(
                """
                INSERT INTO recommendation_history(
                    run_id, ts_code, category, category_label, rank, score,
                    reasons_json, snapshot_date, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        item["ts_code"],
                        item["category"],
                        item["category_label"],
                        item["rank"],
                        item["score"],
                        json.dumps(item.get("reasons", []), ensure_ascii=False),
                        snapshot_date,
                        timestamp,
                    )
                    for item in results
                ],
            )
            if evaluations:
                connection.executemany(
                    """
                    INSERT INTO pattern_evaluations(
                        run_id, ts_code, status, matches_json, trade_date,
                        history_bars, warning, snapshot_date, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            run_id,
                            item["ts_code"],
                            item.get("status", "not_calculated"),
                            json.dumps(item.get("matches", []), ensure_ascii=False),
                            item.get("trade_date"),
                            int(item.get("history_bars", 0)),
                            item.get("warning"),
                            snapshot_date,
                            timestamp,
                        )
                        for item in evaluations
                    ],
                )
        return run_id

    def previous_category_counts(
        self, filters: dict, before_snapshot: str
    ) -> tuple[str, dict[str, int]] | None:
        canonical = json.dumps(filters, ensure_ascii=False, sort_keys=True)
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT snapshot_date, category_counts_json
                FROM screen_runs
                WHERE filters_json=? AND snapshot_date < ?
                ORDER BY snapshot_date DESC, created_at DESC
                LIMIT 1
                """,
                (canonical, before_snapshot),
            ).fetchone()
        if row is None:
            return None
        return str(row["snapshot_date"]), json.loads(row["category_counts_json"] or "{}")

    def pattern_for_code(self, ts_code: str, history_limit: int = 10) -> dict[str, Any]:
        with self._connection() as connection:
            rows = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT pe.*, sr.filters_json, sr.warnings_json
                    FROM pattern_evaluations pe
                    JOIN screen_runs sr ON sr.run_id=pe.run_id
                    WHERE pe.ts_code=?
                    ORDER BY pe.snapshot_date DESC, pe.created_at DESC, pe.id DESC
                    LIMIT ?
                    """,
                    (ts_code, max(1, min(50, int(history_limit)))),
                ).fetchall()
            ]
        history = []
        for row in rows:
            row["matches"] = json.loads(row.pop("matches_json"))
            row["filters"] = json.loads(row.pop("filters_json"))
            row["run_warnings"] = json.loads(row.pop("warnings_json") or "[]")
            history.append(row)
        if not history:
            return {
                "ts_code": ts_code,
                "calculation_state": "not_calculated",
                "message": "尚未对这只股票运行形态计算",
                "current": None,
                "history": [],
            }
        current = history[0]
        if current["status"] == "not_calculated":
            state = "not_calculated"
            message = current.get("warning") or "尚未完成形态计算"
        elif current["status"] == "no_match":
            state = "calculated_no_match"
            message = "已计算，但当前未匹配三类形态"
        else:
            state = "matched"
            message = "已匹配形态"
        return {
            "ts_code": ts_code,
            "calculation_state": state,
            "message": message,
            "current": current,
            "history": history,
        }

    def snapshot(self, history_limit: int = 20) -> dict[str, Any]:
        with self._connection() as connection:
            rows = [dict(row) for row in connection.execute(
                "SELECT * FROM stock_state ORDER BY updated_at DESC"
            ).fetchall()]
            runs = [dict(row) for row in connection.execute(
                "SELECT * FROM screen_runs ORDER BY created_at DESC LIMIT ?", (history_limit,)
            ).fetchall()]
            recommendations = [dict(row) for row in connection.execute(
                """
                SELECT * FROM recommendation_history
                WHERE run_id IN (SELECT run_id FROM screen_runs ORDER BY created_at DESC LIMIT ?)
                ORDER BY created_at DESC, rank ASC
                """,
                (history_limit,),
            ).fetchall()]
        for run in runs:
            run["filters"] = json.loads(run.pop("filters_json"))
            run["category_counts"] = json.loads(run.pop("category_counts_json", "{}") or "{}")
            run["warnings"] = json.loads(run.pop("warnings_json", "[]") or "[]")
        for item in recommendations:
            item["reasons"] = json.loads(item.pop("reasons_json"))
        viewed, saved, pending, watchlist = [], [], [], []
        for item in rows:
            item["viewed"] = bool(item.get("viewed_at"))
            item["saved"] = bool(item["saved"])
            item["pending"] = bool(item["pending"])
            item["watchlist"] = bool(item.get("watchlist", 0))
            if item["viewed"]:
                viewed.append(item)
            if item["saved"]:
                saved.append(item)
            if item["pending"]:
                pending.append(item)
            if item["watchlist"]:
                watchlist.append(item)
        return {
            "viewed": viewed,
            "saved": saved,
            "pending": pending,
            "watchlist": watchlist,
            "history": {"runs": runs, "recommendations": recommendations},
        }
