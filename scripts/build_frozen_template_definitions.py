from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from zer0share import pro_api

from build_template_statistical_validation import (
    PROJECT_ROOT,
    TEMPLATES,
    ZERO_CONFIG,
    ZERO_ROOT,
    load_market_data,
    load_templates,
)


ALGORITHM = "qfq_log_close_independent_z_single_window_pearson"
DEFAULT_OUTPUT = PROJECT_ROOT / "public" / "template-definitions"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def build_payloads() -> dict[str, dict]:
    previous_cwd = Path.cwd()
    os.chdir(ZERO_ROOT)
    try:
        market, as_of = load_market_data(pro_api(str(ZERO_CONFIG)))
        templates = load_templates(market)
    finally:
        os.chdir(previous_cwd)

    payloads: dict[str, dict] = {}
    for definition in TEMPLATES:
        records = templates[definition.key]["bars"]
        bars = [
            {
                "trade_date": item["date"],
                "time": (
                    f"{item['date'][:4]}-{item['date'][4:6]}-"
                    f"{item['date'][6:]}"
                ),
                "open": item["open"],
                "high": item["high"],
                "low": item["low"],
                "close": item["close"],
                "volume": item["volume"],
            }
            for item in records
        ]
        if len(bars) != definition.bars:
            raise RuntimeError(
                f"{definition.key}: expected {definition.bars} bars, "
                f"found {len(bars)}"
            )
        payloads[definition.key] = {
            "schema_version": 1,
            "algorithm": ALGORITHM,
            "data_as_of": as_of,
            "template": {
                "id": definition.key,
                "key": definition.key,
                "label": definition.label,
                "name": definition.label,
                "source": "frozen",
                "kind": "frozen",
                "read_only": True,
                "source_ts_code": definition.code,
                "source_name": definition.name,
                "start_date": definition.start,
                "end_date": definition.end,
                "window_bars": definition.bars,
                "description": definition.cue,
            },
            "bars": bars,
            "curve": [item["normalizedClose"] for item in records],
            "boundaries": {
                "data_source": str(ZERO_ROOT),
                "network_used": False,
                "sealed_final_read": False,
                "future_return_used": False,
                "ic_used": False,
                "strategy_performance_used": False,
            },
        }
    return payloads


def validate(payloads: dict[str, dict]) -> dict:
    expected = {item.key: item for item in TEMPLATES}
    if set(payloads) != set(expected):
        raise RuntimeError("frozen template payload keys differ from registry")
    checks = []
    for key, payload in payloads.items():
        definition = expected[key]
        bars = payload["bars"]
        assert payload["algorithm"] == ALGORITHM
        assert len(bars) == definition.bars
        assert bars[0]["trade_date"] == definition.start
        assert bars[-1]["trade_date"] == definition.end
        assert len(payload["curve"]) == definition.bars
        assert all(
            float(row[field]) > 0
            for row in bars
            for field in ("open", "high", "low", "close")
        )
        checks.append(
            {
                "template": key,
                "bars": len(bars),
                "start_date": bars[0]["trade_date"],
                "end_date": bars[-1]["trade_date"],
            }
        )
    return {"pass": True, "algorithm": ALGORITHM, "templates": checks}


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    if PROJECT_ROOT not in output.parents:
        raise RuntimeError("输出必须位于工作区")
    payloads = build_payloads()
    qa = validate(payloads)
    if args.dry_run:
        print(json.dumps(qa, ensure_ascii=False, indent=2))
        return
    if output.exists():
        raise RuntimeError(f"拒绝覆盖现有冻结模板目录：{output}")
    output.mkdir(parents=True)
    for key, payload in payloads.items():
        (output / f"{key}.json").write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
    print(json.dumps(qa, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
