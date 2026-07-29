from __future__ import annotations

import http.client
import json
import math
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from server.config import PROJECT_ROOT
from server.http import make_handler
from server.repository import LocalMarketRepository
from server.service import MarketService
from server.similarity import (
    ALGORITHM,
    load_frozen_templates,
    pearson_similarity,
    score_latest_cross_section,
    z_log_close,
)
from server.state import StateStore


REGISTRY = PROJECT_ROOT / "config" / "similarity_templates.json"


def trading_dates(count: int, end: str = "20260729") -> list[str]:
    return [
        value.strftime("%Y%m%d")
        for value in pd.bdate_range(end=pd.Timestamp(end), periods=count)
    ]


class SimilarityAlgorithmTests(unittest.TestCase):
    def test_frozen_registry_contains_exact_four_templates(self):
        templates = load_frozen_templates(REGISTRY)
        self.assertEqual(
            [item.key for item in templates],
            [
                "fresh_breakout",
                "healthy_uptrend",
                "pullback_strengthening",
                "parabolic_uptrend",
            ],
        )
        self.assertEqual([item.window_bars for item in templates], [50, 80, 55, 160])
        self.assertTrue(all(item.public_dict()["algorithm"] == ALGORITHM for item in templates))

    def test_similarity_equals_independent_log_z_pearson(self):
        template = np.exp(np.linspace(0.0, 0.7, 80) + np.sin(np.arange(80)) * 0.03)
        candidate = np.exp(np.linspace(0.0, 0.5, 80) + np.cos(np.arange(80)) * 0.05)
        expected = float(np.mean(z_log_close(candidate) * z_log_close(template)))
        actual = pearson_similarity(candidate, z_log_close(template))
        self.assertTrue(math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-12))

    def test_cross_section_requires_latest_equal_length_window(self):
        dates = trading_dates(25)
        rows = []
        for code, phase in (("000001.SZ", 0.0), ("000002.SZ", 0.7)):
            for index, date in enumerate(dates):
                rows.append(
                    {
                        "ts_code": code,
                        "trade_date": date,
                        "qfq_close": math.exp(index / 100 + math.sin(index + phase) * 0.02),
                    }
                )
        frame = pd.DataFrame(rows)
        template_z = z_log_close(frame[frame["ts_code"] == "000001.SZ"].tail(20)["qfq_close"])
        scored = score_latest_cross_section(
            frame, template_z=template_z, window_bars=20, as_of=dates[-1]
        )
        self.assertEqual(scored.iloc[0]["ts_code"], "000001.SZ")
        self.assertAlmostEqual(float(scored.iloc[0]["score"]), 1.0, places=12)
        self.assertEqual(set(scored["window_bars"]), {20})


class BatchQfqRepositoryTests(unittest.TestCase):
    def test_recent_qfq_daily_loads_daily_and_factors_once(self):
        class FakePro:
            def __init__(self):
                self.daily_calls = 0
                self.factor_calls = 0

            def daily(self, **_kwargs):
                self.daily_calls += 1
                return pd.DataFrame(
                    [
                        {"ts_code": "000001.SZ", "trade_date": "20260728", "open": 10, "high": 11, "low": 9, "close": 10, "pre_close": 9, "vol": 1, "amount": 1, "pct_chg": 1},
                        {"ts_code": "000001.SZ", "trade_date": "20260729", "open": 20, "high": 21, "low": 19, "close": 20, "pre_close": 10, "vol": 1, "amount": 1, "pct_chg": 1},
                    ]
                )

            def adj_factor(self, **_kwargs):
                self.factor_calls += 1
                return pd.DataFrame(
                    [
                        {"ts_code": "000001.SZ", "trade_date": "20260728", "adj_factor": 1.0},
                        {"ts_code": "000001.SZ", "trade_date": "20260729", "adj_factor": 2.0},
                    ]
                )

        repository = LocalMarketRepository.__new__(LocalMarketRepository)
        repository.pro = FakePro()
        repository._query_lock = threading.RLock()
        repository._lock = threading.RLock()
        repository._cache = {}
        repository.latest_partition = lambda _table: "20260729"
        first = repository.recent_qfq_daily("20260728", "20260729")
        second = repository.recent_qfq_daily("20260728", "20260729")
        self.assertEqual(repository.pro.daily_calls, 1)
        self.assertEqual(repository.pro.factor_calls, 1)
        self.assertAlmostEqual(float(first.iloc[0]["qfq_close"]), 5.0)
        self.assertAlmostEqual(float(first.iloc[1]["qfq_close"]), 20.0)
        self.assertEqual(len(second), 2)


class SimilarityTemplateStoreTests(unittest.TestCase):
    def test_custom_template_crud_survives_store_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            store = StateStore(path)
            created = store.create_similarity_template(
                name="我的模板",
                source_ts_code="000001.SZ",
                start_date="20260701",
                end_date="20260729",
                bars=[{"trade_date": "20260701", "close": 10.0}, {"trade_date": "20260729", "close": 11.0}],
                z_values=[-1.0, 1.0],
                data_as_of="20260729",
            )
            template_id = created["id"]
            reopened = StateStore(path)
            loaded = reopened.similarity_template(template_id)
            self.assertEqual(loaded["bars"], created["bars"])
            self.assertEqual(loaded["z_values"], [-1.0, 1.0])
            renamed = reopened.rename_similarity_template(template_id, "重命名")
            self.assertEqual(renamed["name"], "重命名")
            self.assertTrue(reopened.delete_similarity_template(template_id))
            self.assertIsNone(StateStore(path).similarity_template(template_id))


class FakeTemplateRepository:
    def __init__(self):
        self.dates = trading_dates(20)
        self.source = "000001.SZ"

    def snapshots(self):
        return SimpleNamespace(daily_kline=self.dates[-1], adj_factor=self.dates[-1])

    def resolve_code(self, _raw):
        return self.source

    def recent_qfq_daily(self, _start, _end, codes=None):
        rows = []
        selected = codes or {self.source}
        for code in selected:
            phase = 0.0 if code == self.source else 1.0
            for index, date in enumerate(self.dates):
                close = math.exp(index / 100 + math.sin(index + phase) * 0.02)
                rows.append(
                    {
                        "ts_code": code,
                        "trade_date": date,
                        "qfq_open": close,
                        "qfq_high": close * 1.01,
                        "qfq_low": close * 0.99,
                        "qfq_close": close,
                    }
                )
        return pd.DataFrame(rows)

    def basic(self):
        return pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行"},
                {"ts_code": "000002.SZ", "symbol": "000002", "name": "万科A"},
            ]
        )

    def industries(self):
        return pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "l1_name": "银行"},
                {"ts_code": "000002.SZ", "l1_name": "房地产"},
            ]
        )


class MarketTemplateServiceTests(unittest.TestCase):
    def make_service(self, state_path: Path) -> MarketService:
        service = MarketService.__new__(MarketService)
        service.repository = FakeTemplateRepository()
        service.state_store = StateStore(state_path)
        service.frozen_templates = load_frozen_templates(REGISTRY)
        service._frozen_templates_by_id = {
            item.key: item for item in service.frozen_templates
        }
        service._materialized_frozen_templates = {}
        service._similarity_score_cache = {}
        service._similarity_lock = threading.RLock()
        return service

    def test_custom_service_crud_and_within_template_topk(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.make_service(Path(directory) / "state.sqlite3")
            dates = service.repository.dates
            created = service.create_template(
                {
                    "name": "自定义上涨",
                    "source_ts_code": "000001.SZ",
                    "start_date": dates[0],
                    "end_date": dates[-1],
                }
            )
            self.assertTrue(created["id"].startswith("custom_"))
            self.assertEqual(service.templates()["frozen_count"], 4)
            stocks = service.template_stocks(created["id"], 2)
            self.assertEqual(stocks["threshold_used"], None)
            self.assertEqual(stocks["ranking_scope"], "within_template_only")
            self.assertEqual([item["rank"] for item in stocks["items"]], [1, 2])
            renamed = service.rename_template(created["id"], {"name": "新名字"})
            self.assertEqual(renamed["name"], "新名字")
            with self.assertRaises(ValueError):
                service.rename_template("fresh_breakout", {"name": "不可改"})
            with self.assertRaises(ValueError):
                service.delete_template("fresh_breakout")
            self.assertTrue(service.delete_template(created["id"])["deleted"])
            with self.assertRaises(LookupError):
                service.template(created["id"])


class TemplateHttpRouteTests(unittest.TestCase):
    def test_template_routes_dispatch_all_crud_methods(self):
        class FakeService:
            def templates(self):
                return {"items": []}

            def template(self, template_id):
                return {"id": template_id}

            def template_stocks(self, template_id, limit):
                return {"id": template_id, "limit": int(limit), "items": []}

            def create_template(self, body):
                return {"id": "custom_1", **body}

            def rename_template(self, template_id, body):
                return {"id": template_id, **body}

            def delete_template(self, template_id):
                return {"id": template_id, "deleted": True}

        from http.server import ThreadingHTTPServer

        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FakeService()))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)

            def request(method, path, body=None):
                payload = None if body is None else json.dumps(body)
                headers = {} if body is None else {"Content-Type": "application/json"}
                connection.request(method, path, payload, headers)
                response = connection.getresponse()
                return response.status, json.loads(response.read())

            self.assertEqual(request("GET", "/api/templates")[0], 200)
            self.assertEqual(request("GET", "/api/templates/fresh_breakout")[1]["id"], "fresh_breakout")
            self.assertEqual(request("GET", "/api/templates/fresh_breakout/stocks?limit=30")[1]["limit"], 30)
            self.assertEqual(request("POST", "/api/templates", {"name": "x"})[0], 201)
            self.assertEqual(request("PATCH", "/api/templates/custom_1", {"name": "y"})[1]["name"], "y")
            self.assertTrue(request("DELETE", "/api/templates/custom_1")[1]["deleted"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
