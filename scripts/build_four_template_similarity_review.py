from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from zer0share import pro_api


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ZERO_ROOT = Path(r"C:\Users\hp\Documents\zer0share")
ZERO_CONFIG = ZERO_ROOT / "config" / "settings.toml"
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "outputs"
    / "shape-v2"
    / "four-template-similarity-review-v1-20260729"
)
SEARCH_START = "20251001"
TOP_K = 30


@dataclass(frozen=True)
class Template:
    key: str
    label: str
    code: str
    name: str
    start: str
    end: str
    bars: int
    accent: str
    cue: str


TEMPLATES = (
    Template(
        "fresh_breakout",
        "刚突破",
        "603986.SH",
        "兆易创新",
        "20250619",
        "20250827",
        50,
        "#d97706",
        "平台 / 蓄势 → 上破 → 少量保持",
    ),
    Template(
        "healthy_uptrend",
        "健康上涨",
        "601009.SH",
        "南京银行",
        "20240306",
        "20240703",
        80,
        "#0f766e",
        "持续抬高 → 回撤受控 → 不末端抛物线",
    ),
    Template(
        "pullback_strengthening",
        "回调转强",
        "603391.SH",
        "力聚热能",
        "20250805",
        "20251028",
        55,
        "#6d5bd0",
        "强第一段 → 回吐受控 → 再次向上",
    ),
    Template(
        "parabolic_uptrend",
        "抛物线上升",
        "001309.SZ",
        "德明利",
        "20251031",
        "20260630",
        160,
        "#be123c",
        "前段缓慢 → 斜率放大 → 加速拥挤",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top-k", type=int, default=TOP_K)
    return parser.parse_args()


def date_label(value: str) -> str:
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def normalized_close(frame: pd.DataFrame) -> np.ndarray:
    close = frame["close"].to_numpy(dtype=float)
    return close / close[0] * 100.0


def z_normalized_log_close(frame: pd.DataFrame) -> np.ndarray:
    values = np.log(frame["close"].to_numpy(dtype=float))
    standard_deviation = float(values.std())
    if standard_deviation <= 1e-12:
        return np.zeros_like(values)
    return (values - values.mean()) / standard_deviation


def pearson_similarity(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.mean(left * right))


def market_cap_tier(total_mv: float | None) -> str:
    if total_mv is None or not math.isfinite(total_mv):
        return "市值缺失"
    yi = total_mv / 10000.0
    if yi < 50:
        return "小于50亿"
    if yi < 200:
        return "50–200亿"
    if yi < 1000:
        return "200–1000亿"
    return "1000亿以上"


def max_drawdown_pct(close: np.ndarray) -> float:
    running = np.maximum.accumulate(close)
    return float(np.min(close / running - 1.0) * 100.0)


def render_bars(frame: pd.DataFrame) -> list[dict]:
    first_close = float(frame.iloc[0]["close"])
    bars = []
    for row in frame.itertuples(index=False):
        bars.append(
            {
                "date": str(row.trade_date),
                "open": round(float(row.open), 4),
                "high": round(float(row.high), 4),
                "low": round(float(row.low), 4),
                "close": round(float(row.close), 4),
                "volume": round(float(row.vol), 2),
                "pctChange": round(float(row.pct_chg), 4),
                "normalizedClose": round(float(row.close) / first_close * 100.0, 4),
            }
        )
    return bars


def qfq_batch(daily: pd.DataFrame, factors: pd.DataFrame) -> pd.DataFrame:
    merged = daily.merge(
        factors[["ts_code", "trade_date", "adj_factor"]],
        on=["ts_code", "trade_date"],
        how="left",
    ).sort_values(["ts_code", "trade_date"])
    merged["adj_factor"] = merged.groupby("ts_code")["adj_factor"].bfill()
    merged = merged.dropna(subset=["adj_factor"]).copy()
    base_factor = merged.groupby("ts_code")["adj_factor"].transform("last")
    multiplier = merged["adj_factor"] / base_factor
    for column in ("open", "high", "low", "close", "pre_close"):
        merged[column] = (merged[column] * multiplier).round(2)
    merged["change"] = (merged["close"] - merged["pre_close"]).round(2)
    merged["pct_chg"] = (merged["change"] / merged["pre_close"] * 100.0).round(2)
    return merged.drop(columns=["adj_factor"])


def load_templates(pro) -> dict[str, dict]:
    loaded: dict[str, dict] = {}
    for item in TEMPLATES:
        frame = pro.pro_bar(
            ts_code=item.code,
            start_date=item.start,
            end_date=item.end,
            adj="qfq",
        ).sort_values("trade_date")
        if len(frame) != item.bars:
            raise RuntimeError(
                f"{item.label} {item.code}: expected {item.bars} bars, got {len(frame)}"
            )
        if str(frame.iloc[0]["trade_date"]) != item.start:
            raise RuntimeError(f"{item.label}: template start date drifted")
        if str(frame.iloc[-1]["trade_date"]) != item.end:
            raise RuntimeError(f"{item.label}: template end date drifted")
        loaded[item.key] = {
            "meta": item,
            "path": normalized_close(frame),
            "bars": render_bars(frame),
        }
    return loaded


def result_payload(
    *,
    frame: pd.DataFrame,
    similarity: float,
    rank: int,
    name: str,
    industry: str,
    total_mv: float | None,
    limit_rows: pd.DataFrame,
    suspension_rows: pd.DataFrame,
) -> dict:
    code = str(frame.iloc[0]["ts_code"])
    close = frame["close"].to_numpy(dtype=float)
    start = str(frame.iloc[0]["trade_date"])
    end = str(frame.iloc[-1]["trade_date"])
    matched_limits = limit_rows[
        (limit_rows["ts_code"] == code)
        & (limit_rows["trade_date"] >= start)
        & (limit_rows["trade_date"] <= end)
    ]
    price_lookup = frame.set_index("trade_date")["close"]
    up_limit_count = 0
    down_limit_count = 0
    for limit_row in matched_limits.itertuples(index=False):
        current_close = price_lookup.get(str(limit_row.trade_date))
        if current_close is None or not math.isfinite(float(current_close)):
            continue
        tolerance = max(abs(float(limit_row.up_limit)) * 1e-5, 0.001)
        if abs(float(current_close) - float(limit_row.up_limit)) <= tolerance:
            up_limit_count += 1
        tolerance = max(abs(float(limit_row.down_limit)) * 1e-5, 0.001)
        if abs(float(current_close) - float(limit_row.down_limit)) <= tolerance:
            down_limit_count += 1
    suspension_count = int(
        suspension_rows[
            (suspension_rows["ts_code"] == code)
            & (suspension_rows["trade_date"] >= start)
            & (suspension_rows["trade_date"] <= end)
        ].shape[0]
    )
    max_abs_day = float(frame["pct_chg"].abs().max())
    anomaly_flags = []
    if up_limit_count:
        anomaly_flags.append(f"涨停×{up_limit_count}")
    if down_limit_count:
        anomaly_flags.append(f"跌停×{down_limit_count}")
    if suspension_count:
        anomaly_flags.append(f"停牌记录×{suspension_count}")
    if max_abs_day >= 9.5 and not up_limit_count and not down_limit_count:
        anomaly_flags.append(f"最大单日{max_abs_day:.1f}%")
    return {
        "rank": rank,
        "code": code,
        "name": name,
        "start": start,
        "end": end,
        "startLabel": date_label(start),
        "endLabel": date_label(end),
        "barCount": int(len(frame)),
        "distance": round(1.0 - similarity, 6),
        "similarity": round(similarity, 6),
        "returnPct": round((close[-1] / close[0] - 1.0) * 100.0, 2),
        "maxDrawdownPct": round(max_drawdown_pct(close), 2),
        "maxAbsDayPct": round(max_abs_day, 2),
        "industry": industry or "行业缺失",
        "totalMvYi": round(total_mv / 10000.0, 1)
        if total_mv is not None and math.isfinite(total_mv)
        else None,
        "marketCapTier": market_cap_tier(total_mv),
        "upLimitCount": up_limit_count,
        "downLimitCount": down_limit_count,
        "suspensionCount": suspension_count,
        "anomalyFlags": anomaly_flags,
        "bars": render_bars(frame),
    }


def build_data(pro, top_k: int) -> dict:
    templates = load_templates(pro)
    daily = pro.daily(start_date=SEARCH_START, end_date="20261231")
    if daily.empty:
        raise RuntimeError("current-market daily query returned no data")
    as_of = str(daily["trade_date"].max())
    daily = daily[daily["trade_date"] <= as_of].copy()
    factors = pro.adj_factor(start_date=SEARCH_START, end_date=as_of)
    adjusted = qfq_batch(daily, factors)

    listed = pro.stock_basic(list_status="L")
    listed = listed[
        listed["ts_code"].astype(str).str.endswith((".SH", ".SZ", ".BJ"))
    ].copy()
    listed_codes = set(listed["ts_code"].astype(str))
    names = listed.set_index("ts_code")["name"].astype(str).to_dict()

    latest_basic = pro.daily_basic(trade_date=as_of)
    total_mv_map = (
        latest_basic.drop_duplicates("ts_code")
        .set_index("ts_code")["total_mv"]
        .astype(float)
        .to_dict()
    )
    members = pro.index_member_all(is_new="Y")
    industry_map = (
        members.drop_duplicates("ts_code")
        .set_index("ts_code")["l1_name"]
        .fillna("")
        .astype(str)
        .to_dict()
    )
    limits = pro.stk_limit(start_date=SEARCH_START, end_date=as_of)
    suspensions = pro.suspend_d(start_date=SEARCH_START, end_date=as_of)

    groups: dict[str, pd.DataFrame] = {}
    minimum_window = min(item.bars for item in TEMPLATES)
    for code, frame in adjusted.groupby("ts_code", sort=False):
        if code not in listed_codes:
            continue
        ordered = frame.sort_values("trade_date").reset_index(drop=True)
        if str(ordered.iloc[-1]["trade_date"]) != as_of:
            continue
        if len(ordered) < minimum_window:
            continue
        groups[str(code)] = ordered

    categories = []
    for item in TEMPLATES:
        template_path = z_normalized_log_close(
            pd.DataFrame(templates[item.key]["bars"])
        )
        eligible_codes = [
            code for code, frame in groups.items() if len(frame) >= item.bars
        ]
        scored = []
        for code in eligible_codes:
            window = groups[code].tail(item.bars).reset_index(drop=True)
            similarity = pearson_similarity(
                z_normalized_log_close(window), template_path
            )
            scored.append((similarity, code, window))
        scored.sort(key=lambda value: (-value[0], value[1]))
        results = []
        for rank, (similarity, code, window) in enumerate(scored[:top_k], start=1):
            raw_mv = total_mv_map.get(code)
            total_mv = float(raw_mv) if raw_mv is not None and pd.notna(raw_mv) else None
            results.append(
                result_payload(
                    frame=window,
                    similarity=similarity,
                    rank=rank,
                    name=names.get(code, code),
                    industry=industry_map.get(code, ""),
                    total_mv=total_mv,
                    limit_rows=limits,
                    suspension_rows=suspensions,
                )
            )
        categories.append(
            {
                "key": item.key,
                "label": item.label,
                "cue": item.cue,
                "accent": item.accent,
                "windowBars": item.bars,
                "eligibleCount": len(scored),
                "template": {
                    "code": item.code,
                    "name": item.name,
                    "start": item.start,
                    "end": item.end,
                    "startLabel": date_label(item.start),
                    "endLabel": date_label(item.end),
                    "barCount": item.bars,
                    "bars": templates[item.key]["bars"],
                },
                "results": results,
            }
        )

    appearances: dict[str, list[dict]] = {}
    for category in categories:
        for result in category["results"]:
            appearances.setdefault(result["code"], []).append(
                {"category": category["label"], "rank": result["rank"]}
            )
    for category in categories:
        for result in category["results"]:
            result["crossCategoryHits"] = [
                value
                for value in appearances[result["code"]]
                if value["category"] != category["label"]
            ]

    diagnostics = []
    for category in categories:
        top10 = category["results"][:10]
        diagnostics.append(
            {
                "category": category["label"],
                "top10WithLimit": sum(
                    bool(item["upLimitCount"] or item["downLimitCount"]) for item in top10
                ),
                "top10WithSuspension": sum(
                    bool(item["suspensionCount"]) for item in top10
                ),
                "top10CrossCategory": sum(
                    bool(item["crossCategoryHits"]) for item in top10
                ),
                "uniqueCodes": len({item["code"] for item in category["results"]}),
            }
        )

    return {
        "schemaVersion": "four-template-similarity-review/1",
        "status": "similarity_retrieval_review_not_for_model_evaluation",
        "generatedAt": "2026-07-29",
        "branch": "codex/four-template-market-retrieval-review-v1",
        "baseCommit": "3e5bb44",
        "asOf": as_of,
        "asOfLabel": date_label(as_of),
        "topK": top_k,
        "dataSource": {
            "provider": "local zer0share",
            "root": str(ZERO_ROOT),
            "dailyRangeLoaded": f"{SEARCH_START}-{as_of}",
            "candidateApi": "daily + adj_factor, reproduced pro_bar qfq in batch",
            "templateApi": 'pro_bar(adj="qfq")',
            "metadataApis": "stock_basic + daily_basic + index_member_all",
            "anomalyApis": "stk_limit + suspend_d",
            "networkUsed": False,
            "sealedFinalRead": False,
        },
        "method": {
            "windowPolicy": "one latest window per listed A-share, ending on local latest trade date",
            "priceInput": "log(qfq close)",
            "normalization": "independent z-normalization within each window",
            "distance": "correlation distance = 1 - Pearson r",
            "similarity": "Pearson r; display score = 100 * r",
            "rankingInputs": ["query-window z-normalized log-close", "fixed template z-normalized log-close"],
            "rankingExcludes": [
                "post-window performance",
                "industry",
                "market cap",
                "volume",
                "limit/suspension flags",
                "Shape V2 axes",
                "sealed final",
            ],
        },
        "universe": {
            "latestDailyStockCount": int(
                daily[daily["trade_date"] == as_of]["ts_code"].nunique()
            ),
            "listedAshareCount": len(listed_codes),
            "eligibleLatestMinWindowCount": len(groups),
            "eligibleLatest160BarCount": sum(
                len(frame) >= max(item.bars for item in TEMPLATES)
                for frame in groups.values()
            ),
        },
        "diagnostics": diagnostics,
        "categories": categories,
    }


def html_document(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:,">
<title>四模子全市场相似检索 V1 评审页</title>
<style>
:root{{--ink:#172033;--muted:#687083;--paper:#f2efe7;--card:#fffdf8;--line:#d9d3c7;--up:#d95050;--down:#159874}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font-family:"Segoe UI","Microsoft YaHei",sans-serif}}
header{{padding:30px clamp(18px,4vw,58px) 24px;background:#172033;color:#fff}}
.eyebrow{{font-size:12px;letter-spacing:.14em;color:#cbd5e1;text-transform:uppercase}} h1{{margin:8px 0 9px;font-size:clamp(26px,3vw,42px)}}
header p{{max-width:980px;margin:0;color:#dbe3f2;line-height:1.65}} .notice{{display:inline-flex;margin-top:15px;padding:7px 11px;border:1px solid #8792a7;border-radius:999px;color:#f5d28d;font-size:12px}}
main{{padding:20px clamp(12px,3vw,42px) 42px}} .summary{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}}
.summary article,.audit,.template-card,.result-card{{background:var(--card);border:1px solid var(--line);border-radius:14px}}
.summary article{{padding:14px}} .summary b{{display:block;margin-bottom:5px}} .summary span{{font-size:12px;color:var(--muted);line-height:1.55}}
.tabs{{display:flex;gap:8px;overflow:auto;margin:18px 0 14px;padding-bottom:2px}} .tab{{flex:0 0 auto;border:1px solid var(--line);background:#fffdf8;border-radius:999px;padding:9px 14px;color:var(--ink);cursor:pointer;font-weight:700}}
.tab[aria-selected="true"]{{background:#172033;color:#fff;border-color:#172033}} .panel{{display:none}} .panel.active{{display:block}}
.category-head{{display:flex;justify-content:space-between;gap:14px;align-items:end;margin-bottom:12px;border-left:5px solid var(--accent);padding-left:12px}}
.category-head h2{{margin:0 0 4px;font-size:25px}} .category-head p{{margin:0;color:var(--muted);font-size:13px}} .category-head small{{color:var(--muted);text-align:right}}
.template-card{{padding:14px;margin-bottom:12px;border-top:4px solid var(--accent)}} .template-top,.result-top{{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}}
.template-top h3,.result-top h3{{margin:0;font-size:18px}} .code{{font:12px ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--muted)}}
.badge{{display:inline-flex;padding:4px 8px;border-radius:999px;background:#f2eee4;font-size:11px;color:#5d6471}} .rank{{font-size:24px;font-weight:800;color:var(--accent)}}
.result-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}} details.result-card{{overflow:hidden}} details[open]{{border-top:4px solid var(--accent)}}
summary{{list-style:none;cursor:pointer;padding:14px}} summary::-webkit-details-marker{{display:none}} .result-body{{padding:0 14px 14px}}
.facts{{display:grid;grid-template-columns:repeat(6,1fr);gap:6px;margin-top:10px}} .fact{{padding:8px 5px;background:#f5f2ea;border-radius:8px;text-align:center}}
.fact b{{display:block;font-size:12px}} .fact span{{font-size:10px;color:var(--muted)}} .flags{{display:flex;flex-wrap:wrap;gap:5px;margin-top:9px}}
.flag{{padding:4px 7px;border-radius:999px;background:#fff2dc;color:#925a08;font-size:11px}} .flag.cross{{background:#eeeafd;color:#5e4cad}} .flag.clean{{background:#e8f6ef;color:#137153}}
.charts{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}} .chart{{padding:8px;background:#fbfaf6;border:1px solid #e7e1d6;border-radius:10px}}
.chart-title{{display:flex;justify-content:space-between;gap:8px;color:var(--muted);font-size:10px;margin-bottom:4px}} svg{{display:block;width:100%;height:auto}}
.audit{{margin-top:18px;padding:18px}} .audit h2{{margin:0 0 12px}} .audit-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:9px}}
.audit-grid div{{padding:11px;background:#f5f2ea;border-radius:9px}} .audit-grid b{{display:block;margin-bottom:4px;font-size:12px}} .audit-grid span{{color:var(--muted);font-size:11px;line-height:1.5}}
footer{{padding:0 14px 30px;text-align:center;color:var(--muted);font-size:11px}}
@media(max-width:1100px){{.summary,.audit-grid{{grid-template-columns:repeat(2,1fr)}}.result-grid{{grid-template-columns:1fr}}}}
@media(max-width:700px){{header{{padding-top:24px}}main{{padding-left:10px;padding-right:10px}}.summary,.audit-grid{{grid-template-columns:1fr}}.category-head{{align-items:start;flex-direction:column}}.category-head small{{text-align:left}}.facts{{grid-template-columns:repeat(3,1fr)}}.charts{{grid-template-columns:1fr}}.template-card{{padding:10px}}summary{{padding:11px}}.result-body{{padding:0 10px 10px}}}}
</style>
</head>
<body>
<header>
  <div class="eyebrow">Four-template full-market retrieval · V1</div>
  <h1>四模子全市场相似检索 V1 评审页</h1>
  <p>目的只有一个：检查四个已拍板模子，能否从本地当前全市场捞出肉眼同类形态。每类沿用自己的窗口长度；行业、市值、涨跌停和停牌只做旁注，不参与排序。</p>
  <div class="notice">similarity retrieval review / not for model evaluation</div>
</header>
<main>
  <section class="summary">
    <article><b>数据边界</b><span>本机 zer0share，最新交易日 {data["asOfLabel"]}；未联网、未补行情、未读 sealed final。</span></article>
    <article><b>既定口径</b><span>前复权 log-close；每段独立 z 标准化；Pearson 相关降序；每只股票每类仅一个最新窗口。</span></article>
    <article><b>全市场范围</b><span>{data["universe"]["latestDailyStockCount"]} 只有当日行情；其中 {data["universe"]["eligibleLatest160BarCount"]} 只满足上市且至少160根。</span></article>
    <article><b>人工检查</b><span>先看前10是否像，再看串型、涨停/停牌/异常单日，以及同一股票是否跨类出现。</span></article>
  </section>
  <nav class="tabs" id="tabs" aria-label="四类形态"></nav>
  <div id="panels"></div>
  <section class="audit">
    <h2>数据泄漏与排序审计</h2>
    <div class="audit-grid">
      <div><b>✅ 查询窗口</b><span>候选只用截至 {data["asOfLabel"]} 的最新固定长度窗口；模板只用拍板起止日。</span></div>
      <div><b>✅ 排序输入</b><span>仅候选窗口与固定模板的归一化前复权收盘路径。</span></div>
      <div><b>✅ 明确排除</b><span>不看窗口后表现、未来收益、IC、策略表现、行业、市值、成交量或异常标记。</span></div>
      <div><b>✅ 重复控制</b><span>每类每只股票只有一个最新窗口；Top30唯一代码数在分组页显示。</span></div>
    </div>
  </section>
</main>
<footer>生成日期 2026-07-29 · 非正式本地评审输出 · 分支 codex/four-template-market-retrieval-review-v1</footer>
<script>
const DATA={payload};
const esc=s=>String(s).replace(/[&<>"]/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}}[c]));
const fmt=n=>Number(n).toLocaleString("zh-CN",{{maximumFractionDigits:2}});
function pathChart(item,accent){{
 const bars=item.bars,W=560,H=185,p={{l:30,r:10,t:12,b:23}},vals=bars.map(b=>b.normalizedClose),lo0=Math.min(...vals),hi0=Math.max(...vals),pad=Math.max((hi0-lo0)*.1,1),lo=lo0-pad,hi=hi0+pad;
 const x=i=>p.l+i*(W-p.l-p.r)/Math.max(vals.length-1,1),y=v=>p.t+(hi-v)*(H-p.t-p.b)/(hi-lo),d=vals.map((v,i)=>(i?"L":"M")+x(i).toFixed(1)+","+y(v).toFixed(1)).join(" ");
 return `<div class="chart"><div class="chart-title"><span>展示路径 · 首日=100（评分使用z标准化）</span><span>${{item.startLabel}} → ${{item.endLabel}}</span></div><svg viewBox="0 0 ${{W}} ${{H}}">${{[lo,(lo+hi)/2,hi].map(t=>`<line x1="${{p.l}}" x2="${{W-p.r}}" y1="${{y(t)}}" y2="${{y(t)}}" stroke="#e5e0d6"/><text x="${{p.l-4}}" y="${{y(t)+3}}" text-anchor="end" font-size="8" fill="#788190">${{t.toFixed(0)}}</text>`).join("")}}<path d="${{d}}" fill="none" stroke="${{accent}}" stroke-width="2.6" stroke-linejoin="round"/><text x="${{p.l}}" y="${{H-6}}" font-size="8" fill="#788190">${{item.startLabel}}</text><text x="${{W-p.r}}" y="${{H-6}}" text-anchor="end" font-size="8" fill="#788190">${{item.endLabel}}</text></svg></div>`;
}}
function candleChart(item){{
 const bars=item.bars,W=560,H=245,p={{l:34,r:10,t:10,b:22}},priceH=157,volTop=182,volH=34,lows=bars.map(b=>b.low),highs=bars.map(b=>b.high),lo=Math.min(...lows),hi=Math.max(...highs),range=hi-lo||1,vmax=Math.max(...bars.map(b=>b.volume)),step=(W-p.l-p.r)/bars.length,body=Math.max(1.2,step*.58);
 const x=i=>p.l+(i+.5)*step,y=v=>p.t+(hi-v)*priceH/range,vy=v=>volTop+volH*(1-v/vmax);
 const marks=bars.map((b,i)=>{{const color=b.close>=b.open?"#d95050":"#159874",yo=y(b.open),yc=y(b.close),top=Math.min(yo,yc),bh=Math.max(Math.abs(yc-yo),1);return `<line x1="${{x(i)}}" x2="${{x(i)}}" y1="${{y(b.high)}}" y2="${{y(b.low)}}" stroke="${{color}}"/><rect x="${{x(i)-body/2}}" y="${{top}}" width="${{body}}" height="${{bh}}" fill="${{color}}"><title>${{b.date}} O${{b.open}} H${{b.high}} L${{b.low}} C${{b.close}}</title></rect><rect x="${{x(i)-body/2}}" y="${{vy(b.volume)}}" width="${{body}}" height="${{volTop+volH-vy(b.volume)}}" fill="${{color}}" opacity=".6"/>`;}}).join("");
 return `<div class="chart"><div class="chart-title"><span>原始前复权K线 + 成交量</span><span>红涨 · 绿跌</span></div><svg viewBox="0 0 ${{W}} ${{H}}">${{[0,.5,1].map(r=>`<line x1="${{p.l}}" x2="${{W-p.r}}" y1="${{p.t+r*priceH}}" y2="${{p.t+r*priceH}}" stroke="#e5e0d6"/>`).join("")}}<text x="${{p.l-4}}" y="${{p.t+4}}" text-anchor="end" font-size="8" fill="#788190">${{hi.toFixed(2)}}</text><text x="${{p.l-4}}" y="${{p.t+priceH}}" text-anchor="end" font-size="8" fill="#788190">${{lo.toFixed(2)}}</text><line x1="${{p.l}}" x2="${{W-p.r}}" y1="${{volTop}}" y2="${{volTop}}" stroke="#cfc8bb"/>${{marks}}<text x="${{p.l}}" y="${{H-6}}" font-size="8" fill="#788190">${{item.startLabel}}</text><text x="${{W-p.r}}" y="${{H-6}}" text-anchor="end" font-size="8" fill="#788190">${{item.endLabel}}</text></svg></div>`;
}}
function flags(item){{
 const values=item.anomalyFlags.map(x=>`<span class="flag">${{esc(x)}}</span>`);
 if(item.crossCategoryHits.length) values.push(`<span class="flag cross">跨类：${{item.crossCategoryHits.map(x=>esc(x.category)+"#"+x.rank).join("、")}}</span>`);
 if(!values.length) values.push(`<span class="flag clean">未见涨跌停/停牌异常</span>`);
 return `<div class="flags">${{values.join("")}}</div>`;
}}
function facts(item){{
 return `<div class="facts"><div class="fact"><b>${{(item.similarity*100).toFixed(2)}}%</b><span>Pearson相似</span></div><div class="fact"><b>${{item.distance.toFixed(4)}}</b><span>相关距离</span></div><div class="fact"><b>${{item.returnPct>0?"+":""}}${{item.returnPct}}%</b><span>区间涨跌</span></div><div class="fact"><b>${{item.maxDrawdownPct}}%</b><span>最大回撤</span></div><div class="fact"><b>${{esc(item.industry)}}</b><span>申万一级</span></div><div class="fact"><b>${{esc(item.marketCapTier)}}</b><span>${{item.totalMvYi==null?"市值缺失":fmt(item.totalMvYi)+"亿"}}</span></div></div>`;
}}
function resultCard(item,cat){{
 const open=item.rank<=10?" open":"";
 return `<details class="result-card" style="--accent:${{cat.accent}}"${{open}}><summary><div class="result-top"><div><h3>${{esc(item.name)}} <span class="code">${{esc(item.code)}}</span></h3><span class="code">${{item.startLabel}}～${{item.endLabel}} · ${{item.barCount}}根</span></div><div class="rank">#${{item.rank}}</div></div>${{facts(item)}}${{flags(item)}}</summary><div class="result-body"><div class="charts">${{pathChart(item,cat.accent)}}${{candleChart(item)}}</div></div></details>`;
}}
const tabs=document.querySelector("#tabs"),panels=document.querySelector("#panels");
DATA.categories.forEach((cat,index)=>{{
 const diag=DATA.diagnostics.find(x=>x.category===cat.label);
 tabs.insertAdjacentHTML("beforeend",`<button class="tab" aria-selected="${{index===0}}" data-key="${{cat.key}}">${{esc(cat.label)}} · ${{cat.windowBars}}根</button>`);
 panels.insertAdjacentHTML("beforeend",`<section class="panel${{index===0?" active":""}}" id="panel-${{cat.key}}" style="--accent:${{cat.accent}}"><div class="category-head"><div><h2>${{esc(cat.label)}}</h2><p>${{esc(cat.cue)}}</p></div><small>Top${{cat.results.length}} / 候选${{cat.eligibleCount}} · 唯一代码${{diag.uniqueCodes}}<br>前10：涨跌停${{diag.top10WithLimit}} · 停牌${{diag.top10WithSuspension}} · 跨类${{diag.top10CrossCategory}}</small></div><article class="template-card"><div class="template-top"><div><span class="badge">固定主模子</span><h3>${{esc(cat.template.name)}} <span class="code">${{cat.template.code}}</span></h3><div class="code">${{cat.template.startLabel}}～${{cat.template.endLabel}} · ${{cat.template.barCount}}根</div></div></div><div class="charts">${{pathChart(cat.template,cat.accent)}}${{candleChart(cat.template)}}</div></article><div class="result-grid">${{cat.results.map(x=>resultCard(x,cat)).join("")}}</div></section>`);
}});
tabs.addEventListener("click",event=>{{const button=event.target.closest(".tab");if(!button)return;document.querySelectorAll(".tab").forEach(x=>x.setAttribute("aria-selected",String(x===button)));document.querySelectorAll(".panel").forEach(x=>x.classList.toggle("active",x.id==="panel-"+button.dataset.key));}});
</script>
</body>
</html>
"""


def validate(data: dict) -> None:
    if data["dataSource"]["networkUsed"]:
        raise RuntimeError("networkUsed must remain false")
    if data["dataSource"]["sealedFinalRead"]:
        raise RuntimeError("sealedFinalRead must remain false")
    for category in data["categories"]:
        if len(category["results"]) != data["topK"]:
            raise RuntimeError(f"{category['label']}: incomplete top-k")
        codes = [item["code"] for item in category["results"]]
        if len(codes) != len(set(codes)):
            raise RuntimeError(f"{category['label']}: duplicate security in top-k")
        for rank, result in enumerate(category["results"], start=1):
            if result["rank"] != rank:
                raise RuntimeError(f"{category['label']}: rank sequence broken")
            if result["barCount"] != category["windowBars"]:
                raise RuntimeError(f"{category['label']}: window length drift")
            if result["end"] != data["asOf"]:
                raise RuntimeError(f"{category['label']}: result not current")
            if not -1.0 <= result["similarity"] <= 1.0:
                raise RuntimeError(f"{category['label']}: invalid Pearson similarity")
        distances = [item["distance"] for item in category["results"]]
        if distances != sorted(distances):
            raise RuntimeError(f"{category['label']}: results not sorted by distance")


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    if PROJECT_ROOT not in output.parents:
        raise RuntimeError(f"output must stay inside project workspace: {output}")
    if output.exists():
        raise RuntimeError(f"refusing to overwrite existing output: {output}")
    if args.top_k < 10:
        raise RuntimeError("top-k must be at least 10 for visual review")
    output.mkdir(parents=True)

    previous_cwd = Path.cwd()
    os.chdir(ZERO_ROOT)
    try:
        pro = pro_api(str(ZERO_CONFIG))
        data = build_data(pro, args.top_k)
    finally:
        os.chdir(previous_cwd)

    validate(data)
    (output / "review-data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "index.html").write_text(html_document(data), encoding="utf-8")
    print(output / "index.html")
    print(
        json.dumps(
            {
                "asOf": data["asOf"],
                "universe": data["universe"],
                "diagnostics": data["diagnostics"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
