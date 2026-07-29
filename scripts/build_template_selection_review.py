from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from zer0share import pro_api


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ZERO_ROOT = Path(r"C:\Users\hp\Documents\zer0share")
ZERO_CONFIG = ZERO_ROOT / "config" / "settings.toml"


@dataclass(frozen=True)
class Candidate:
    category: str
    role: str
    code: str
    name: str
    start: str
    end: str
    sample_id: str | None
    definition: str
    reason: str
    drawback: str
    purity: str
    segment_base: str | None = None
    segment_peak: str | None = None
    segment_trough: str | None = None


CANDIDATES = [
    Candidate(
        "fresh_breakout",
        "main",
        "603986.SH",
        "兆易创新",
        "20250619",
        "20250829",
        None,
        "长平台缓慢抬升后放量上破，突破后短暂保持。",
        "52根窗口覆盖约两个月蓄势，8月21日至25日连续上破，随后4根仍守在平台上方；窗口终点停在第二次涨停之前。",
        "突破段仍偏强，包含一个涨停日；更适合表达“强突破”，不适合表达温和型突破。",
        "高",
    ),
    Candidate(
        "fresh_breakout",
        "backup",
        "603808.SH",
        "歌力思",
        "20250730",
        "20251022",
        "S-8C9D4D01396A",
        "低波动整理后温和放量上破，并有次日确认。",
        "55根内大部分时间横向消化，末两根以5.35%和1.04%完成突破与确认，单日极值不过度主导。",
        "突破幅度偏温和，若只看归一化路径，视觉冲击不如兆易创新。",
        "很高",
    ),
    Candidate(
        "fresh_breakout",
        "considered",
        "000538.SZ",
        "云南白药",
        "20250618",
        "20250902",
        "S-EB3631EFF29F",
        "窄幅平台后小幅放量创新高。",
        "55根最大回撤小，突破后第1根继续守住，结构最稳定。",
        "突破仅约3%，形态太克制，作为主模子可能把“刚突破”定义得过窄。",
        "高",
    ),
    Candidate(
        "healthy_uptrend",
        "main",
        "601009.SH",
        "南京银行",
        "20240306",
        "20240703",
        "S-71CE133BA6D2",
        "高低点持续抬高，回撤短浅，斜率稳定。",
        "80根上涨约21%，最大回撤约5%；涨幅分布在完整窗口，没有末端抛物线或单日突击。",
        "银行股波动偏低，模板对高波动成长股的容忍度需要后续检索阶段观察。",
        "很高",
    ),
    Candidate(
        "healthy_uptrend",
        "backup",
        "600900.SH",
        "长江电力",
        "20240327",
        "20240724",
        "S-FB4202871453",
        "多个小台阶组成的平稳上升。",
        "80根上涨约28%，最大回撤约3%；每次整理都较短，主趋势贯穿完整窗口。",
        "走势过于平滑，可能比一般股票的“健康上升”更理想化。",
        "很高",
    ),
    Candidate(
        "healthy_uptrend",
        "considered",
        "002532.SZ",
        "天山铝业",
        "20250625",
        "20251022",
        "S-149153362198",
        "较高斜率下的连续阶梯上升。",
        "80根上涨约48%，回撤仍控制在约7%，结构连续。",
        "斜率明显高于前两者，容易把“健康上升”推向强趋势或加速段。",
        "中高",
    ),
    Candidate(
        "pullback_strengthening",
        "main",
        "603391.SH",
        "力聚热能",
        "20250805",
        "20251028",
        "S-BA6BDD717D6E",
        "强第一段上涨后，回吐不超过前涨幅的一半，并已略微重新向上。",
        "55根内先上涨约38%，随后只回吐前涨幅约32%，低点后再回升约9%；终点距前高约1%，三段交易结构清楚。",
        "上市时间较短；第一段上涨集中在约两个月内，代表的是偏强趋势，不是所有温和回调。",
        "很高",
        "20250814",
        "20251015",
        "20251021",
    ),
    Candidate(
        "pullback_strengthening",
        "backup",
        "600029.SH",
        "南方航空",
        "20250903",
        "20251203",
        "S-B0FD9125DF06",
        "较强第一段上涨后回吐约38%，随后重新接近前高。",
        "60根内第一段上涨约26%，回吐前涨幅约38%，低点后回升约7%；结构更稳，但第一段强度低于主模子。",
        "上涨斜率和弹性略弱，作为备选更合适。",
        "高",
        "20250903",
        "20251113",
        "20251125",
    ),
    Candidate(
        "pullback_strengthening",
        "considered",
        "600150.SH",
        "中国船舶",
        "20250611",
        "20250901",
        "S-79457207DE3A",
        "强上涨后浅回撤，再次回到前高附近。",
        "55根内第一段上涨约29%，只回吐前涨幅约28%，低点后回升约7%。",
        "窗口含一个涨停日，单日事件对结构影响较大，因此不升为主模子。",
        "中高",
        "20250612",
        "20250808",
        "20250827",
    ),
    Candidate(
        "parabolic_uptrend",
        "main",
        "001309.SZ",
        "德明利",
        "20251226",
        "20260630",
        None,
        "斜率持续抬升、涨幅向后半段集中，进入高波动加速尾端。",
        "120根从近乎横向转为连续加速，区间约上涨295%；后60根明显比前60根陡，适合作为行业拥挤与尾端风险模子。",
        "多次涨停且最大回撤约20%，极端波动较强；该模子只提示尾端风险，不负责预测精确顶部或做空时点。",
        "高",
    ),
    Candidate(
        "parabolic_uptrend",
        "backup",
        "300502.SZ",
        "新易盛",
        "20250410",
        "20250930",
        None,
        "持续加速的长周期抛物线上升。",
        "120根约上涨570%，四段斜率总体逐级放大，归一化后抛物线结构非常醒目。",
        "创业板单日波动上限更高，含20%大阳线，容易把模板推向过度极端。",
        "很高",
    ),
    Candidate(
        "parabolic_uptrend",
        "considered",
        "300476.SZ",
        "胜宏科技",
        "20250410",
        "20250930",
        None,
        "高斜率上涨并在后半程持续扩张。",
        "120根约上涨325%，后半段加速清楚，适合作为同类证据。",
        "走势更像多个强台阶串联，连续曲率不如德明利和新易盛纯净。",
        "中高",
    ),
]


CATEGORY_META = {
    "fresh_breakout": {
        "label": "刚突破",
        "kicker": "平台 / 蓄势 → 上破 → 少量保持",
        "accent": "#d97706",
    },
    "healthy_uptrend": {
        "label": "健康上升",
        "kicker": "持续抬高 → 回撤受控 → 不末端抛物线",
        "accent": "#0f766e",
    },
    "pullback_strengthening": {
        "label": "回调转强",
        "kicker": "强第一段 → 回吐不超过约一半 → 略微重新向上",
        "accent": "#6d5bd0",
    },
    "parabolic_uptrend": {
        "label": "抛物线上升",
        "kicker": "斜率抬升 → 加速拥挤 → 尾端风险提示",
        "accent": "#be123c",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT
        / "outputs"
        / "shape-v2"
        / "template-selection-review-20260729-v2",
    )
    return parser.parse_args()


def date_label(value: str) -> str:
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def load_candidate(pro, candidate: Candidate) -> dict:
    bars = pro.pro_bar(
        ts_code=candidate.code,
        start_date=candidate.start,
        end_date=candidate.end,
        adj="qfq",
    )
    bars = bars.sort_values("trade_date").reset_index(drop=True)
    if bars.empty:
        raise RuntimeError(f"{candidate.code} {candidate.start}-{candidate.end}: no bars")
    if bars.iloc[0]["trade_date"] != candidate.start:
        raise RuntimeError(
            f"{candidate.code}: requested start {candidate.start}, "
            f"resolved {bars.iloc[0]['trade_date']}"
        )
    if bars.iloc[-1]["trade_date"] != candidate.end:
        raise RuntimeError(
            f"{candidate.code}: requested end {candidate.end}, "
            f"resolved {bars.iloc[-1]['trade_date']}"
        )

    first_close = float(bars.iloc[0]["close"])
    final_close = float(bars.iloc[-1]["close"])
    running_high = first_close
    max_drawdown = 0.0
    rendered_bars = []
    for row in bars.itertuples(index=False):
        close = float(row.close)
        running_high = max(running_high, close)
        max_drawdown = min(max_drawdown, close / running_high - 1.0)
        rendered_bars.append(
            {
                "date": str(row.trade_date),
                "open": round(float(row.open), 4),
                "high": round(float(row.high), 4),
                "low": round(float(row.low), 4),
                "close": round(close, 4),
                "volume": round(float(row.vol), 2),
                "normalizedClose": round(close / first_close * 100.0, 4),
                "pctChange": round(float(row.pct_chg), 4),
            }
        )

    payload = asdict(candidate)
    midpoint_close = float(bars.iloc[len(bars) // 2]["close"])
    gain_denominator = final_close - first_close
    last_20_gain_share = (
        (final_close - float(bars.iloc[-21]["close"])) / gain_denominator * 100.0
        if len(bars) > 20 and gain_denominator > 0
        else None
    )
    segment_metrics = None
    if candidate.segment_base and candidate.segment_peak and candidate.segment_trough:
        indexed = bars.set_index("trade_date")
        base = float(indexed.loc[candidate.segment_base, "close"])
        peak = float(indexed.loc[candidate.segment_peak, "close"])
        trough = float(indexed.loc[candidate.segment_trough, "close"])
        segment_metrics = {
            "baseDate": candidate.segment_base,
            "peakDate": candidate.segment_peak,
            "troughDate": candidate.segment_trough,
            "firstLegAdvancePct": round((peak / base - 1.0) * 100.0, 1),
            "retracementOfAdvancePct": round(
                (peak - trough) / (peak - base) * 100.0, 1
            ),
            "resumptionFromTroughPct": round(
                (final_close / trough - 1.0) * 100.0, 1
            ),
            "endVsPeakPct": round((final_close / peak - 1.0) * 100.0, 1),
        }
    payload.update(
        {
            "startLabel": date_label(candidate.start),
            "endLabel": date_label(candidate.end),
            "barCount": len(rendered_bars),
            "returnPct": round(
                (final_close / first_close - 1.0) * 100.0, 1
            ),
            "maxDrawdownPct": round(max_drawdown * 100.0, 1),
            "maxAbsDayPct": round(float(bars["pct_chg"].abs().max()), 1),
            "firstHalfReturnPct": round(
                (midpoint_close / first_close - 1.0) * 100.0, 1
            ),
            "secondHalfReturnPct": round(
                (final_close / midpoint_close - 1.0) * 100.0, 1
            ),
            "last20GainSharePct": (
                round(last_20_gain_share, 1)
                if last_20_gain_share is not None
                else None
            ),
            "segmentMetrics": segment_metrics,
            "bars": rendered_bars,
        }
    )
    return payload


def html_document(data: dict) -> str:
    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>四形态主K线模子 · V2拍板页</title>
<style>
:root{{--ink:#172033;--muted:#687083;--paper:#f4f1e8;--card:#fffdf8;--line:#dcd6c8;--up:#d95050;--down:#159874}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--paper);color:var(--ink);font-family:"Segoe UI","Microsoft YaHei",sans-serif}}
header{{padding:34px clamp(20px,4vw,64px) 26px;background:#182033;color:#fff}}
.eyebrow{{font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:#cbd5e1}}
h1{{margin:9px 0 10px;font-size:clamp(26px,3vw,42px);line-height:1.12}}
header p{{max-width:900px;margin:0;color:#dbe3f2;line-height:1.7}}
.notice{{display:inline-flex;margin-top:18px;padding:8px 12px;border:1px solid #8994a8;border-radius:999px;color:#f4d08a;font-size:12px;letter-spacing:.04em}}
main{{padding:24px clamp(14px,3vw,44px) 44px}}
.summary{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-bottom:18px}}
.summary article{{padding:16px 18px;background:var(--card);border:1px solid var(--line);border-radius:14px}}
.summary b{{display:block;margin-bottom:6px;font-size:15px}}
.summary span{{color:var(--muted);font-size:13px;line-height:1.55}}
.main-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;align-items:start}}
.category{{--accent:#0f766e;min-width:0;background:var(--card);border:1px solid var(--line);border-top:5px solid var(--accent);border-radius:16px;box-shadow:0 8px 22px rgba(40,35,25,.06);overflow:hidden}}
.category-head{{padding:18px 18px 12px}}
.category-head small{{color:var(--muted)}}
.category h2{{margin:5px 0 3px;font-size:24px}}
.category-head p{{margin:0;color:var(--muted);font-size:13px}}
.pick{{padding:0 14px 16px}}
.stock-line{{display:flex;align-items:baseline;justify-content:space-between;gap:8px;padding:10px 4px 9px}}
.stock-line strong{{font-size:18px}}
.stock-line span{{color:var(--muted);font:12px ui-monospace,SFMono-Regular,Consolas,monospace}}
.badge{{display:inline-flex;margin:0 0 8px;padding:4px 8px;border-radius:999px;background:color-mix(in srgb,var(--accent) 12%,white);color:var(--accent);font-size:12px;font-weight:700}}
.facts{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin:0 0 10px}}
.fact{{padding:8px;background:#f6f3eb;border:1px solid #e5dfd2;border-radius:9px;text-align:center}}
.fact b{{display:block;font-size:13px}}
.fact span{{color:var(--muted);font-size:10px}}
.chart-wrap{{margin-top:8px;padding:8px;background:#fbfaf6;border:1px solid #e6e0d4;border-radius:12px}}
.chart-title{{display:flex;justify-content:space-between;gap:8px;margin:0 2px 5px;color:var(--muted);font-size:10px}}
.chart svg{{display:block;width:100%;height:auto}}
.notes{{display:grid;gap:8px;margin-top:11px}}
.note{{padding:9px 10px;border-left:3px solid var(--accent);background:#f8f6f0;border-radius:0 8px 8px 0;font-size:12px;line-height:1.55}}
.note.warn{{border-left-color:#b45309;background:#fff7e8}}
details{{margin:0 14px 16px;border:1px dashed #cfc7b8;border-radius:11px;background:#faf8f2}}
summary{{cursor:pointer;padding:11px 12px;font-weight:700;font-size:13px}}
.backup{{padding:0 12px 12px}}
.backup .chart-wrap{{background:#fff}}
.candidate-section,.audit{{margin-top:18px;padding:20px;background:var(--card);border:1px solid var(--line);border-radius:16px}}
.candidate-section h2,.audit h2{{margin:0 0 12px;font-size:20px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th,td{{padding:10px 8px;border-top:1px solid #e5dfd4;text-align:left;vertical-align:top;line-height:1.5}}
th{{border-top:0;color:var(--muted);font-weight:600}}
.role-main{{color:#047857;font-weight:700}}.role-backup{{color:#6d5bd0;font-weight:700}}.role-considered{{color:#7c6f5d}}
.audit-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}
.audit-grid div{{padding:12px;background:#f5f2ea;border-radius:10px}}
.audit-grid b{{display:block;margin-bottom:5px;font-size:13px}}
.audit-grid span{{color:var(--muted);font-size:12px;line-height:1.5}}
footer{{padding:20px 14px 32px;text-align:center;color:var(--muted);font-size:12px}}
@media(max-width:1499px){{.main-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.summary{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
@media(max-width:900px){{.main-grid{{grid-template-columns:1fr}}}}
@media(max-width:700px){{.summary,.audit-grid{{grid-template-columns:1fr}}.candidate-section{{overflow:auto}}table{{min-width:900px}}}}
</style>
</head>
<body>
<header>
  <div class="eyebrow">Template Selection Review</div>
  <h1>四形态主 K 线模子 · V2拍板页</h1>
  <p>前三类用于主动发现向上状态；“抛物线上升”用于识别加速拥挤和尾端风险。价格路径按首日收盘归一为 100；下方保留前复权原价 K 线与成交量。</p>
  <div class="notice">template selection review / not for model evaluation</div>
</header>
<main>
  <section class="summary">
    <article><b>数据边界</b><span>仅本机 zer0share 快照；接口 pro_bar；前复权 qfq；未联网、未补数。</span></article>
    <article><b>选择边界</b><span>只看窗口内 OHLCV 和已确认的形态定义；不看窗口之后表现。</span></article>
    <article><b>回调新定义</b><span>强第一段上涨；回吐前涨幅约38%～50%以内；终点已略微重新向上。</span></article>
    <article><b>抛物线定位</b><span>它是尾端风险与行业拥挤提示，不代表必然下跌，也不负责判断精确顶部。</span></article>
  </section>
  <section class="main-grid" id="mainGrid"></section>
  <section class="candidate-section">
    <h2>候选收敛记录</h2>
    <table>
      <thead><tr><th>类别</th><th>结论</th><th>股票</th><th>窗口</th><th>K线</th><th>纯净度</th><th>逐图判断</th></tr></thead>
      <tbody id="candidateRows"></tbody>
    </table>
  </section>
  <section class="audit">
    <h2>数据泄漏审计</h2>
    <div class="audit-grid">
      <div><b>✅ 查询边界</b><span>每只股票仅查询页面标注的精确起止日；生成页不包含窗口之后 K 线。</span></div>
      <div><b>✅ 选择依据</b><span>只使用窗口内价格、成交量、回撤、单日幅度与形态分段。</span></div>
      <div><b>✅ 数据来源</b><span>本机 zer0share；pro_bar(adj="qfq")；仓库既有非 sealed template 候选。</span></div>
      <div><b>✅ 用户先验候选</b><span>德明利由用户先点名；窗口固定截止2026-06-30月末，7月数据不进入页面或选模理由。</span></div>
    </div>
  </section>
</main>
<footer>生成日期 2026-07-29 · V2非正式本地评审页 · 等待用户拍板</footer>
<script>
const DATA={data_json};
const meta=DATA.categoryMeta;
const roleLabel={{main:"主模子推荐",backup:"备选展开",considered:"考虑后未入选"}};
const fmtDate=s=>s.slice(0,4)+"-"+s.slice(4,6)+"-"+s.slice(6);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}}[c]));
function lineChart(item){{
  const W=560,H=190,p={{l:30,r:12,t:15,b:25}},vals=item.bars.map(b=>b.normalizedClose);
  const min=Math.min(...vals),max=Math.max(...vals),pad=Math.max((max-min)*.12,1),lo=min-pad,hi=max+pad;
  const x=i=>p.l+i*(W-p.l-p.r)/(vals.length-1),y=v=>p.t+(hi-v)*(H-p.t-p.b)/(hi-lo);
  const d=vals.map((v,i)=>(i?"L":"M")+x(i).toFixed(1)+","+y(v).toFixed(1)).join(" ");
  const ticks=[lo,(lo+hi)/2,hi];
  const markerSvg=item.segmentMetrics?[["起涨",item.segmentMetrics.baseDate],["前高",item.segmentMetrics.peakDate],["回调低点",item.segmentMetrics.troughDate]].map(([label,date])=>{{const i=item.bars.findIndex(b=>b.date===date),v=vals[i],cy=y(v),ty=Math.max(11,cy-7);return `<circle cx="${{x(i)}}" cy="${{cy}}" r="4" fill="#fff" stroke="${{meta[item.category].accent}}" stroke-width="2"/><text x="${{x(i)}}" y="${{ty}}" text-anchor="middle" font-size="8" fill="#4f5665">${{label}}</text>`;}}).join(""):"";
  return `<div class="chart-wrap"><div class="chart-title"><span>归一化收盘路径 · 首日=100</span><span>${{esc(item.startLabel)}} → ${{esc(item.endLabel)}}</span></div>
  <div class="chart"><svg viewBox="0 0 ${{W}} ${{H}}" aria-label="${{esc(item.name)}}归一化价格路径">
  ${{ticks.map(t=>`<line x1="${{p.l}}" x2="${{W-p.r}}" y1="${{y(t)}}" y2="${{y(t)}}" stroke="#e5e0d6"/><text x="${{p.l-5}}" y="${{y(t)+4}}" text-anchor="end" font-size="9" fill="#7b8493">${{t.toFixed(0)}}</text>`).join("")}}
  <line x1="${{p.l}}" x2="${{W-p.r}}" y1="${{y(100)}}" y2="${{y(100)}}" stroke="#9aa3b1" stroke-dasharray="4 4"/>
  <path d="${{d}}" fill="none" stroke="${{meta[item.category].accent}}" stroke-width="3" stroke-linejoin="round"/>
  ${{markerSvg}}
  <circle cx="${{x(vals.length-1)}}" cy="${{y(vals.at(-1))}}" r="4" fill="${{meta[item.category].accent}}"/>
  <text x="${{p.l}}" y="${{H-7}}" font-size="9" fill="#7b8493">${{item.startLabel}}</text>
  <text x="${{W-p.r}}" y="${{H-7}}" text-anchor="end" font-size="9" fill="#7b8493">${{item.endLabel}}</text>
  </svg></div></div>`;
}}
function candleChart(item){{
  const W=560,H=270,p={{l:34,r:12,t:13,b:24}},priceH=175,volTop=205,volH=40,bars=item.bars;
  const lows=bars.map(b=>b.low),highs=bars.map(b=>b.high),lo=Math.min(...lows),hi=Math.max(...highs),range=hi-lo||1;
  const vmax=Math.max(...bars.map(b=>b.volume)),step=(W-p.l-p.r)/bars.length,body=Math.max(2,step*.58);
  const x=i=>p.l+(i+.5)*step,y=v=>p.t+(hi-v)*priceH/range,vy=v=>volTop+volH*(1-v/vmax);
  const candles=bars.map((b,i)=>{{const up=b.close>=b.open,color=up?"#d95050":"#159874",yo=y(b.open),yc=y(b.close),top=Math.min(yo,yc),h=Math.max(Math.abs(yc-yo),1);return `<line x1="${{x(i)}}" x2="${{x(i)}}" y1="${{y(b.high)}}" y2="${{y(b.low)}}" stroke="${{color}}" stroke-width="1"/><rect x="${{x(i)-body/2}}" y="${{top}}" width="${{body}}" height="${{h}}" fill="${{color}}"><title>${{fmtDate(b.date)}} O${{b.open}} H${{b.high}} L${{b.low}} C${{b.close}} ${{b.pctChange}}%</title></rect><rect x="${{x(i)-body/2}}" y="${{vy(b.volume)}}" width="${{body}}" height="${{volTop+volH-vy(b.volume)}}" fill="${{color}}" opacity=".62"/>`;}}).join("");
  return `<div class="chart-wrap"><div class="chart-title"><span>原价K线（前复权）+ 成交量</span><span>红涨 · 绿跌</span></div>
  <div class="chart"><svg viewBox="0 0 ${{W}} ${{H}}" aria-label="${{esc(item.name)}}K线与成交量">
  ${{[0,.5,1].map(r=>`<line x1="${{p.l}}" x2="${{W-p.r}}" y1="${{p.t+r*priceH}}" y2="${{p.t+r*priceH}}" stroke="#e5e0d6"/>`).join("")}}
  <text x="${{p.l-5}}" y="${{p.t+4}}" text-anchor="end" font-size="9" fill="#7b8493">${{hi.toFixed(2)}}</text>
  <text x="${{p.l-5}}" y="${{p.t+priceH}}" text-anchor="end" font-size="9" fill="#7b8493">${{lo.toFixed(2)}}</text>
  <line x1="${{p.l}}" x2="${{W-p.r}}" y1="${{volTop}}" y2="${{volTop}}" stroke="#cfc8bb"/>
  ${{candles}}
  <text x="${{p.l}}" y="${{H-7}}" font-size="9" fill="#7b8493">${{item.startLabel}}</text>
  <text x="${{W-p.r}}" y="${{H-7}}" text-anchor="end" font-size="9" fill="#7b8493">${{item.endLabel}}</text>
  </svg></div></div>`;
}}
function facts(item){{
 if(item.category==="pullback_strengthening"){{
   const s=item.segmentMetrics;
   return `<div class="facts"><div class="fact"><b>${{item.barCount}}根</b><span>K线窗口</span></div><div class="fact"><b>+${{s.firstLegAdvancePct}}%</b><span>第一段上涨</span></div><div class="fact"><b>${{s.retracementOfAdvancePct}}%</b><span>回吐前涨幅</span></div><div class="fact"><b>+${{s.resumptionFromTroughPct}}%</b><span>低点后回升</span></div></div>`;
 }}
 if(item.category==="parabolic_uptrend"){{
   return `<div class="facts"><div class="fact"><b>${{item.barCount}}根</b><span>K线窗口</span></div><div class="fact"><b>+${{item.returnPct}}%</b><span>区间涨幅</span></div><div class="fact"><b>+${{item.secondHalfReturnPct}}%</b><span>后半程涨幅</span></div><div class="fact"><b>${{item.maxDrawdownPct}}%</b><span>最大回撤</span></div></div>`;
 }}
 return `<div class="facts"><div class="fact"><b>${{item.barCount}}根</b><span>K线窗口</span></div><div class="fact"><b>${{item.returnPct>0?"+":""}}${{item.returnPct}}%</b><span>区间涨跌</span></div><div class="fact"><b>${{item.maxDrawdownPct}}%</b><span>最大回撤</span></div><div class="fact"><b>${{item.maxAbsDayPct}}%</b><span>最大单日</span></div></div>`;
}}
function stock(item,compact=false){{
 return `<div class="stock-line"><strong>${{esc(item.name)}}</strong><span>${{esc(item.code)}} · ${{item.startLabel}}～${{item.endLabel}}</span></div>
 <div class="badge">${{roleLabel[item.role]}}</div>${{facts(item)}}${{lineChart(item)}}${{candleChart(item)}}
 <div class="notes"><div class="note">${{esc(item.definition)}}<br>${{esc(item.reason)}}</div><div class="note warn"><b>主要缺点：</b>${{esc(item.drawback)}}</div></div>`;
}}
const grid=document.querySelector("#mainGrid");
for(const key of ["fresh_breakout","healthy_uptrend","pullback_strengthening","parabolic_uptrend"]){{
 const main=DATA.candidates.find(x=>x.category===key&&x.role==="main");
 const backup=DATA.candidates.find(x=>x.category===key&&x.role==="backup");
 const m=meta[key];
 grid.insertAdjacentHTML("beforeend",`<article class="category" style="--accent:${{m.accent}}">
 <div class="category-head"><small>${{esc(m.kicker)}}</small><h2>${{esc(m.label)}}</h2><p>主模子直接展示；备选可展开对照。</p></div>
 <div class="pick">${{stock(main)}}</div>
 <details><summary>展开备选：${{esc(backup.name)}} · ${{backup.barCount}}根</summary><div class="backup">${{stock(backup,true)}}</div></details>
 </article>`);
}}
const tbody=document.querySelector("#candidateRows");
for(const item of DATA.candidates){{
 tbody.insertAdjacentHTML("beforeend",`<tr><td>${{esc(meta[item.category].label)}}</td><td class="role-${{item.role}}">${{roleLabel[item.role]}}</td><td><b>${{esc(item.name)}}</b><br>${{esc(item.code)}}${{item.sample_id?`<br>${{esc(item.sample_id)}}`:""}}</td><td>${{item.startLabel}}<br>${{item.endLabel}}</td><td>${{item.barCount}}</td><td>${{esc(item.purity)}}</td><td>${{esc(item.reason)}}<br><span style="color:#8a5b16">缺点：${{esc(item.drawback)}}</span></td></tr>`);
}}
</script>
</body>
</html>
"""


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    if PROJECT_ROOT not in output.parents:
        raise RuntimeError(f"output must stay inside project workspace: {output}")
    output.mkdir(parents=True, exist_ok=True)

    previous_cwd = Path.cwd()
    os.chdir(ZERO_ROOT)
    try:
        pro = pro_api(str(ZERO_CONFIG))
        candidates = [load_candidate(pro, item) for item in CANDIDATES]
    finally:
        os.chdir(previous_cwd)

    data = {
        "schemaVersion": "template-selection-review/2",
        "status": "template_selection_review_not_for_model_evaluation",
        "generatedAt": "2026-07-29",
        "branch": "codex/shape-template-selection-review",
        "dataSource": {
            "provider": "local zer0share",
            "root": str(ZERO_ROOT),
            "api": 'pro_bar(adj="qfq")',
            "networkUsed": False,
            "postWindowBarsIncluded": False,
        },
        "categoryMeta": CATEGORY_META,
        "candidates": candidates,
    }
    (output / "review-data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "index.html").write_text(html_document(data), encoding="utf-8")
    print(output / "index.html")
    for item in candidates:
        print(
            item["category"],
            item["role"],
            item["code"],
            item["start"],
            item["end"],
            item["barCount"],
        )


if __name__ == "__main__":
    main()
