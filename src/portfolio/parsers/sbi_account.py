"""SBI証券 旧サイト「口座管理 > 口座（円建） > 保有証券一覧」の保存HTMLを解析する。

国内株式・ETF と投資信託が1ページに載る（米国株式は別ページ）。テーブル構造:
  <b>株式（特定預り）</b> / <b>株式（NISA預り（成長投資枠））</b>
    <table> ヘッダ行: 銘柄 | 保有株数 (売却注文中) | 取得単価 現在値 | 取得金額 評価額 | 評価損益 | 取引
            明細行:  td.mbody '銘柄名 コード' | '5' | '53,610 68,530' | '268,050 342,650' | '+74,600'
  <b>投資信託</b><b>（金額/特定預り）</b> / <b>（金額/NISA預り（つみたて投資枠））</b> / <b>（金額/旧つみたてNISA預り）</b>
    <table> ヘッダ行: ファンド名 | 保有口数 (売却注文中) | 取得単価 基準価額 | 取得金額 評価額 | 評価損益 | ...
            明細行:  td.mbody 'ファンド名' | '31,129口' | '64,249 100,206' | '200,000 311,931' | '+111,931'
ページに日付表示は無い（呼び出し側がファイル更新日時で補完）。
"""
from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup, Tag

from portfolio.models import Fund, Holding, ParseResult
from portfolio.parsers._num import all_floats, to_float

_CODE_RE = re.compile(r"^(?P<name>.+?)\s+(?P<code>[0-9A-Z]{4,5})$")


def matches(html: str) -> bool:
    return "sbisec" in html and "保有証券一覧" in html and "mtext-db" in html


def parse(html: str) -> ParseResult:
    soup = BeautifulSoup(html, "lxml")
    warnings: list[str] = []
    holdings: list[Holding] = []
    funds: list[Fund] = []
    snap = date.today()

    for table in soup.find_all("table"):
        trs = table.find_all("tr", recursive=False) or table.find_all("tr")
        if not trs:
            continue
        head = [c.get_text(" ", strip=True) for c in trs[0].find_all("td", recursive=False)]
        if not head:
            continue
        kind = "stock" if head[0] == "銘柄" else "fund" if head[0] == "ファンド名" else None
        if kind is None:
            continue
        account = _account_of(table)
        for tr in trs[1:]:
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 5 or "mbody" not in (tds[0].get("class") or []):
                continue
            cells = [c.get_text(" ", strip=True) for c in tds]
            try:
                if kind == "stock":
                    holdings.append(_parse_stock(cells, account, snap))
                else:
                    funds.append(_parse_fund(cells, account, snap))
            except Exception as e:  # noqa: BLE001
                warnings.append(f"SBI保有証券: 解析失敗 {cells[:2]} ({e})")

    if not holdings and not funds:
        warnings.append("SBI保有証券: 明細行が見つかりませんでした")
    return ParseResult("sbi", None, holdings=holdings, warnings=warnings, kind="holdings", funds=funds)


def _account_of(table: Tag) -> str:
    """テーブル直前の <b> テキスト（'株式（特定預り）' / '（金額/NISA預り（つみたて投資枠））' 等）から預り区分。"""
    b = table.find_previous(string=re.compile("預り"))
    text = re.sub(r"\s+", "", b) if b else ""
    if "旧つみたてNISA" in text:
        return "旧つみたてNISA"
    if "つみたて投資枠" in text:
        return "NISAつみたて"
    if "成長投資枠" in text:
        return "NISA成長"
    if "NISA" in text:
        return "NISA"
    if "一般預り" in text:
        return "一般"
    return "特定"


def _parse_stock(cells: list[str], account: str, snap: date) -> Holding:
    m = _CODE_RE.match(cells[0])
    name, code = (m.group("name"), m.group("code")) if m else (cells[0], cells[0])
    qty = all_floats(cells[1])
    cost, price = (all_floats(cells[2]) + [None, None])[:2]
    acq, mv = (all_floats(cells[3]) + [None, None])[:2]
    pnl = to_float(cells[4])
    return Holding(
        snapshot_date=snap,
        broker="sbi",
        account_type=account,
        is_nisa="NISA" in account.upper(),
        asset_class="国内株式",
        symbol=code,
        name=name,
        market="東証",
        currency="JPY",
        quantity=qty[0] if qty else None,
        price=price, price_jpy=price,
        avg_cost=cost, avg_cost_jpy=cost,
        acquisition_amount=acq, acquisition_amount_jpy=acq,
        market_value=mv, market_value_jpy=mv,
        unrealized_pnl=pnl, unrealized_pnl_jpy=pnl,
        unrealized_pnl_pct=round(pnl / acq * 100, 2) if (pnl is not None and acq) else None,
        extra={"selling_quantity": qty[1] if len(qty) > 1 else None},
    )


def _parse_fund(cells: list[str], account: str, snap: date) -> Fund:
    units = all_floats(cells[1])
    cost, nav = (all_floats(cells[2]) + [None, None])[:2]
    acq, mv = (all_floats(cells[3]) + [None, None])[:2]
    pnl = to_float(cells[4])
    return Fund(
        snapshot_date=snap,
        broker="sbi",
        account_type=account,
        is_nisa="NISA" in account.upper(),
        name=cells[0],
        units=units[0] if units else None,
        selling_units=units[1] if len(units) > 1 else None,
        nav=nav,
        avg_cost=cost,
        market_value_jpy=mv,
        acquisition_amount_jpy=acq,
        unrealized_pnl_jpy=pnl,
        unrealized_pnl_pct=round(pnl / acq * 100, 2) if (pnl is not None and acq) else None,
    )
