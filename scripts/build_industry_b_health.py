from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


EXPECTED_SOURCE_SHA256 = (
    "7f790b670ed6532bdca27d248395a033dfbc274086f8609705d09207af3c3437"
)
DISPLAY_TRADING_DAYS = 252


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rounded(value: object, digits: int = 4) -> float | None:
    return None if pd.isna(value) else round(float(value), digits)


def derive_health_fields(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.sort_values(["industry_code", "trade_date"]).reset_index(drop=True)
    grouped = frame.groupby("industry_code", sort=False, group_keys=False)
    frame["b_rank_pct"] = frame.groupby("trade_date")["b_breadth"].rank(
        pct=True, method="average"
    )
    prior_rank = grouped["b_rank_pct"].transform(lambda values: values.shift(1))
    prior_breadth = grouped["b_breadth"].transform(lambda values: values.shift(1))
    high_days = prior_rank.groupby(frame["industry_code"]).transform(
        lambda values: values.ge(0.75).rolling(20, min_periods=20).sum()
    )
    median20 = prior_rank.groupby(frame["industry_code"]).transform(
        lambda values: values.rolling(20, min_periods=20).median()
    )
    median5 = prior_rank.groupby(frame["industry_code"]).transform(
        lambda values: values.rolling(5, min_periods=5).median()
    )
    average_breadth20 = prior_breadth.groupby(frame["industry_code"]).transform(
        lambda values: values.rolling(20, min_periods=20).mean()
    )
    frame["mainline_confirmed"] = (
        high_days.ge(12)
        & median20.ge(0.75)
        & median5.ge(0.75)
        & average_breadth20.gt(0)
    )
    previous_count = grouped["b_count"].shift(1)
    previous_breadth = grouped["b_breadth"].shift(1)
    frame["b_cond_raw"] = frame["b_count"].le(
        previous_count - 1
    ) & frame["b_breadth"].lt(previous_breadth)
    for window in (3, 5):
        recent_count = grouped["b_count"].transform(
            lambda values, window=window: values.rolling(
                window, min_periods=window
            ).mean()
        )
        previous_count_mean = grouped["b_count"].transform(
            lambda values, window=window: values.shift(window)
            .rolling(window, min_periods=window)
            .mean()
        )
        recent_breadth = grouped["b_breadth"].transform(
            lambda values, window=window: values.rolling(
                window, min_periods=window
            ).mean()
        )
        previous_breadth_mean = grouped["b_breadth"].transform(
            lambda values, window=window: values.shift(window)
            .rolling(window, min_periods=window)
            .mean()
        )
        recent_rank = grouped["b_rank_pct"].transform(
            lambda values, window=window: values.rolling(
                window, min_periods=window
            ).mean()
        )
        previous_rank = grouped["b_rank_pct"].transform(
            lambda values, window=window: values.shift(window)
            .rolling(window, min_periods=window)
            .mean()
        )
        frame[f"b_delta_rank_{window}"] = recent_rank - previous_rank
        frame[f"b_base_smooth{window}"] = recent_count.lt(
            previous_count_mean
        ) & recent_breadth.lt(previous_breadth_mean)
        frame[f"b_cond_smooth{window}"] = frame[
            f"b_base_smooth{window}"
        ] & frame[f"b_delta_rank_{window}"].le(-0.10)
    recent5_rank = grouped["b_rank_pct"].transform(
        lambda values: values.rolling(5, min_periods=5).mean()
    )
    previous15_rank = grouped["b_rank_pct"].transform(
        lambda values: values.shift(5).rolling(15, min_periods=15).mean()
    )
    recent5_breadth = grouped["b_breadth"].transform(
        lambda values: values.rolling(5, min_periods=5).mean()
    )
    previous15_breadth = grouped["b_breadth"].transform(
        lambda values: values.shift(5).rolling(15, min_periods=15).mean()
    )
    frame["b_delta_rank_formal"] = recent5_rank - previous15_rank
    frame["b_delta_breadth_formal"] = recent5_breadth - previous15_breadth
    frame["b_cond_formal"] = (
        frame["b_delta_rank_formal"].le(-0.15)
        & frame["b_delta_breadth_formal"].lt(0)
        & frame["mainline_confirmed"]
    )
    return frame


def build_payload(
    source: Path,
    latest: Path | None = None,
    timeline: Path | None = None,
) -> dict:
    actual_hash = sha256(source)
    if actual_hash != EXPECTED_SOURCE_SHA256:
        raise RuntimeError(
            f"frozen B source hash mismatch: {actual_hash} != {EXPECTED_SOURCE_SHA256}"
        )

    frame = pd.read_parquet(source)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    latest_hash = None
    if latest is not None:
        latest_hash = sha256(latest)
        latest_frame = pd.read_csv(latest)
        latest_frame["trade_date"] = pd.to_datetime(
            latest_frame["trade_date"].astype(str)
        )
        if latest_frame["trade_date"].nunique() != 1:
            raise RuntimeError("latest B extension must contain exactly one date")
        if latest_frame["trade_date"].iloc[0] <= frame["trade_date"].max():
            raise RuntimeError("latest B extension date must follow the audited source")
        if len(latest_frame) != 31 or int(latest_frame["b_count"].sum()) != 100:
            raise RuntimeError("latest B extension must contain 31 industries and Top100")
        frame = pd.concat([frame, latest_frame], ignore_index=True, sort=False)
        frame = derive_health_fields(frame)
    frame = frame.sort_values(["industry_code", "trade_date"]).reset_index(drop=True)
    window_dates = sorted(frame["trade_date"].unique())[-DISPLAY_TRADING_DAYS:]
    if timeline is not None:
        timeline_payload = json.loads(timeline.read_text(encoding="utf-8"))
        display_dates = [
            pd.Timestamp(snapshot["date"])
            for snapshot in timeline_payload["snapshots"]
        ]
    else:
        display_dates = window_dates[::5]
        if display_dates[-1] != window_dates[-1]:
            display_dates.append(window_dates[-1])

    grouped = frame.groupby("industry_code", sort=False)
    for window in (3, 5):
        recent_count = grouped["b_count"].transform(
            lambda values, window=window: values.rolling(
                window, min_periods=window
            ).mean()
        )
        prior_count = grouped["b_count"].transform(
            lambda values, window=window: values.shift(window)
            .rolling(window, min_periods=window)
            .mean()
        )
        frame[f"b_count_change_{window}"] = recent_count - prior_count

    duration_by_index: dict[int, int] = {}
    for _, industry_rows in frame.groupby("industry_code", sort=False):
        weak_start_position: int | None = None
        previous_active = False
        for position, (index, row) in enumerate(industry_rows.iterrows()):
            active = bool(
                row["b_cond_smooth3"]
                or row["b_cond_smooth5"]
                or row["b_cond_formal"]
            )
            if not active:
                weak_start_position = None
            elif not previous_active:
                weak_start_position = position if bool(row["b_cond_smooth3"]) else None
            elif weak_start_position is None and bool(row["b_cond_smooth3"]):
                weak_start_position = position
            duration_by_index[index] = (
                position - weak_start_position + 1
                if active and weak_start_position is not None
                else 0
            )
            previous_active = active

    snapshots = []
    for trade_date, daily in frame[
        frame["trade_date"].isin(display_dates)
    ].groupby("trade_date", sort=True):
        daily = daily.copy()
        pool_total = int(daily["b_count"].sum())
        daily = daily.sort_values(
            ["b_count", "b_breadth", "industry_code"],
            ascending=[False, False, True],
        )
        daily["pool_rank"] = range(1, len(daily) + 1)
        industries = []
        for index, row in daily.iterrows():
            formal = bool(row["b_cond_formal"])
            smooth3 = bool(row["b_cond_smooth3"])
            smooth5 = bool(row["b_cond_smooth5"])
            status = "cooling" if formal else "weakening" if smooth3 or smooth5 else "stable"
            industries.append(
                {
                    "industry_code": str(row["industry_code"]),
                    "industry": str(row["industry"]),
                    "b_count": int(row["b_count"]),
                    "pool_share": rounded(
                        row["b_count"] / pool_total if pool_total else 0
                    ),
                    "pool_rank": int(row["pool_rank"]),
                    "b_breadth": rounded(row["b_breadth"]),
                    "breadth_rank_pct": rounded(row["b_rank_pct"]),
                    "change_3d_count": rounded(row["b_count_change_3"]),
                    "change_5d_count": rounded(row["b_count_change_5"]),
                    "smooth3_weak": smooth3,
                    "smooth5_weak": smooth5,
                    "formal_cooling": formal,
                    "status": status,
                    "weak_duration": duration_by_index[index],
                }
            )
        snapshots.append(
            {
                "date": trade_date.strftime("%Y%m%d"),
                "pool_total": pool_total,
                "industries": industries,
            }
        )

    return {
        "version": "industry-b-health/1",
        "as_of": snapshots[-1]["date"],
        "definition": {
            "b_pool": (
                "三趋势模板全截面百分位均值 Bscore，每日独立 Top100；"
                "不是三个模板各自 Top100 的并集"
            ),
            "pool_share": "行业 B 数量 / 当日正式行业 B 总数",
            "smooth3": "最近3日数量、行业B广度均值低于此前3日，且广度排名均值下降至少0.10",
            "smooth5": "最近5日数量、行业B广度均值低于此前5日，且广度排名均值下降至少0.10",
            "formal": "最近5日对此前15日广度排名下降至少0.15、B广度下降，且此前已确认主线",
            "duration": "从当前走弱区间内3日平滑走弱首次成立日起，按实际交易日累计",
        },
        "source": {
            "kind": "frozen_audited_daily_b_panel",
            "sha256": actual_hash,
            "latest_extension_sha256": latest_hash,
            "data_window": [
                snapshots[0]["date"],
                snapshots[-1]["date"],
            ],
        },
        "snapshots": snapshots,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--latest", type=Path)
    parser.add_argument("--timeline", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("public/industry-b-health.json"),
    )
    args = parser.parse_args()
    payload = build_payload(
        args.source.resolve(),
        args.latest.resolve() if args.latest else None,
        args.timeline.resolve() if args.timeline else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
