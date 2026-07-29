from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from zer0share import pro_api

from build_four_template_similarity_review import (
    PROJECT_ROOT,
    SEARCH_START,
    ZERO_CONFIG,
    ZERO_ROOT,
    date_label,
    max_drawdown_pct,
    pearson_similarity,
    qfq_batch,
    render_bars,
    result_payload,
    z_normalized_log_close,
)


DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "outputs"
    / "shape-v2"
    / "template-cleanup-comparison-review-20260729-v2"
)
TOP_K = 12


@dataclass(frozen=True)
class DraftTemplate:
    category: str
    label: str
    role: str
    code: str
    name: str
    start: str
    end: str
    bars: int
    accent: str
    note: str


TEMPLATES = (
    DraftTemplate("fresh_breakout", "刚突破", "original", "603986.SH", "兆易创新", "20250619", "20250827", 50, "#d97706", "原模子：突破后保留三根震荡确认。"),
    DraftTemplate("fresh_breakout", "刚突破", "draft", "603986.SH", "兆易创新", "20250617", "20250825", 50, "#d97706", "清理稿：窗口前移两根，结束在突破后的第一根小实体K线。"),
    DraftTemplate("healthy_uptrend", "健康上涨", "original", "601009.SH", "南京银行", "20240306", "20240703", 80, "#0f766e", "原模子：主体稳定，但最后三根冲高回落。"),
    DraftTemplate("healthy_uptrend", "健康上涨", "draft", "600900.SH", "长江电力", "20240327", "20240724", 80, "#0f766e", "替代稿：多个小台阶持续抬高，最大回撤更小。"),
    DraftTemplate("pullback_strengthening", "回调转强", "original", "603391.SH", "力聚热能", "20250805", "20251028", 55, "#6d5bd0", "原模子：第一段上涨占比较长，回调与走强集中在尾段。"),
    DraftTemplate("pullback_strengthening", "回调转强", "draft", "600029.SH", "南方航空", "20250903", "20251203", 60, "#6d5bd0", "替代稿：上涨、回调、再接近前高三段更均衡。"),
    DraftTemplate("parabolic_uptrend", "抛物线上升", "original", "001309.SZ", "德明利", "20251031", "20260630", 160, "#be123c", "原模子：加速明显，但中间最大回撤约35%。"),
    DraftTemplate("parabolic_uptrend", "抛物线上升", "draft", "300502.SZ", "新易盛", "20250410", "20250930", 120, "#be123c", "替代稿：连续曲率更清楚；仍需留意创业板20%大阳线。"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top-k", type=int, default=TOP_K)
    return parser.parse_args()


def load_template(pro, item: DraftTemplate) -> tuple[pd.DataFrame, dict]:
    frame = pro.pro_bar(
        ts_code=item.code,
        start_date=item.start,
        end_date=item.end,
        adj="qfq",
    ).sort_values("trade_date").reset_index(drop=True)
    if len(frame) != item.bars:
        raise RuntimeError(f"{item.label}/{item.role}: expected {item.bars}, got {len(frame)}")
    if str(frame.iloc[0]["trade_date"]) != item.start or str(frame.iloc[-1]["trade_date"]) != item.end:
        raise RuntimeError(f"{item.label}/{item.role}: template date drift")
    close = frame["close"].to_numpy(dtype=float)
    return frame, {
        "role": item.role,
        "code": item.code,
        "name": item.name,
        "start": item.start,
        "end": item.end,
        "startLabel": date_label(item.start),
        "endLabel": date_label(item.end),
        "barCount": item.bars,
        "returnPct": round((close[-1] / close[0] - 1) * 100, 2),
        "maxDrawdownPct": round(max_drawdown_pct(close), 2),
        "maxAbsDayPct": round(float(frame["pct_chg"].abs().max()), 2),
        "note": item.note,
        "bars": render_bars(frame),
    }


def build_data(pro, top_k: int) -> dict:
    loaded = {}
    for item in TEMPLATES:
        loaded[(item.category, item.role)] = load_template(pro, item)

    daily = pro.daily(start_date=SEARCH_START, end_date="20261231")
    as_of = str(daily["trade_date"].max())
    daily = daily[daily["trade_date"] <= as_of].copy()
    adjusted = qfq_batch(
        daily,
        pro.adj_factor(start_date=SEARCH_START, end_date=as_of),
    )
    listed = pro.stock_basic(list_status="L")
    listed = listed[listed["ts_code"].astype(str).str.endswith((".SH", ".SZ", ".BJ"))].copy()
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

    groups = {}
    minimum_window = min(x.bars for x in TEMPLATES)
    for code, frame in adjusted.groupby("ts_code", sort=False):
        if code not in listed_codes:
            continue
        ordered = frame.sort_values("trade_date").reset_index(drop=True)
        if str(ordered.iloc[-1]["trade_date"]) != as_of or len(ordered) < minimum_window:
            continue
        groups[str(code)] = ordered

    categories = []
    for category in dict.fromkeys(x.category for x in TEMPLATES):
        items = [x for x in TEMPLATES if x.category == category]
        variants = []
        for item in items:
            template_frame, template_payload = loaded[(item.category, item.role)]
            template_path = z_normalized_log_close(template_frame)
            scored = []
            for code, frame in groups.items():
                if len(frame) < item.bars:
                    continue
                window = frame.tail(item.bars).reset_index(drop=True)
                similarity = pearson_similarity(z_normalized_log_close(window), template_path)
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
            variants.append(
                {
                    "role": item.role,
                    "windowBars": item.bars,
                    "eligibleCount": len(scored),
                    "template": template_payload,
                    "results": results,
                    "top10TailNegativeCount": sum(
                        (
                            result["bars"][-1]["close"]
                            / result["bars"][
                                -max(5, math.ceil(len(result["bars"]) * 0.2))
                            ]["close"]
                            - 1
                        )
                        < 0
                        for result in results[:10]
                    ),
                    "top10DeepEndDrawdownCount": sum(
                        (
                            result["bars"][-1]["close"]
                            / max(
                                bar["close"]
                                for bar in result["bars"][
                                    -max(5, math.ceil(len(result["bars"]) * 0.2)) :
                                ]
                            )
                            - 1
                        )
                        < -0.1
                        for result in results[:10]
                    ),
                }
            )
        original_codes = {x["code"] for x in variants[0]["results"][:10]}
        draft_codes = {x["code"] for x in variants[1]["results"][:10]}
        categories.append(
            {
                "key": category,
                "label": items[0].label,
                "accent": items[0].accent,
                "top10Overlap": len(original_codes & draft_codes),
                "variants": variants,
            }
        )

    return {
        "schemaVersion": "template-cleanup-comparison-review/1",
        "status": "template_cleanup_review_not_for_model_evaluation",
        "generatedAt": "2026-07-29",
        "branch": "codex/four-template-market-retrieval-review-v1",
        "asOf": as_of,
        "asOfLabel": date_label(as_of),
        "topK": top_k,
        "dataSource": {
            "provider": "local zer0share",
            "networkUsed": False,
            "sealedFinalRead": False,
            "futureWindowDataUsed": False,
        },
        "method": {
            "score": "Pearson(z(log qfq close query), z(log qfq close candidate))",
            "window": "each template keeps its displayed bar count",
            "tailGateUsed": False,
            "categorySpecificScoringUsed": False,
        },
        "categories": categories,
    }


def html_document(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    html = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:,"><title>原模子 vs 清理稿 · 标准 Pearson 对照</title>
<style>
:root{--ink:#162033;--muted:#687083;--paper:#f2efe7;--card:#fffdf8;--line:#d9d3c7}*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:"Segoe UI","Microsoft YaHei",sans-serif}
header{padding:28px clamp(18px,4vw,58px) 24px;background:#162033;color:#fff}h1{margin:7px 0;font-size:clamp(26px,3vw,40px)}
header p{max-width:980px;margin:0;color:#dbe3f2;line-height:1.65}.eyebrow{font-size:12px;letter-spacing:.14em;color:#cbd5e1}
.notice{display:inline-flex;margin-top:14px;padding:7px 11px;border:1px solid #8792a7;border-radius:999px;color:#f5d28d;font-size:12px}
main{padding:19px clamp(10px,3vw,42px) 42px}.summary{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.summary div,.template,.result{background:var(--card);border:1px solid var(--line);border-radius:13px}
.summary div{padding:13px}.summary b{display:block;margin-bottom:5px}.summary span{font-size:12px;color:var(--muted);line-height:1.55}
.tabs{display:flex;gap:8px;overflow:auto;margin:17px 0 13px}.tab{flex:0 0 auto;padding:9px 14px;border:1px solid var(--line);border-radius:999px;background:#fffdf8;font-weight:700;cursor:pointer}.tab[aria-selected=true]{background:#162033;color:#fff}
.panel{display:none}.panel.active{display:block}.panel-head{display:flex;justify-content:space-between;gap:10px;align-items:end;padding-left:12px;border-left:5px solid var(--accent);margin-bottom:10px}.panel-head h2{margin:0}.panel-head span{font-size:12px;color:var(--muted)}
.compare{display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:start}.column{min-width:0}.column-title{padding:11px 12px;border-radius:11px 11px 0 0;background:#162033;color:#fff}.column-title.draft{background:#087a63}.column-title b{display:block}.column-title span{font-size:11px;color:#dce5ef}
.template{padding:11px;border-top:4px solid var(--accent);border-radius:0 0 13px 13px;margin-bottom:8px}.top{display:flex;justify-content:space-between;gap:8px}.top h3{margin:0;font-size:17px}.code{font:10px ui-monospace,Consolas,monospace;color:var(--muted)}
.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;margin:8px 0}.metric{padding:7px 4px;background:#f4f1e9;border-radius:8px;text-align:center}.metric b{display:block;font-size:12px}.metric span{font-size:9px;color:var(--muted)}
.note{margin:5px 0 8px;font-size:11px;line-height:1.5;color:var(--muted)}.results{display:grid;gap:8px}.result{padding:10px;border-top:3px solid var(--accent)}.rank{font-size:21px;font-weight:800;color:var(--accent)}
.flags{display:flex;gap:5px;flex-wrap:wrap;margin:6px 0}.pill{padding:4px 7px;border-radius:999px;font-size:9px;background:#ece8df}
.visuals{display:grid;gap:6px}.chart{padding:6px;background:#fbfaf6;border:1px solid #e7e1d6;border-radius:9px}.chart-label{display:flex;justify-content:space-between;font-size:8px;color:var(--muted);margin:0 2px 3px}svg{display:block;width:100%;height:auto}
footer{padding:0 12px 28px;text-align:center;color:var(--muted);font-size:11px}@media(max-width:720px){.summary,.compare{grid-template-columns:1fr}.panel-head{align-items:start;flex-direction:column}.metrics{grid-template-columns:repeat(3,1fr)}}
</style></head><body>
<header><div class="eyebrow">TEMPLATE CLEANUP COMPARISON</div><h1>原模子 vs 清理稿</h1><p>只更换或清理查询模板，不加尾端过滤，不改标准 Pearson。目的是判断前排问题究竟来自模板细节，还是来自通用算法。</p><div class="notice">template cleanup review / not for model evaluation</div></header>
<main><section class="summary"><div><b>算法不变</b><span>前复权 log-close 独立 z 标准化，整段 Pearson 降序。</span></div><div><b>只动模板</b><span>右侧缩短多余尾巴，或换用现有非 sealed 备选模子。</span></div><div><b>数据边界</b><span>本机 zer0share，截至 <i id="asof"></i>；不看未来，不读 sealed final。</span></div></section><nav class="tabs" id="tabs"></nav><div id="panels"></div></main>
<footer>非正式本地模板清理评审页 · 不接正式前端</footer>
<script>
const DATA=__PAYLOAD__; const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
document.querySelector("#asof").textContent=DATA.asOfLabel;
function lineChart(item,accent){const b=item.bars,v=b.map(x=>x.normalizedClose),W=520,H=116,p={l:25,r:7,t:6,b:16},lo0=Math.min(...v),hi0=Math.max(...v),pad=Math.max((hi0-lo0)*.08,1),lo=lo0-pad,hi=hi0+pad,x=i=>p.l+i*(W-p.l-p.r)/Math.max(v.length-1,1),y=n=>p.t+(hi-n)*(H-p.t-p.b)/(hi-lo),d=v.map((n,i)=>(i?"L":"M")+x(i).toFixed(1)+","+y(n).toFixed(1)).join(" ");return `<div class="chart"><div class="chart-label"><span>归一化收盘路径</span><span>首日=100</span></div><svg viewBox="0 0 ${W} ${H}"><path d="${d}" fill="none" stroke="${accent}" stroke-width="2.2"/><text x="${p.l}" y="${H-3}" font-size="7" fill="#788190">${item.startLabel}</text><text x="${W-p.r}" y="${H-3}" text-anchor="end" font-size="7" fill="#788190">${item.endLabel}</text></svg></div>`}
function candleChart(item){const b=item.bars,W=520,H=146,p={l:31,r:7,t:5,b:15},pb=96,vt=103,vb=H-p.b,lows=b.map(x=>x.low),highs=b.map(x=>x.high),lo0=Math.min(...lows),hi0=Math.max(...highs),pad=Math.max((hi0-lo0)*.04,.01),lo=lo0-pad,hi=hi0+pad,mv=Math.max(...b.map(x=>x.volume),1),step=(W-p.l-p.r)/b.length,x=i=>p.l+(i+.5)*step,yp=n=>p.t+(hi-n)*(pb-p.t)/(hi-lo),yv=n=>vb-n*(vb-vt)/mv,bw=Math.max(.7,Math.min(4.5,step*.62)),cs=b.map((q,i)=>{const col=q.close>=q.open?"#e05252":"#159a78",cx=x(i),yo=yp(q.open),yc=yp(q.close),top=Math.min(yo,yc),h=Math.max(Math.abs(yo-yc),.7);return `<line x1="${cx}" x2="${cx}" y1="${yp(q.high)}" y2="${yp(q.low)}" stroke="${col}" stroke-width=".8"/><rect x="${cx-bw/2}" y="${top}" width="${bw}" height="${h}" fill="${col}"/>`}).join(""),vs=b.map((q,i)=>{const col=q.close>=q.open?"#e05252":"#159a78",cx=x(i),top=yv(q.volume);return `<rect x="${cx-bw/2}" y="${top}" width="${bw}" height="${Math.max(vb-top,.5)}" fill="${col}" opacity=".5"/>`}).join("");return `<div class="chart"><div class="chart-label"><span>原始前复权K线 + 成交量</span><span>红涨 · 绿跌</span></div><svg viewBox="0 0 ${W} ${H}"><line x1="${p.l}" x2="${W-p.r}" y1="${pb+3}" y2="${pb+3}" stroke="#ded8cc"/>${cs}${vs}<text x="${p.l}" y="${H-3}" font-size="7" fill="#788190">${item.startLabel}</text><text x="${W-p.r}" y="${H-3}" text-anchor="end" font-size="7" fill="#788190">${item.endLabel}</text></svg></div>`}
function charts(x,a){return `<div class="visuals">${lineChart(x,a)}${candleChart(x)}</div>`}
function template(t,a){return `<article class="template"><div class="top"><div><h3>${esc(t.name)} <span class="code">${t.code}</span></h3><span class="code">${t.startLabel}～${t.endLabel} · ${t.barCount}根</span></div></div><div class="metrics"><div class="metric"><b>${t.returnPct>0?"+":""}${t.returnPct}%</b><span>区间涨跌</span></div><div class="metric"><b>${t.maxDrawdownPct}%</b><span>最大回撤</span></div><div class="metric"><b>${t.maxAbsDayPct}%</b><span>最大单日</span></div></div><p class="note">${esc(t.note)}</p>${charts(t,a)}</article>`}
function result(x,a){return `<article class="result"><div class="top"><div><h3>${esc(x.name)} <span class="code">${x.code}</span></h3><span class="code">${x.startLabel}～${x.endLabel} · ${x.barCount}根</span></div><div class="rank">#${x.rank}</div></div><div class="metrics"><div class="metric"><b>${(x.similarity*100).toFixed(2)}%</b><span>Pearson</span></div><div class="metric"><b>${x.returnPct>0?"+":""}${x.returnPct}%</b><span>区间涨跌</span></div><div class="metric"><b>${x.maxDrawdownPct}%</b><span>最大回撤</span></div></div><div class="flags"><span class="pill">${esc(x.industry)}</span><span class="pill">${esc(x.marketCapTier)}</span>${x.anomalyFlags.map(y=>`<span class="pill">${esc(y)}</span>`).join("")}</div>${charts(x,a)}</article>`}
const tabs=document.querySelector("#tabs"),panels=document.querySelector("#panels");DATA.categories.forEach((c,i)=>{tabs.insertAdjacentHTML("beforeend",`<button class="tab" aria-selected="${i===0}" data-key="${c.key}">${esc(c.label)}</button>`);const cols=c.variants.map((v,j)=>`<section class="column"><div class="column-title ${j?"draft":""}"><b>${j?"清理稿 / 替代稿":"原模子"}</b><span>${v.windowBars}根 · 前十尾段下跌 ${v.top10TailNegativeCount}/10 · 尾段高点回撤超10% ${v.top10DeepEndDrawdownCount}/10</span></div>${template(v.template,c.accent)}<div class="results">${v.results.map(x=>result(x,c.accent)).join("")}</div></section>`).join("");panels.insertAdjacentHTML("beforeend",`<section class="panel ${i===0?"active":""}" id="panel-${c.key}" style="--accent:${c.accent}"><div class="panel-head"><h2>${esc(c.label)}</h2><span>两边前十重合 ${c.top10Overlap}/10</span></div><div class="compare">${cols}</div></section>`)});tabs.addEventListener("click",e=>{const b=e.target.closest(".tab");if(!b)return;document.querySelectorAll(".tab").forEach(x=>x.setAttribute("aria-selected",String(x===b)));document.querySelectorAll(".panel").forEach(x=>x.classList.toggle("active",x.id==="panel-"+b.dataset.key))});
</script></body></html>"""
    return html.replace("__PAYLOAD__", payload)


def validate(data: dict) -> None:
    if data["dataSource"]["networkUsed"] or data["dataSource"]["sealedFinalRead"]:
        raise RuntimeError("data boundary violation")
    if data["method"]["tailGateUsed"]:
        raise RuntimeError("tail gate must stay disabled")
    for category in data["categories"]:
        if len(category["variants"]) != 2:
            raise RuntimeError(f"{category['label']}: expected two variants")
        for variant in category["variants"]:
            if len(variant["results"]) != data["topK"]:
                raise RuntimeError(f"{category['label']}: incomplete ranking")
            scores = [x["similarity"] for x in variant["results"]]
            if scores != sorted(scores, reverse=True):
                raise RuntimeError(f"{category['label']}: rank order broken")
            if not all(x["end"] == data["asOf"] for x in variant["results"]):
                raise RuntimeError(f"{category['label']}: stale candidate window")


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    if PROJECT_ROOT not in output.parents:
        raise RuntimeError(f"output must stay inside project: {output}")
    if output.exists():
        raise RuntimeError(f"refusing to overwrite: {output}")
    output.mkdir(parents=True)
    previous_cwd = Path.cwd()
    os.chdir(ZERO_ROOT)
    try:
        data = build_data(pro_api(str(ZERO_CONFIG)), args.top_k)
    finally:
        os.chdir(previous_cwd)
    validate(data)
    (output / "review-data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "index.html").write_text(html_document(data), encoding="utf-8")
    print(output / "index.html")
    for category in data["categories"]:
        left, right = category["variants"]
        print(
            category["label"],
            f"top10_overlap={category['top10Overlap']}",
            "original=" + ",".join(x["name"] for x in left["results"][:5]),
            "draft=" + ",".join(x["name"] for x in right["results"][:5]),
        )


if __name__ == "__main__":
    main()
