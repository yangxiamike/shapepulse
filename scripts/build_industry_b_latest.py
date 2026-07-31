from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
from zer0share import pro_api


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ZERO_ROOT = Path(r"C:\Users\hp\Documents\zer0share")
ZERO_CONFIG = ZERO_ROOT / "config" / "settings.toml"
TEMPLATE_COMMIT = "40e71329ae0c1068eac5b37ebe02202293eda32a"
TEMPLATE_BLOBS = {
    "healthy_uptrend": "aeba1d3d85411949bff78cc8e02c4fcafe6752c0",
    "pullback_strengthening": "29bddb35b6a8abaf760150708da514fbc55a3a37",
    "parabolic_uptrend": "8fafe98217245ea92cd243efe3f6fe60018c5954",
}
WINDOW = 80
LOAD_START = "20200101"


def git_bytes(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def z_values(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    std = float(values.std(ddof=0))
    if not np.isfinite(std) or std <= 1e-12:
        return np.zeros_like(values)
    return (values - values.mean()) / std


def frozen_templates() -> dict[str, np.ndarray]:
    phase = np.linspace(0.0, 1.0, WINDOW)
    output: dict[str, np.ndarray] = {}
    for key, expected_blob in TEMPLATE_BLOBS.items():
        relative = f"public/template-definitions/{key}.json"
        actual_blob = git_bytes(
            "rev-parse", f"{TEMPLATE_COMMIT}:{relative}"
        ).decode("ascii").strip()
        if actual_blob != expected_blob:
            raise RuntimeError(f"{key} frozen blob drift")
        payload = json.loads(
            git_bytes("show", f"{TEMPLATE_COMMIT}:{relative}").decode("utf-8")
        )
        closes = np.asarray(
            [float(row["close"]) for row in payload["bars"]],
            dtype=np.float64,
        )
        output[key] = z_values(
            np.interp(
                phase,
                np.linspace(0.0, 1.0, len(closes)),
                np.log(closes),
            )
        )
    return output


def stock_metadata(pro) -> pd.DataFrame:
    frames = []
    for priority, status in enumerate(("L", "D", "P")):
        frame = pro.stock_basic(list_status=status)
        if frame.empty:
            continue
        frame = frame.copy()
        frame["_priority"] = priority
        frames.append(frame)
    stocks = pd.concat(frames, ignore_index=True)
    stocks = stocks[
        stocks["ts_code"].astype(str).str.endswith((".SH", ".SZ", ".BJ"))
    ].copy()
    stocks = (
        stocks.sort_values(["ts_code", "_priority"])
        .drop_duplicates("ts_code", keep="first")
        .drop(columns="_priority")
    )
    stocks["ts_code"] = stocks["ts_code"].astype(str)
    stocks["list_date"] = (
        stocks["list_date"].astype(str).replace({"nan": "00000000", "": "00000000"})
    )
    stocks["delist_date"] = (
        stocks["delist_date"].astype(str).replace({"nan": None, "": None})
    )
    return stocks


def active_industries(members: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    members = members.copy()
    for column in ("ts_code", "l1_code", "l1_name", "in_date", "out_date"):
        if column not in members:
            members[column] = np.nan
    members["ts_code"] = members["ts_code"].astype(str)
    members["in_date"] = (
        members["in_date"].astype(str).replace({"nan": "00000000", "": "00000000"})
    )
    members["out_date"] = (
        members["out_date"].astype(str).replace({"nan": None, "": None})
    )
    active = members[
        members["in_date"].le(trade_date)
        & (
            members["out_date"].isna()
            | members["out_date"].astype(str).gt(trade_date)
        )
    ].copy()
    return (
        active.sort_values(["ts_code", "in_date"])
        .drop_duplicates("ts_code", keep="last")
        [["ts_code", "l1_code", "l1_name"]]
        .rename(columns={"l1_code": "industry_code", "l1_name": "industry"})
    )


def calculate(trade_date: str) -> pd.DataFrame:
    previous_cwd = Path.cwd()
    os.chdir(ZERO_ROOT)
    try:
        pro = pro_api(str(ZERO_CONFIG))
        daily = pro.daily(
            start_date=LOAD_START,
            end_date=trade_date,
            fields="ts_code,trade_date,close",
        )
        factors = pro.adj_factor(
            start_date=LOAD_START,
            end_date=trade_date,
            fields="ts_code,trade_date,adj_factor",
        )
        stocks = stock_metadata(pro)
        members = pro.index_member_all(
            fields="ts_code,l1_code,l1_name,in_date,out_date,is_new"
        )
    finally:
        os.chdir(previous_cwd)

    if str(daily["trade_date"].astype(str).max()) != trade_date:
        raise RuntimeError(f"daily latest date is not {trade_date}")
    daily["ts_code"] = daily["ts_code"].astype(str)
    daily["trade_date"] = daily["trade_date"].astype(str)
    factors["ts_code"] = factors["ts_code"].astype(str)
    factors["trade_date"] = factors["trade_date"].astype(str)
    prices = daily.merge(
        factors,
        on=["ts_code", "trade_date"],
        how="left",
        validate="one_to_one",
    ).sort_values(["ts_code", "trade_date"])
    prices["adj_factor"] = prices.groupby("ts_code", sort=False)[
        "adj_factor"
    ].bfill()
    if prices["adj_factor"].isna().any():
        raise RuntimeError("adj_factor remains missing")
    latest_factor = prices.groupby("ts_code", sort=False)[
        "adj_factor"
    ].transform("last")
    prices["qfq_close"] = (
        prices["close"].astype(float)
        * prices["adj_factor"].astype(float)
        / latest_factor.astype(float)
    )

    metadata = stocks.set_index("ts_code")
    templates = frozen_templates()
    rows = []
    for code, stock_prices in prices.groupby("ts_code", sort=True):
        if code not in metadata.index:
            continue
        stock = metadata.loc[code]
        listed = str(stock["list_date"] or "00000000")
        delisted = stock["delist_date"]
        if listed > trade_date or (
            delisted is not None
            and not pd.isna(delisted)
            and str(delisted) <= trade_date
        ):
            continue
        ordered = stock_prices.sort_values("trade_date")
        if str(ordered.iloc[-1]["trade_date"]) != trade_date or len(ordered) < WINDOW:
            continue
        values = ordered["qfq_close"].to_numpy(np.float64)[-WINDOW:]
        if np.any(~np.isfinite(values)) or np.any(values <= 0):
            continue
        query_z = z_values(np.log(values))
        row = {"ts_code": code}
        for key, template_z in templates.items():
            row[f"score_{key}"] = float(np.dot(query_z, template_z) / WINDOW)
        rows.append(row)

    scores = pd.DataFrame(rows)
    for key in TEMPLATE_BLOBS:
        scores[f"pct_{key}"] = scores[f"score_{key}"].rank(
            method="average", pct=True
        )
    scores["bscore"] = scores[
        [f"pct_{key}" for key in TEMPLATE_BLOBS]
    ].mean(axis=1)
    scores = scores.sort_values(
        ["bscore", "ts_code"], ascending=[False, True]
    ).reset_index(drop=True)
    scores["b_rank"] = np.arange(1, len(scores) + 1)
    scores = scores.merge(
        active_industries(members, trade_date),
        on="ts_code",
        how="left",
        validate="one_to_one",
    )
    scores["industry_code"] = scores["industry_code"].fillna("missing")
    scores["industry"] = scores["industry"].fillna("行业缺失")
    formal = scores[
        scores["industry_code"].ne("missing")
        & scores["industry"].ne("行业缺失")
    ].copy()
    eligible = (
        formal.groupby(["industry_code", "industry"], as_index=False)
        .size()
        .rename(columns={"size": "eligible_count"})
    )
    selected = (
        formal[formal["b_rank"].le(100)]
        .groupby(["industry_code", "industry"], as_index=False)
        .size()
        .rename(columns={"size": "b_count"})
    )
    result = eligible.merge(
        selected,
        on=["industry_code", "industry"],
        how="left",
        validate="one_to_one",
    )
    result["b_count"] = result["b_count"].fillna(0).astype(int)
    result["b_breadth"] = result["b_count"] / result["eligible_count"]
    result.insert(0, "trade_date", trade_date)
    if int(result["b_count"].sum()) != 100:
        raise RuntimeError("formal B Top100 industry total is not 100")
    if len(result) != 31:
        raise RuntimeError(f"expected 31 formal industries, got {len(result)}")
    return result.sort_values("industry_code").reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = calculate(args.trade_date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False, encoding="utf-8")
    print(
        json.dumps(
            {
                "trade_date": args.trade_date,
                "eligible_stocks": int(
                    round(
                        float(
                            (result["eligible_count"]).sum()
                        )
                    )
                ),
                "b_total": int(result["b_count"].sum()),
                "industries": len(result),
                "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
