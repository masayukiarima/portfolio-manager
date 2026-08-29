"""楽天証券「口座管理 > 保有商品一覧 > すべて」の保存HTML (EUC-JP) を解析する。

明細は <div id="table_possess_data"> 配下の table.tbl-bold-border。1行の td は
  種別 | コード | 銘柄名 | 口座 | 保有数量 | 平均取得価額 | 現在値(+前日比) | 時価評価額/評価損益 (div.MktValYen 等)
"""
from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup, Tag

from portfolio.models import Holding, ParseResult
from portfolio.parsers._num import currency_of, to_float

_TIME_RE = re.compile(r"(\d{2})/(\d{2}) \d{2}:\d{2}")
_YEAR_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")


def matches(html: str) -> bool:
    return "楽天証券" in html and ("table_possess_data" in html or "balance-tbl" in html)


def parse(html: str, year_hint: int | None = None) -> ParseResult:
    soup = BeautifulSoup(html, "lxml")
    snapshot_date = _snapshot_date(soup, year_hint)
    warnings: list[str] = []
    holdings: list[Holding] = []

    container = soup.find(id="table_possess_data") or soup
    rows = 0
    for table in container.find_all("table", class_="tbl-bold-border"):
        for tr in table.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 8:
                continue
            rows += 1
            try:
                h = _parse_row(tds)
            except Exception as e:  # noqa: BLE001
                warnings.append(f"楽天: 解析失敗 {[t.get_text(strip=True) for t in tds[:3]]} ({e})")
                continue
            h.snapshot_date = snapshot_date or date.today()
            holdings.append(h)

    if rows == 0:
        warnings.append("楽天: 明細行が1件も見つかりませんでした")
    return ParseResult("rakuten", snapshot_date, holdings, warnings)


def _snapshot_date(soup: BeautifulSoup, year_hint: int | None) -> date | None:
    text = soup.get_text(" ")
    m = _YEAR_RE.search(text)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _TIME_RE.search(text)
    if not m or year_hint is None:
        return None  # 年が判らないので呼び出し側で補完させる
    return date(year_hint, int(m.group(1)), int(m.group(2)))


def _cell_text(td: Tag) -> str:
    return td.get_text(" ", strip=True)


def _sub(td: Tag, cls: str) -> str | None:
    el = td.find(class_=cls)
    return el.get_text(" ", strip=True) if el else None


def _parse_row(tds: list[Tag]) -> Holding:
    kind, code, name, account = (_cell_text(t) for t in tds[:4])
    qty_txt, cost_txt, price_txt = (_cell_text(t) for t in tds[4:7])
    last = tds[7]

    currency = currency_of(cost_txt, "JPY")
    is_jpy = currency == "JPY"
    price = to_float(price_txt)
    avg_cost = to_float(cost_txt)
    quantity = to_float(qty_txt)

    mv_jpy = to_float(_sub(last, "MktValYen"))
    if mv_jpy is None:  # クラスが無い場合のフォールバック: 先頭の円額
        mv_jpy = to_float(_cell_text(last))
    mv = mv_jpy if is_jpy else to_float(_sub(last, "MktVal"))
    pnl_jpy = to_float(_sub(last, "AppGainLoss"))
    pct = to_float(_sub(last, "AppGainLossRate"))

    acq = round(avg_cost * quantity, 2) if (avg_cost is not None and quantity is not None) else None
    if is_jpy:
        pnl = pnl_jpy
    else:
        pnl = round(mv - acq, 2) if (mv is not None and acq is not None) else None

    return Holding(
        snapshot_date=date.today(),
        broker="rakuten",
        account_type=account,
        is_nisa="NISA" in account.upper(),
        asset_class=kind,
        symbol=code or name,
        name=name,
        currency=currency,
        quantity=quantity,
        price=price,
        price_jpy=price if is_jpy else None,
        avg_cost=avg_cost,
        avg_cost_jpy=avg_cost if is_jpy else None,
        acquisition_amount=acq,
        acquisition_amount_jpy=acq if is_jpy else None,
        market_value=mv,
        market_value_jpy=mv_jpy,
        unrealized_pnl=pnl,
        unrealized_pnl_jpy=pnl_jpy,
        unrealized_pnl_pct=pct,
        extra={"price_change": price_txt},
    )
