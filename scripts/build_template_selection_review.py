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
        "600066.SH",
        "宇通客车",
        "20250903",
        "20251203",
        "S-3F1136639E61",
        "已有上涨基础，随后有序回调，再逐步收复。",
        "60根内先抬升至阶段高点，再经历约9%回撤，末段用多根K线恢复，不依赖单日反抽。",
        "恢复接近前高，时间点略偏“转强确认完成”，不是最早的拐点。",
        "很高",
    ),
    Candidate(
        "pullback_strengthening",
        "backup",
        "001328.SZ",
        "登康口腔",
        "20241028",
        "20250120",
        "S-4D176CB8583F",
        "上升、真实回调、恢复三段结构完整。",
        "60根中上涨基础和约10%回调都清楚，最后5根连续恢复，终点仍未过度脱离前高。",
        "阶段波动比宇通客车更大，1月初有一根6.82%的强阳线。",
        "高",
    ),
    Candidate(
        "pullback_strengthening",
        "considered",
        "603520.SH",
        "司太立",
        "20250618",
        "20250902",
        "S-5BF82CD54A43",
        "上涨后回调并快速恢复。",
        "55根三段结构可辨，末段确有收复。",
        "窗口含涨停及较大波动，个股噪声较强，不适合做主模子。",
        "中",
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
        "kicker": "上涨基础 → 回撤 / 整理 → 重新转强",
        "accent": "#6d5bd0",
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
        / "template-selection-review-20260729",
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
    payload.update(
        {
            "startLabel": date_label(candidate.start),
            "endLabel": date_label(candidate.end),
            "barCount": len(rendered_bars),
            "returnPct": round(
                (float(bars.iloc[-1]["close"]) / first_close - 1.0) * 100.0, 1
            ),
            "maxDrawdownPct": round(max_drawdown * 100.0, 1),
            "maxAbsDayPct": round(float(bars["pct_chg"].abs().max()), 1),
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
<title>三形态主K线模子 · 拍板页</title>
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
.summary{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-bottom:18px}}
.summary article{{padding:16px 18px;background:var(--card);border:1px solid var(--line);border-radius:14px}}
.summary b{{display:block;margin-bottom:6px;font-size:15px}}
.summary span{{color:var(--muted);font-size:13px;line-height:1.55}}
.main-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;align-items:start}}
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
.facts{{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:0 0 10px}}
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
@media(max-width:1080px){{.main-grid{{grid-template-columns:1fr}}.summary{{grid-template-columns:1fr 1fr 1fr}}}}
@media(max-width:700px){{.summary,.audit-grid{{grid-template-columns:1fr}}.candidate-section{{overflow:auto}}table{{min-width:900px}}}}
</style>
</head>
<body>
<header>
  <div class="eyebrow">Template Selection Review</div>
  <h1>三形态主 K 线模子 · 拍板页</h1>
  <p>本页只比较模子本身是否清楚、纯净、具有代表性。价格路径按首日收盘归一为 100；下方保留前复权原价 K 线与成交量，便于同时判断结构与个股噪声。</p>
  <div class="notice">template selection review / not for model evaluation</div>
</header>
<main>
  <section class="summary">
    <article><b>数据边界</b><span>仅本机 zer0share 快照；接口 pro_bar；前复权 qfq；未联网、未补数。</span></article>
    <article><b>选择边界</b><span>只看窗口内 OHLCV 和已确认的形态定义；不看窗口之后表现。</span></article>
    <article><b>本轮不做</b><span>不改算法、评分器、正式前端；不做未来收益、IC、策略与 sealed final。</span></article>
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
      <div><b>✅ 明确未看</b><span>未打开 sealed final evaluation；未使用窗口后收益、IC、命中率或策略结果。</span></div>
    </div>
  </section>
</main>
<footer>生成日期 2026-07-29 · 非正式本地评审页 · 等待用户拍板</footer>
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
  return `<div class="chart-wrap"><div class="chart-title"><span>归一化收盘路径 · 首日=100</span><span>${{esc(item.startLabel)}} → ${{esc(item.endLabel)}}</span></div>
  <div class="chart"><svg viewBox="0 0 ${{W}} ${{H}}" aria-label="${{esc(item.name)}}归一化价格路径">
  ${{ticks.map(t=>`<line x1="${{p.l}}" x2="${{W-p.r}}" y1="${{y(t)}}" y2="${{y(t)}}" stroke="#e5e0d6"/><text x="${{p.l-5}}" y="${{y(t)+4}}" text-anchor="end" font-size="9" fill="#7b8493">${{t.toFixed(0)}}</text>`).join("")}}
  <line x1="${{p.l}}" x2="${{W-p.r}}" y1="${{y(100)}}" y2="${{y(100)}}" stroke="#9aa3b1" stroke-dasharray="4 4"/>
  <path d="${{d}}" fill="none" stroke="${{meta[item.category].accent}}" stroke-width="3" stroke-linejoin="round"/>
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
 return `<div class="facts"><div class="fact"><b>${{item.barCount}}根</b><span>K线窗口</span></div><div class="fact"><b>${{item.returnPct>0?"+":""}}${{item.returnPct}}%</b><span>区间涨跌</span></div><div class="fact"><b>${{item.maxDrawdownPct}}%</b><span>最大回撤</span></div></div>`;
}}
function stock(item,compact=false){{
 return `<div class="stock-line"><strong>${{esc(item.name)}}</strong><span>${{esc(item.code)}} · ${{item.startLabel}}～${{item.endLabel}}</span></div>
 <div class="badge">${{roleLabel[item.role]}}</div>${{facts(item)}}${{lineChart(item)}}${{candleChart(item)}}
 <div class="notes"><div class="note">${{esc(item.definition)}}<br>${{esc(item.reason)}}</div><div class="note warn"><b>主要缺点：</b>${{esc(item.drawback)}}</div></div>`;
}}
const grid=document.querySelector("#mainGrid");
for(const key of ["fresh_breakout","healthy_uptrend","pullback_strengthening"]){{
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
        "schemaVersion": "template-selection-review/1",
        "status": "template_selection_review_not_for_model_evaluation",
        "generatedAt": "2026-07-29",
        "branch": "detached HEAD at d503991",
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
