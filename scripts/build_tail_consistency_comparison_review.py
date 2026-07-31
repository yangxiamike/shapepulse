from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
from zer0share import pro_api

from build_four_template_similarity_review import (
    PROJECT_ROOT,
    SEARCH_START,
    TEMPLATES,
    ZERO_CONFIG,
    ZERO_ROOT,
    date_label,
    load_templates,
    pearson_similarity,
    qfq_batch,
    result_payload,
    z_normalized_log_close,
)


DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "outputs"
    / "shape-v2"
    / "tail-consistency-comparison-review-20260729-v2"
)
TOP_K = 15
TAIL_SHARE = 0.20
END_DRAWDOWN_TOLERANCE_PCT = 5.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top-k", type=int, default=TOP_K)
    return parser.parse_args()


def tail_metrics(frame: pd.DataFrame, tail_bars: int) -> dict:
    close = frame["close"].to_numpy(dtype=float)
    tail = close[-tail_bars:]
    log_tail = np.log(tail)
    return {
        "tailReturnPct": float((tail[-1] / tail[0] - 1.0) * 100.0),
        "tailEndDrawdownPct": float((tail[-1] / tail.max() - 1.0) * 100.0),
        "logTail": log_tail,
    }


def tail_correlation(left: np.ndarray, right: np.ndarray) -> float | None:
    left_std = float(left.std())
    right_std = float(right.std())
    if left_std <= 1e-12 or right_std <= 1e-12:
        return None
    left_z = (left - left.mean()) / left_std
    right_z = (right - right.mean()) / right_std
    return float(np.mean(left_z * right_z))


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
        template_frame = pd.DataFrame(templates[item.key]["bars"])
        template_path = z_normalized_log_close(template_frame)
        tail_bars = max(5, int(math.ceil(item.bars * TAIL_SHARE)))
        template_tail = tail_metrics(template_frame, tail_bars)
        end_drawdown_floor = (
            template_tail["tailEndDrawdownPct"] - END_DRAWDOWN_TOLERANCE_PCT
        )

        scored = []
        for code, frame in groups.items():
            if len(frame) < item.bars:
                continue
            window = frame.tail(item.bars).reset_index(drop=True)
            similarity = pearson_similarity(
                z_normalized_log_close(window), template_path
            )
            candidate_tail = tail_metrics(window, tail_bars)
            same_direction = (
                candidate_tail["tailReturnPct"]
                * template_tail["tailReturnPct"]
                >= 0.0
            )
            near_enough_to_tail_high = (
                candidate_tail["tailEndDrawdownPct"] >= end_drawdown_floor
            )
            passed = same_direction and near_enough_to_tail_high
            tail_corr = tail_correlation(
                template_tail["logTail"], candidate_tail["logTail"]
            )
            scored.append(
                {
                    "similarity": similarity,
                    "code": code,
                    "window": window,
                    "tailReturnPct": candidate_tail["tailReturnPct"],
                    "tailEndDrawdownPct": candidate_tail[
                        "tailEndDrawdownPct"
                    ],
                    "tailCorrelation": tail_corr,
                    "sameDirection": same_direction,
                    "nearEnoughToTailHigh": near_enough_to_tail_high,
                    "passed": passed,
                }
            )
        scored.sort(key=lambda value: (-value["similarity"], value["code"]))
        for rank, row in enumerate(scored, start=1):
            row["standardRank"] = rank
        standard_selected = scored[:top_k]
        gated_selected = [row for row in scored if row["passed"]][:top_k]

        def payload(row: dict, display_rank: int, mode: str) -> dict:
            code = row["code"]
            raw_mv = total_mv_map.get(code)
            total_mv = (
                float(raw_mv)
                if raw_mv is not None and pd.notna(raw_mv)
                else None
            )
            result = result_payload(
                frame=row["window"],
                similarity=row["similarity"],
                rank=display_rank,
                name=names.get(code, code),
                industry=industry_map.get(code, ""),
                total_mv=total_mv,
                limit_rows=limits,
                suspension_rows=suspensions,
            )
            result.update(
                {
                    "mode": mode,
                    "standardRank": row["standardRank"],
                    "tailBars": tail_bars,
                    "tailReturnPct": round(row["tailReturnPct"], 2),
                    "tailEndDrawdownPct": round(
                        row["tailEndDrawdownPct"], 2
                    ),
                    "tailCorrelation": (
                        round(row["tailCorrelation"], 6)
                        if row["tailCorrelation"] is not None
                        else None
                    ),
                    "sameDirection": row["sameDirection"],
                    "nearEnoughToTailHigh": row[
                        "nearEnoughToTailHigh"
                    ],
                    "tailGatePassed": row["passed"],
                }
            )
            return result

        standard_results = [
            payload(row, rank, "standard")
            for rank, row in enumerate(standard_selected, start=1)
        ]
        gated_results = [
            payload(row, rank, "tail_consistent")
            for rank, row in enumerate(gated_selected, start=1)
        ]
        standard_top10_codes = {
            row["code"] for row in standard_selected[:10]
        }
        gated_top10_codes = {row["code"] for row in gated_selected[:10]}
        categories.append(
            {
                "key": item.key,
                "label": item.label,
                "cue": item.cue,
                "accent": item.accent,
                "windowBars": item.bars,
                "eligibleCount": len(scored),
                "tailGateEligibleCount": sum(row["passed"] for row in scored),
                "tailBars": tail_bars,
                "templateTailReturnPct": round(
                    template_tail["tailReturnPct"], 2
                ),
                "templateTailEndDrawdownPct": round(
                    template_tail["tailEndDrawdownPct"], 2
                ),
                "endDrawdownFloorPct": round(end_drawdown_floor, 2),
                "top10Overlap": len(
                    standard_top10_codes & gated_top10_codes
                ),
                "standardTop10Rejected": [
                    {
                        "rank": row["standardRank"],
                        "name": names.get(row["code"], row["code"]),
                        "code": row["code"],
                        "tailReturnPct": round(row["tailReturnPct"], 2),
                        "tailEndDrawdownPct": round(
                            row["tailEndDrawdownPct"], 2
                        ),
                    }
                    for row in standard_selected[:10]
                    if not row["passed"]
                ],
                "template": {
                    "code": item.code,
                    "name": item.name,
                    "startLabel": date_label(item.start),
                    "endLabel": date_label(item.end),
                    "barCount": item.bars,
                    "tailBars": tail_bars,
                    "tailReturnPct": round(
                        template_tail["tailReturnPct"], 2
                    ),
                    "tailEndDrawdownPct": round(
                        template_tail["tailEndDrawdownPct"], 2
                    ),
                    "bars": templates[item.key]["bars"],
                },
                "standardResults": standard_results,
                "tailConsistentResults": gated_results,
            }
        )

    return {
        "schemaVersion": "tail-consistency-comparison-review/1",
        "status": "similarity_retrieval_method_comparison_not_for_model_evaluation",
        "generatedAt": "2026-07-29",
        "branch": "codex/four-template-market-retrieval-review-v1",
        "asOf": as_of,
        "asOfLabel": date_label(as_of),
        "topK": top_k,
        "dataSource": {
            "provider": "local zer0share",
            "networkUsed": False,
            "sealedFinalRead": False,
        },
        "standardMethod": {
            "score": "Pearson(z(log-close query)), z(log-close candidate))",
            "ranking": "descending full-window Pearson",
        },
        "tailConsistencyGate": {
            "tailShare": TAIL_SHARE,
            "tailBars": "max(5, ceil(window length * 20%))",
            "direction": "candidate tail return has same sign as query tail return",
            "endpoint": "candidate tail-end drawdown is no worse than query tail-end drawdown minus 5 percentage points",
            "rankingAfterGate": "unchanged full-window Pearson order among passing candidates",
            "categoryLabelsUsed": False,
            "futureDataUsed": False,
        },
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
<title>标准 Pearson vs 通用尾端一致性 · 评审页</title>
<style>
:root{{--ink:#172033;--muted:#687083;--paper:#f2efe7;--card:#fffdf8;--line:#d9d3c7;--good:#087a63;--bad:#b54735}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:"Segoe UI","Microsoft YaHei",sans-serif}}
header{{padding:28px clamp(18px,4vw,58px) 24px;background:#172033;color:#fff}}.eyebrow{{font-size:12px;letter-spacing:.14em;color:#cbd5e1;text-transform:uppercase}}
h1{{margin:8px 0;font-size:clamp(25px,3vw,40px)}}header p{{max-width:980px;margin:0;color:#dbe3f2;line-height:1.65}}
.notice{{display:inline-flex;margin-top:14px;padding:7px 11px;border:1px solid #8792a7;border-radius:999px;color:#f5d28d;font-size:12px}}
main{{padding:20px clamp(10px,3vw,42px) 42px}}.summary{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}}
.summary article,.template-card,.result,.audit{{background:var(--card);border:1px solid var(--line);border-radius:13px}}.summary article{{padding:13px}}
.summary b{{display:block;margin-bottom:5px}}.summary span{{font-size:12px;line-height:1.55;color:var(--muted)}}
.tabs{{display:flex;gap:8px;overflow:auto;margin:17px 0 13px}}.tab{{flex:0 0 auto;padding:9px 14px;border:1px solid var(--line);border-radius:999px;background:#fffdf8;font-weight:700;cursor:pointer}}
.tab[aria-selected=true]{{background:#172033;color:#fff;border-color:#172033}}.panel{{display:none}}.panel.active{{display:block}}
.head{{display:flex;justify-content:space-between;gap:12px;align-items:end;margin-bottom:10px;padding-left:12px;border-left:5px solid var(--accent)}}.head h2{{margin:0 0 4px}}.head p{{margin:0;color:var(--muted);font-size:13px}}.head small{{color:var(--muted);text-align:right;line-height:1.5}}
.template-card{{padding:13px;border-top:4px solid var(--accent);margin-bottom:12px}}.template-top,.result-top{{display:flex;justify-content:space-between;gap:8px;align-items:start}}
.template-top h3,.result h3{{margin:0;font-size:17px}}.code{{font:11px ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--muted)}}
.compare{{display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:start}}.column{{min-width:0}}.column-head{{position:sticky;top:0;z-index:2;padding:11px 12px;margin-bottom:8px;background:#172033;color:#fff;border-radius:11px}}
.column-head.adjusted{{background:#087a63}}.column-head b{{display:block}}.column-head span{{font-size:11px;color:#dce5ef;line-height:1.5}}
.results{{display:grid;gap:8px}}.result{{padding:11px;border-top:4px solid var(--accent)}}.result.rejected{{background:#fff8f3;border-color:#e6b6a9}}
.rank{{font-size:22px;font-weight:800;color:var(--accent)}}.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;margin:8px 0}}
.metric{{padding:7px 4px;text-align:center;background:#f4f1e9;border-radius:8px}}.metric b{{display:block;font-size:12px}}.metric span{{font-size:9px;color:var(--muted)}}
.flags{{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:7px}}.pill{{padding:4px 7px;border-radius:999px;font-size:10px;background:#ece8df}}.pill.good{{color:#076d59;background:#e3f5ee}}.pill.bad{{color:#a43f2e;background:#fde8e1}}
.visuals{{display:grid;gap:7px}}.chart{{padding:7px;background:#fbfaf6;border:1px solid #e7e1d6;border-radius:9px}}.chart-label{{display:flex;justify-content:space-between;gap:8px;margin:0 3px 4px;color:var(--muted);font-size:9px}}svg{{display:block;width:100%;height:auto}}
.audit{{margin-top:16px;padding:16px}}.audit h2{{margin:0 0 9px}}.audit-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}}.audit-grid div{{padding:10px;background:#f4f1e9;border-radius:8px;font-size:11px;line-height:1.5;color:var(--muted)}}.audit-grid b{{display:block;color:var(--ink);margin-bottom:3px}}
footer{{padding:0 12px 28px;text-align:center;color:var(--muted);font-size:11px}}
@media(max-width:1000px){{.summary,.audit-grid{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:720px){{.summary,.audit-grid,.compare{{grid-template-columns:1fr}}.head{{align-items:start;flex-direction:column}}.head small{{text-align:left}}.metrics{{grid-template-columns:repeat(2,1fr)}}.column-head{{position:static}}}}
</style>
</head>
<body>
<header>
 <div class="eyebrow">Universal tail consistency comparison</div>
 <h1>标准 Pearson vs 通用尾端一致性</h1>
 <p>不修改模板、不识别类别、不改变任意窗口能力。右侧只使用查询窗口自身最后20%的方向和终点位置做一致性门槛；通过后仍按原始整段 Pearson 排序。</p>
 <div class="notice">method comparison review / not for model evaluation</div>
</header>
<main>
 <section class="summary">
  <article><b>左侧基线</b><span>整段 log-close 独立 z 标准化，按 Pearson 相关降序。</span></article>
  <article><b>右侧调整</b><span>尾端方向必须与模板一致；终点距尾段高点不能比模板差超过5个百分点。</span></article>
  <article><b>通用边界</b><span>尾段固定为任意窗口最后20%，至少5根；不读取健康上涨、抛物线等标签。</span></article>
  <article><b>数据边界</b><span>本机 zer0share，截至 {data["asOfLabel"]}；不看未来表现，不读 sealed final。</span></article>
 </section>
 <nav class="tabs" id="tabs"></nav>
 <div id="panels"></div>
 <section class="audit">
  <h2>怎么判断这次调整</h2>
  <div class="audit-grid">
   <div><b>1. 看尾端</b>右侧前排是否不再出现最近一段持续下降。</div>
   <div><b>2. 看整段</b>右侧是否仍保留左侧中真正肉眼相似的核心股票。</div>
   <div><b>3. 看误伤</b>刚突破等原本尾端一致的类别，前排是否基本不变。</div>
   <div><b>4. 看通用性</b>规则只依赖模板自身尾段，任意窗口都能直接使用。</div>
  </div>
 </section>
</main>
<footer>2026-07-29 · 非正式本地方法对照页 · 不接正式前端</footer>
<script>
const DATA={payload};
const esc=s=>String(s).replace(/[&<>"]/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}}[c]));
function normalizedChart(item,accent){{
 const v=item.bars.map(x=>x.normalizedClose),W=520,H=145,p={{l:26,r:8,t:8,b:18}},lo0=Math.min(...v),hi0=Math.max(...v),pad=Math.max((hi0-lo0)*.1,1),lo=lo0-pad,hi=hi0+pad;
 const x=i=>p.l+i*(W-p.l-p.r)/Math.max(v.length-1,1),y=n=>p.t+(hi-n)*(H-p.t-p.b)/(hi-lo),d=v.map((n,i)=>(i?"L":"M")+x(i).toFixed(1)+","+y(n).toFixed(1)).join(" "),tailStart=v.length-item.tailBars;
 return `<div class="chart"><div class="chart-label"><span>归一化收盘路径 · 首日=100</span><span>最后20%阴影</span></div><svg viewBox="0 0 ${{W}} ${{H}}"><rect x="${{x(tailStart)}}" y="${{p.t}}" width="${{W-p.r-x(tailStart)}}" height="${{H-p.t-p.b}}" fill="${{accent}}" opacity=".07"/><line x1="${{x(tailStart)}}" x2="${{x(tailStart)}}" y1="${{p.t}}" y2="${{H-p.b}}" stroke="${{accent}}" stroke-dasharray="3 3" opacity=".55"/><path d="${{d}}" fill="none" stroke="${{accent}}" stroke-width="2.4" stroke-linejoin="round"/><text x="${{p.l}}" y="${{H-4}}" font-size="8" fill="#788190">${{item.startLabel||""}}</text><text x="${{W-p.r}}" y="${{H-4}}" text-anchor="end" font-size="8" fill="#788190">${{item.endLabel||""}}</text><text x="${{x(tailStart)+4}}" y="${{p.t+10}}" font-size="8" fill="${{accent}}">最后20% · ${{item.tailBars}}根</text></svg></div>`;
}}
function candleChart(item,accent){{
 const b=item.bars,W=520,H=184,p={{l:34,r:8,t:8,b:18}},priceBottom=124,volumeTop=132,volumeBottom=H-p.b;
 const lows=b.map(x=>x.low),highs=b.map(x=>x.high),lo0=Math.min(...lows),hi0=Math.max(...highs),pad=Math.max((hi0-lo0)*.05,.01),lo=lo0-pad,hi=hi0+pad,maxVol=Math.max(...b.map(x=>x.volume),1);
 const step=(W-p.l-p.r)/Math.max(b.length,1),x=i=>p.l+(i+.5)*step,yp=n=>p.t+(hi-n)*(priceBottom-p.t)/(hi-lo),yv=n=>volumeBottom-n*(volumeBottom-volumeTop)/maxVol;
 const bodyW=Math.max(.8,Math.min(5,step*.62)),tailStart=b.length-item.tailBars,tailX=p.l+tailStart*step;
 const candles=b.map((q,i)=>{{const up=q.close>=q.open,color=up?"#e05252":"#159a78",cx=x(i),yo=yp(q.open),yc=yp(q.close),top=Math.min(yo,yc),height=Math.max(Math.abs(yo-yc),.8);return `<line x1="${{cx.toFixed(1)}}" x2="${{cx.toFixed(1)}}" y1="${{yp(q.high).toFixed(1)}}" y2="${{yp(q.low).toFixed(1)}}" stroke="${{color}}" stroke-width="${{Math.max(.6,Math.min(1.1,step*.22)).toFixed(1)}}"/><rect x="${{(cx-bodyW/2).toFixed(1)}}" y="${{top.toFixed(1)}}" width="${{bodyW.toFixed(1)}}" height="${{height.toFixed(1)}}" fill="${{color}}"/>`;}}).join("");
 const volumes=b.map((q,i)=>{{const color=q.close>=q.open?"#e05252":"#159a78",cx=x(i),top=yv(q.volume);return `<rect x="${{(cx-bodyW/2).toFixed(1)}}" y="${{top.toFixed(1)}}" width="${{bodyW.toFixed(1)}}" height="${{Math.max(volumeBottom-top,.6).toFixed(1)}}" fill="${{color}}" opacity=".55"/>`;}}).join("");
 return `<div class="chart"><div class="chart-label"><span>原始前复权 K线 + 成交量</span><span>红涨 · 绿跌</span></div><svg viewBox="0 0 ${{W}} ${{H}}"><rect x="${{tailX.toFixed(1)}}" y="${{p.t}}" width="${{(W-p.r-tailX).toFixed(1)}}" height="${{(volumeBottom-p.t).toFixed(1)}}" fill="${{accent}}" opacity=".055"/><line x1="${{tailX.toFixed(1)}}" x2="${{tailX.toFixed(1)}}" y1="${{p.t}}" y2="${{volumeBottom}}" stroke="${{accent}}" stroke-dasharray="3 3" opacity=".5"/><line x1="${{p.l}}" x2="${{W-p.r}}" y1="${{priceBottom+4}}" y2="${{priceBottom+4}}" stroke="#ded8cc"/><text x="2" y="${{p.t+7}}" font-size="7" fill="#788190">${{hi0.toFixed(2)}}</text><text x="2" y="${{priceBottom}}" font-size="7" fill="#788190">${{lo0.toFixed(2)}}</text>${{candles}}${{volumes}}<text x="${{p.l}}" y="${{H-4}}" font-size="8" fill="#788190">${{item.startLabel||""}}</text><text x="${{W-p.r}}" y="${{H-4}}" text-anchor="end" font-size="8" fill="#788190">${{item.endLabel||""}}</text></svg></div>`;
}}
function charts(item,accent){{
 return `<div class="visuals">${{normalizedChart(item,accent)}}${{candleChart(item,accent)}}</div>`;
}}
function metrics(item){{
 const tail=item.tailCorrelation==null?"—":(item.tailCorrelation*100).toFixed(1)+"%";
 return `<div class="metrics"><div class="metric"><b>${{(item.similarity*100).toFixed(2)}}%</b><span>整段Pearson</span></div><div class="metric"><b>${{tail}}</b><span>尾段Pearson</span></div><div class="metric"><b>${{item.tailReturnPct>0?"+":""}}${{item.tailReturnPct}}%</b><span>尾段涨跌</span></div><div class="metric"><b>${{item.tailEndDrawdownPct}}%</b><span>终点距尾段高点</span></div></div>`;
}}
function card(item,cat,adjusted){{
 const passed=item.tailGatePassed,rankNote=adjusted&&item.standardRank!==item.rank?` · 原榜#${{item.standardRank}}`:"";
 return `<article class="result ${{passed?"":"rejected"}}" style="--accent:${{cat.accent}}"><div class="result-top"><div><h3>${{esc(item.name)}} <span class="code">${{item.code}}</span></h3><span class="code">${{item.startLabel}}～${{item.endLabel}} · ${{item.barCount}}根${{rankNote}}</span></div><div class="rank">#${{item.rank}}</div></div>${{metrics(item)}}<div class="flags"><span class="pill ${{passed?"good":"bad"}}">${{passed?"尾端通过":"尾端不一致"}}</span>${{item.anomalyFlags.map(x=>`<span class="pill">${{esc(x)}}</span>`).join("")}}</div>${{charts(item,cat.accent)}}</article>`;
}}
const tabs=document.querySelector("#tabs"),panels=document.querySelector("#panels");
DATA.categories.forEach((cat,i)=>{{
 tabs.insertAdjacentHTML("beforeend",`<button class="tab" aria-selected="${{i===0}}" data-key="${{cat.key}}">${{esc(cat.label)}} · ${{cat.windowBars}}根</button>`);
 const rejected=cat.standardTop10Rejected.length?cat.standardTop10Rejected.map(x=>`${{x.rank}}.${{esc(x.name)}}`).join("、"):"无";
 panels.insertAdjacentHTML("beforeend",`<section class="panel ${{i===0?"active":""}}" id="panel-${{cat.key}}" style="--accent:${{cat.accent}}"><div class="head"><div><h2>${{esc(cat.label)}}</h2><p>${{esc(cat.cue)}}</p></div><small>尾段${{cat.tailBars}}根 · 模板尾段${{cat.templateTailReturnPct>0?"+":""}}${{cat.templateTailReturnPct}}% · 模板终点距高点${{cat.templateTailEndDrawdownPct}}%<br>右侧通过${{cat.tailGateEligibleCount}}/${{cat.eligibleCount}} · 前十重合${{cat.top10Overlap}} · 左榜剔除：${{rejected}}</small></div><article class="template-card"><div class="template-top"><div><h3>固定模板 · ${{esc(cat.template.name)}} <span class="code">${{cat.template.code}}</span></h3><span class="code">${{cat.template.startLabel}}～${{cat.template.endLabel}} · 尾端门槛：同方向，且终点距尾段高点≥${{cat.endDrawdownFloorPct}}%</span></div></div>${{charts(cat.template,cat.accent)}}</article><div class="compare"><section class="column"><div class="column-head"><b>标准 Pearson</b><span>原始整段排序；红色卡片表示尾端与模板矛盾。</span></div><div class="results">${{cat.standardResults.map(x=>card(x,cat,false)).join("")}}</div></section><section class="column"><div class="column-head adjusted"><b>通用尾端一致性</b><span>只剔除矛盾候选；通过者仍按左侧整段 Pearson 原名次顺序。</span></div><div class="results">${{cat.tailConsistentResults.map(x=>card(x,cat,true)).join("")}}</div></section></div></section>`);
}});
tabs.addEventListener("click",e=>{{const b=e.target.closest(".tab");if(!b)return;document.querySelectorAll(".tab").forEach(x=>x.setAttribute("aria-selected",String(x===b)));document.querySelectorAll(".panel").forEach(x=>x.classList.toggle("active",x.id==="panel-"+b.dataset.key));}});
</script>
</body>
</html>
"""


def validate(data: dict) -> None:
    if data["dataSource"]["networkUsed"]:
        raise RuntimeError("network must remain disabled")
    if data["dataSource"]["sealedFinalRead"]:
        raise RuntimeError("sealed final must remain unread")
    for category in data["categories"]:
        standard = category["standardResults"]
        gated = category["tailConsistentResults"]
        if len(standard) != data["topK"] or len(gated) != data["topK"]:
            raise RuntimeError(f"{category['label']}: incomplete comparison")
        if [x["similarity"] for x in standard] != sorted(
            [x["similarity"] for x in standard], reverse=True
        ):
            raise RuntimeError(f"{category['label']}: standard rank broken")
        if [x["similarity"] for x in gated] != sorted(
            [x["similarity"] for x in gated], reverse=True
        ):
            raise RuntimeError(f"{category['label']}: gated rank broken")
        if not all(x["tailGatePassed"] for x in gated):
            raise RuntimeError(f"{category['label']}: failed item in gated list")
        if not all(x["end"] == data["asOf"] for x in standard + gated):
            raise RuntimeError(f"{category['label']}: stale window")


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    if PROJECT_ROOT not in output.parents:
        raise RuntimeError(f"output must stay inside project workspace: {output}")
    if output.exists():
        raise RuntimeError(f"refusing to overwrite existing output: {output}")
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
    for category in data["categories"]:
        print(
            category["label"],
            f"eligible={category['tailGateEligibleCount']}/{category['eligibleCount']}",
            f"top10_overlap={category['top10Overlap']}",
            "rejected="
            + ",".join(
                item["name"] for item in category["standardTop10Rejected"]
            ),
        )


if __name__ == "__main__":
    main()
