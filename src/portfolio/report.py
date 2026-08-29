"""分析結果を自己完結の HTML（インライン SVG、外部依存なし）として書き出す。"""
from __future__ import annotations

import html
import math
from datetime import datetime

from portfolio.analysis import ASSET_CLASSES, Analysis

# カテゴリ色: 固定順スロット（dataviz 既定パレット、CVD 検証済みの順序）。資産クラスの表示順に対応させる。
_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7"]
_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9"]
_CLASS_SLOT = {c: i for i, c in enumerate(ASSET_CLASSES)}


def _esc(s) -> str:
    return html.escape(str(s))


def _yen(v: float) -> str:
    return f"{v:,.0f}"


def _man(v: float) -> str:
    return f"{v / 10000:,.0f}万円"


def _pct(v: float, d: int = 1) -> str:
    return f"{v:.{d}f}%"


def _css() -> str:
    light = "".join(f"--s{i}:{c};" for i, c in enumerate(_LIGHT))
    dark = "".join(f"--s{i}:{c};" for i, c in enumerate(_DARK))
    return f"""
:root{{color-scheme:light dark;--bg:#fcfcfb;--card:#ffffff;--ink:#0b0b0b;--ink2:#52514e;--ink3:#8a8985;--line:#e6e5e1;--grid:#eeede9;{light}}}
@media (prefers-color-scheme: dark){{:root{{--bg:#1a1a19;--card:#232322;--ink:#ffffff;--ink2:#c3c2b7;--ink3:#8f8e88;--line:#3a3a37;--grid:#2e2e2c;{dark}}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,"Segoe UI","Hiragino Sans","Noto Sans JP",sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:24px 20px 60px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:32px 0 12px;color:var(--ink)}}
.sub{{color:var(--ink2);margin:0 0 20px}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}}
.tile{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px}}
.tile .k{{font-size:12px;color:var(--ink2)}} .tile .v{{font-size:22px;font-weight:600;letter-spacing:-.01em}} .tile .d{{font-size:12px;color:var(--ink3)}}
.row{{display:grid;grid-template-columns:1fr 1fr;gap:16px}} @media (max-width:760px){{.row{{grid-template-columns:1fr}}}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px;overflow-x:auto}}
.card h3{{margin:0 0 8px;font-size:14px}}
table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}} th,td{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}
th{{color:var(--ink2);font-weight:500;font-size:12px}} td:first-child,th:first-child{{text-align:left}} td.l{{text-align:left}}
.sw{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}}
.legend{{display:flex;flex-wrap:wrap;gap:6px 16px;margin:8px 0 0;font-size:12px;color:var(--ink2)}}
svg text{{fill:var(--ink2);font-size:11px}} svg .lab{{fill:var(--ink);font-size:12px;font-weight:600}}
.tip{{position:fixed;pointer-events:none;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:8px 10px;font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.12);display:none;z-index:9;white-space:nowrap}}
.note{{color:var(--ink3);font-size:12px}} ul.note{{padding-left:18px}}
.tabs{{display:flex;gap:4px;border-bottom:1px solid var(--line);margin:16px 0 20px}}
.tabs button{{background:none;border:0;border-bottom:2px solid transparent;padding:8px 14px;font:inherit;color:var(--ink2);cursor:pointer}}
.tabs button[aria-selected=true]{{color:var(--ink);border-bottom-color:var(--ink);font-weight:600}}
[hidden]{{display:none!important}}
td.pos{{color:#0a7a2f}} td.neg{{color:#c0392b}} @media (prefers-color-scheme: dark){{td.pos{{color:#4cc46f}} td.neg{{color:#ff7b6b}}}}
tr.sum td{{font-weight:600;border-top:2px solid var(--line)}}
"""


def _signed(v, fmt=",.0f") -> str:
    if v is None:
        return "<td>-</td>"
    cls = "pos" if v > 0 else "neg" if v < 0 else ""
    return f'<td class="{cls}">{v:+{fmt}}</td>'


def _num(v, fmt=",.2f") -> str:
    return f"<td>{v:{fmt}}</td>" if v is not None else "<td>-</td>"


def _holdings_tab(a: Analysis) -> str:
    def stock_table(rows: list[dict]) -> str:
        body = "".join(
            f'<tr><td class="l">{_esc(r["broker"])}</td><td class="l">{_esc(r["account"])}{" ★" if r["nisa"] else ""}</td>'
            f'<td class="l"><i class="sw" style="background:var(--s{_CLASS_SLOT.get(r["cls"], 6)})"></i>{_esc(r["cls"])}</td>'
            f'<td class="l"><b>{_esc(r["symbol"])}</b></td><td class="l">{_esc(r["name"])}</td>'
            f'{_num(r["qty"], ",.0f" if (r["qty"] or 0) == int(r["qty"] or 0) else ",.2f")}'
            f'<td class="l">{_esc(r["currency"])}</td>{_num(r["price"])}{_num(r["avg_cost"])}'
            f'{_num(r["cost_jpy"], ",.0f")}<td>{_yen(r["mv"])}</td>{_signed(r["pnl"])}{_signed(r["pct"], ".1f")}'
            f'<td>{_pct(r["share"])}</td><td>{"○" if r["stop"] else ""}</td><td class="l">{r["date"]}</td></tr>'
            for r in rows)
        mv = sum(r["mv"] for r in rows)
        cost = sum(r["cost_jpy"] or 0 for r in rows)
        pnl = sum(r["pnl"] or 0 for r in rows)
        total = (f'<tr class="sum"><td class="l" colspan="9">合計 {len(rows)} 銘柄</td><td>{_yen(cost)}</td><td>{_yen(mv)}</td>'
                 f'{_signed(pnl)}{_signed(pnl / cost * 100 if cost else None, ".1f")}<td>{_pct(mv / (a.total or 1) * 100)}</td><td></td><td></td></tr>')
        return ("<table><tr><th>証券</th><th>口座</th><th>区分</th><th>銘柄</th><th>名称</th><th>数量</th><th>通貨</th>"
                "<th>現在値</th><th>取得単価</th><th>取得額(円)</th><th>評価額(円)</th><th>損益(円)</th><th>損益%</th>"
                f"<th>全体比</th><th>逆指値</th><th>日付</th></tr>{body}{total}</table>")

    def fund_table(rows: list[dict]) -> str:
        body = "".join(
            f'<tr><td class="l">{_esc(r["broker"])}</td><td class="l">{_esc(r["account"])}{" ★" if r["nisa"] else ""}</td>'
            f'<td class="l">{_esc(r["name"])}</td>{_num(r["units"], ",.0f")}{_num(r["nav"], ",.0f")}{_num(r["avg_cost"], ",.0f")}'
            f'{_num(r["cost_jpy"], ",.0f")}<td>{_yen(r["mv"])}</td>{_signed(r["pnl"])}{_signed(r["pct"], ".1f")}'
            f'<td>{_pct(r["share"])}</td><td class="l">{r["date"]}</td></tr>' for r in rows)
        mv = sum(r["mv"] for r in rows)
        cost = sum(r["cost_jpy"] or 0 for r in rows)
        pnl = sum(r["pnl"] or 0 for r in rows)
        total = (f'<tr class="sum"><td class="l" colspan="6">合計 {len(rows)} 本</td><td>{_yen(cost)}</td><td>{_yen(mv)}</td>'
                 f'{_signed(pnl)}{_signed(pnl / cost * 100 if cost else None, ".1f")}<td>{_pct(mv / (a.total or 1) * 100)}</td><td></td></tr>')
        return ("<table><tr><th>証券</th><th>口座</th><th>ファンド名</th><th>口数</th><th>基準価額</th><th>取得単価</th>"
                f"<th>取得額(円)</th><th>評価額(円)</th><th>損益(円)</th><th>損益%</th><th>全体比</th><th>日付</th></tr>{body}{total}</table>")

    cash = "".join(f'<tr><td class="l">{_esc(c["who"])}</td><td class="l">{_esc(c["label"])}</td><td>{_yen(c["mv"])}</td>'
                   f'<td>{_pct(c["mv"] / (a.total or 1) * 100)}</td></tr>' for c in a.cash_items)
    manual = "".join(f'<tr><td class="l">{_esc(r["name"])}</td><td class="l">{_esc(r["cls"])}</td><td class="l">{_esc(r["currency"])}</td>'
                     f'<td>{_yen(r["mv"])}</td><td>{_pct(r["share"])}</td><td class="l">{r["date"]}</td><td class="l">{_esc(r["note"] or "")}</td></tr>'
                     for r in a.manual_rows)
    return (f'<h2 style="margin-top:0">株式・ETF（{len(a.holdings_rows)} 件、評価額順）</h2><div class="card">{stock_table(a.holdings_rows)}</div>'
            f'<h2>投資信託（{len(a.funds_rows)} 件）</h2><div class="card">{fund_table(a.funds_rows)}</div>'
            f'<h2>現金同等物</h2><div class="card"><table><tr><th>口座</th><th>項目</th><th>評価額(円)</th><th>全体比</th></tr>{cash}</table></div>'
            f'<h2>手入力資産</h2><div class="card"><table><tr><th>名前</th><th>資産クラス</th><th>通貨</th><th>金額(円)</th><th>全体比</th><th>日付</th><th>メモ</th></tr>{manual}</table></div>'
            '<p class="note">★ = NISA 口座。逆指値 ○ = 売り逆指値注文あり。損益は円換算、投信の基準価額・取得単価は 1万口あたり。</p>')


def _donut(a: Analysis) -> str:
    items = [(c, a.allocation[c]) for c in ASSET_CLASSES if a.allocation.get(c)]
    total = sum(v for _, v in items) or 1
    cx, cy, r, w = 150, 150, 120, 34
    paths, labels, ang = [], [], -math.pi / 2
    for c, v in items:
        frac = v / total
        a0, a1 = ang, ang + frac * 2 * math.pi
        gap = 0.012  # 2px 相当の隙間
        s0, s1 = a0 + gap / 2, a1 - gap / 2
        if s1 <= s0:
            s1 = s0 + 0.001
        large = 1 if (s1 - s0) > math.pi else 0
        x0, y0 = cx + r * math.cos(s0), cy + r * math.sin(s0)
        x1, y1 = cx + r * math.cos(s1), cy + r * math.sin(s1)
        ri = r - w
        xi0, yi0 = cx + ri * math.cos(s1), cy + ri * math.sin(s1)
        xi1, yi1 = cx + ri * math.cos(s0), cy + ri * math.sin(s0)
        d = f"M{x0:.1f},{y0:.1f} A{r},{r} 0 {large} 1 {x1:.1f},{y1:.1f} L{xi0:.1f},{yi0:.1f} A{ri},{ri} 0 {large} 0 {xi1:.1f},{yi1:.1f} Z"
        slot = _CLASS_SLOT[c]
        paths.append(f'<path d="{d}" fill="var(--s{slot})" data-tip="{_esc(c)}: {_yen(v)}円 ({_pct(frac * 100)})"/>')
        if frac >= 0.06:
            am = (s0 + s1) / 2
            lx, ly = cx + (r - w / 2) * math.cos(am), cy + (r - w / 2) * math.sin(am)
            labels.append(f'<text x="{lx:.1f}" y="{ly + 4:.1f}" text-anchor="middle" style="fill:#fff;font-size:11px;font-weight:600">{_pct(frac * 100, 0)}</text>')
        ang = a1
    legend = "".join(
        f'<span><i class="sw" style="background:var(--s{_CLASS_SLOT[c]})"></i>{_esc(c)} {_man(v)} ({_pct(v / total * 100)})</span>'
        for c, v in items)
    return (f'<svg viewBox="0 0 300 300" width="300" height="300" role="img" aria-label="資産配分">{"".join(paths)}{"".join(labels)}'
            f'<text x="{cx}" y="{cy - 4}" text-anchor="middle" class="lab">総資産</text>'
            f'<text x="{cx}" y="{cy + 14}" text-anchor="middle" class="lab">{_man(total)}</text></svg>'
            f'<div class="legend">{legend}</div>')


def _history(a: Analysis) -> str:
    hist = a.history
    classes = [c for c in ASSET_CLASSES if any(s.by_class.get(c) for s in hist)]
    W, H, L, R, T, B = 720, 300, 70, 16, 16, 40
    pw, ph = W - L - R, H - T - B
    n = len(hist)
    ymax = max(s.total for s in hist) or 1
    step = 10 ** math.floor(math.log10(ymax))
    for m in (1, 2, 2.5, 5, 10):
        if ymax / (step * m) <= 5:
            step *= m
            break
    ymax = math.ceil(ymax / step) * step
    xs = [L + (pw * i / (n - 1) if n > 1 else pw / 2) for i in range(n)]
    ys = lambda v: T + ph - v / ymax * ph  # noqa: E731

    grid = "".join(
        f'<line x1="{L}" x2="{L + pw}" y1="{ys(v):.1f}" y2="{ys(v):.1f}" stroke="var(--grid)"/>'
        f'<text x="{L - 6}" y="{ys(v) + 4:.1f}" text-anchor="end">{v / 10000:,.0f}万</text>'
        for v in [step * k for k in range(int(ymax / step) + 1)])
    areas = []
    base = [0.0] * n
    for c in classes:
        top = [base[i] + hist[i].by_class.get(c, 0) for i in range(n)]
        pts_top = " ".join(f"{xs[i]:.1f},{ys(top[i]):.1f}" for i in range(n))
        pts_base = " ".join(f"{xs[i]:.1f},{ys(base[i]):.1f}" for i in reversed(range(n)))
        slot = _CLASS_SLOT[c]
        areas.append(f'<polygon points="{pts_top} {pts_base}" fill="var(--s{slot})" fill-opacity=".75" stroke="var(--bg)" stroke-width="2"/>')
        base = top
    total_line = " ".join(f"{xs[i]:.1f},{ys(hist[i].total):.1f}" for i in range(n))
    markers = "".join(f'<circle cx="{xs[i]:.1f}" cy="{ys(hist[i].total):.1f}" r="4" fill="var(--ink)" stroke="var(--bg)" stroke-width="2"/>' for i in range(n))
    labels_x = "".join(f'<text x="{xs[i]:.1f}" y="{H - B + 16}" text-anchor="middle">{hist[i].date[5:]}</text>'
                       for i in range(n) if n <= 12 or i % max(1, n // 10) == 0 or i == n - 1)
    # ホバー用の縦帯（各日付に1本）
    hits = []
    for i in range(n):
        x0 = (xs[i - 1] + xs[i]) / 2 if i > 0 else L
        x1 = (xs[i] + xs[i + 1]) / 2 if i < n - 1 else L + pw
        tip = f"{hist[i].date}  合計 {_yen(hist[i].total)}円" + "".join(
            f"\\n{c}: {_yen(hist[i].by_class.get(c, 0))}円" for c in classes if hist[i].by_class.get(c))
        hits.append(f'<rect x="{x0:.1f}" y="{T}" width="{x1 - x0:.1f}" height="{ph}" fill="transparent" data-tip="{_esc(tip)}" data-x="{xs[i]:.1f}"/>')
    legend = "".join(f'<span><i class="sw" style="background:var(--s{_CLASS_SLOT[c]})"></i>{_esc(c)}</span>' for c in classes) \
        + '<span><i class="sw" style="background:var(--ink)"></i>合計</span>'
    table = "<table><tr><th>日付</th>" + "".join(f"<th>{_esc(c)}</th>" for c in classes) + "<th>合計</th></tr>" + "".join(
        f"<tr><td>{s.date}</td>" + "".join(f"<td>{_yen(s.by_class.get(c, 0))}</td>" for c in classes) + f"<td><b>{_yen(s.total)}</b></td></tr>"
        for s in hist) + "</table>"
    return (f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:{W}px" role="img" aria-label="資産推移">'
            f'{grid}<line x1="{L}" x2="{L + pw}" y1="{T + ph}" y2="{T + ph}" stroke="var(--line)"/>'
            f'{"".join(areas)}<polyline points="{total_line}" fill="none" stroke="var(--ink)" stroke-width="2"/>{markers}'
            f'<line id="xh" x1="0" x2="0" y1="{T}" y2="{T + ph}" stroke="var(--ink3)" stroke-dasharray="3 3" style="display:none"/>'
            f'{labels_x}{"".join(hits)}</svg><div class="legend">{legend}</div>'
            f'<details style="margin-top:8px"><summary class="note">表で見る</summary>{table}</details>')


def render(a: Analysis) -> str:
    alloc_total = a.total or 1
    us_equity_like = a.allocation.get("米国株式", 0) + a.allocation.get("投資信託", 0)
    cov = a.stop_covered_value / a.equity_value * 100 if a.equity_value else 0
    tiles = [
        ("総資産", _man(a.total), f"{_yen(a.total)}円 / {a.as_of} 時点"),
        ("含み益（証券口座）", _man(a.unrealized_pnl), "株式 + 投信 + MMF"),
        ("NISA 残高", _man(a.nisa_value), _pct(a.nisa_value / alloc_total * 100) + " / 非課税"),
        ("特定口座 含み益", _man(a.taxable_pnl), f"売却時の税金 約 {_man(a.taxable_pnl * 0.20315)}"),
        ("米国株式 + 米国指数投信", _pct(us_equity_like / alloc_total * 100), _man(us_equity_like)),
        ("現金同等物", _pct(a.allocation.get("現金同等物", 0) / alloc_total * 100), _man(a.allocation.get("現金同等物", 0))),
        ("逆指値カバー率", _pct(cov), f"株式 {_man(a.equity_value)} のうち {_man(a.stop_covered_value)}"),
    ]
    tiles_html = "".join(f'<div class="tile"><div class="k">{_esc(k)}</div><div class="v">{_esc(v)}</div><div class="d">{_esc(d)}</div></div>' for k, v, d in tiles)

    cur_total = sum(a.currency.values()) or 1
    cur_rows = "".join(f"<tr><td>{_esc(k)}</td><td>{_yen(v)}</td><td>{_pct(v / cur_total * 100)}</td></tr>" for k, v in a.currency.items())
    top_rows = "".join(
        f'<tr><td class="l"><i class="sw" style="background:var(--s{_CLASS_SLOT.get(p["cls"], 6)})"></i>{_esc(p["symbol"])}</td>'
        f'<td class="l">{_esc(p["name"])}</td><td>{_yen(p["mv"])}</td><td>{_pct(p["pct"])}</td></tr>' for p in a.top_positions)
    cash_rows = "".join(f'<tr><td class="l">{_esc(c["who"])}</td><td class="l">{_esc(c["label"])}</td><td>{_yen(c["mv"])}</td></tr>' for c in a.cash_items)
    alloc_rows = "".join(f'<tr><td class="l"><i class="sw" style="background:var(--s{_CLASS_SLOT[c]})"></i>{_esc(c)}</td><td>{_yen(v)}</td><td>{_pct(v / alloc_total * 100)}</td></tr>'
                         for c, v in a.allocation.items())

    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Portfolio Report {a.as_of}</title><style>{_css()}</style></head><body><main>
<h1>ポートフォリオ分析</h1><p class="sub">{a.as_of} 時点のスナップショット（生成: {datetime.now():%Y-%m-%d %H:%M}）。手入力資産・暗号資産は最新の登録値を引き継ぎ。</p>
<div class="tabs" role="tablist"><button role="tab" aria-selected="true" data-tab="analysis">分析</button><button role="tab" aria-selected="false" data-tab="holdings">保有一覧</button></div>
<section id="tab-holdings" hidden>{_holdings_tab(a)}</section>
<section id="tab-analysis">
<div class="tiles">{tiles_html}</div>
<div class="row" style="margin-top:20px">
  <div class="card"><h3>資産配分</h3><div style="display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start">{_donut(a)}</div>
    <details style="margin-top:8px"><summary class="note">表で見る</summary><table><tr><th>資産クラス</th><th>評価額(円)</th><th>比率</th></tr>{alloc_rows}</table></details></div>
  <div class="card"><h3>通貨エクスポージャ</h3><table><tr><th>通貨</th><th>評価額(円)</th><th>比率</th></tr>{cur_rows}</table>
    <p class="note">目安: 円高 10% で約 −{_man(a.currency.get("USD", 0) * 0.1)}、米国株 20% 下落で約 −{_man(us_equity_like * 0.2)}。</p>
    <h3 style="margin-top:16px">現金同等物の内訳</h3><table><tr><th>口座</th><th>項目</th><th>評価額(円)</th></tr>{cash_rows}</table></div>
</div>
<h2>資産推移</h2><div class="card">{_history(a)}<p class="note">各日付時点で、証券会社・テーブルごとの最新スナップショットを合算（取込していない日は前回値を引き継ぐ）。</p></div>
<h2>上位ポジション（証券会社・口座横断）</h2><div class="card"><table><tr><th>銘柄</th><th>名称</th><th>評価額(円)</th><th>全体比</th></tr>{top_rows}</table></div>
<ul class="note"><li>本レポートは保有状況の事実整理であり、投資助言ではありません。</li><li>資産クラスの上書きは <code>portfolio classify</code>、手入力資産は <code>portfolio manual</code> で管理。</li></ul>
</section>
</main><div class="tip" id="tip"></div>
<script>
document.querySelectorAll('.tabs button').forEach(b=>b.addEventListener('click',()=>{{
  document.querySelectorAll('.tabs button').forEach(x=>x.setAttribute('aria-selected',x===b));
  document.querySelectorAll('main > section').forEach(s=>s.hidden=(s.id!=='tab-'+b.dataset.tab));
  history.replaceState(null,'','#'+b.dataset.tab);
}}));
if(location.hash==='#holdings')document.querySelector('[data-tab=holdings]').click();
const tip=document.getElementById('tip'),xh=document.getElementById('xh');
document.querySelectorAll('[data-tip]').forEach(el=>{{
  el.addEventListener('mousemove',e=>{{tip.style.display='block';tip.textContent='';el.dataset.tip.split('\\\\n').forEach((l,i)=>{{if(i)tip.appendChild(document.createElement('br'));tip.appendChild(document.createTextNode(l));}});
    tip.style.left=(e.clientX+14)+'px';tip.style.top=(e.clientY+14)+'px';
    if(el.dataset.x&&xh){{xh.setAttribute('x1',el.dataset.x);xh.setAttribute('x2',el.dataset.x);xh.style.display='block';}}}});
  el.addEventListener('mouseleave',()=>{{tip.style.display='none';if(xh)xh.style.display='none';}});
}});
</script></body></html>"""
