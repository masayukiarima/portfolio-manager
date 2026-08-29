"""SBI証券 新サイト「取引 > 外国株式 > 注文照会」の保存HTMLを解析する。

保有一覧と同じ div ベース構造:
  article.main-content
    ul.responsive-table
      li.table-header   … '国内注文日時', '期間', '銘柄', '取引', '預り', '数量 (未約定数量)', ...
      li.table-row > div.table-item … 1注文
"""
from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup, Tag

from portfolio.models import Order, ParseResult
from portfolio.parsers._num import to_float

_DATE_RE = re.compile(r"日本時間[：:]\s*(\d{4})/(\d{2})/(\d{2})")
_DT_RE = re.compile(r"(\d{4})/(\d{2})/(\d{2})(?:\s+(\d{2}:\d{2}))?")


def matches(html: str) -> bool:
    return "sbisec" in html and "国内注文日時" in html


def parse(html: str) -> ParseResult:
    soup = BeautifulSoup(html, "lxml")
    snapshot_date = _snapshot_date(soup)
    warnings: list[str] = []
    orders: list[Order] = []

    article = soup.select_one("article.main-content")
    if article is None:
        raise ValueError("SBI: article.main-content が見つかりません")

    for li in article.select("li.table-row"):
        items = li.select("div.table-item")
        cells = [c.get_text(" ", strip=True) for c in items]
        if len(cells) < 11:
            continue
        try:
            orders.append(_parse_row(items, cells, snapshot_date or date.today()))
        except Exception as e:  # noqa: BLE001
            warnings.append(f"SBI注文: 解析失敗 {cells[:3]} ({e})")

    if not orders and not warnings:
        warnings.append("SBI注文: 注文行が見つかりませんでした（注文なし、または未対応の画面）")
    return ParseResult("sbi", snapshot_date, warnings=warnings, kind="orders", orders=orders)


def _snapshot_date(soup: BeautifulSoup) -> date | None:
    m = _DATE_RE.search(soup.get_text(" "))
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _norm_dt(text: str) -> str | None:
    m = _DT_RE.search(text or "")
    if not m:
        return None
    d = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return f"{d} {m.group(4)}" if m.group(4) else d


def _parse_row(items: list[Tag], cells: list[str], snap: date) -> Order:
    # cells: ['2026/08/29 21:02', '2026/09/04', '注文中 アルファベット C GOOG NASDAQ', '現買', '特定',
    #         '1 ( 1 )', '300.00', '342.8800', '-', '外貨', '-', '取消 訂正 詳細']
    head = items[2]
    status_el = head.select_one("span.sticker")
    status = status_el.get_text(strip=True) if status_el else ""
    ps = [p.get_text(" ", strip=True) for p in head.select("p")]
    name = ps[0] if ps else ""
    code_parts = ps[1].split(None, 1) if len(ps) > 1 else [""]
    symbol = code_parts[0]
    market = code_parts[1] if len(code_parts) > 1 else None

    side_txt = cells[3]
    side = "売" if "売" in side_txt else "買"
    account = cells[4] or "-"

    qty_labels = [l.get_text(strip=True) for l in items[5].select("label")]
    quantity = to_float(qty_labels[0]) if qty_labels else to_float(cells[5])
    unfilled = to_float(qty_labels[1]) if len(qty_labels) > 1 else None
    filled = (quantity - unfilled) if (quantity is not None and unfilled is not None) else None

    price_txt = cells[6]
    condition = cells[10] if cells[10] not in ("", "-") else None
    if "成行" in price_txt:
        order_type = "成行"
        limit_price = None
    else:
        order_type = "指値"
        limit_price = to_float(price_txt)
    trigger_price = None
    if condition and "逆指値" in condition:
        order_type = f"逆指値/{order_type}"
        # 例: '逆指値/成行:現在値240.00 USD以下で、成行で発注'
        tm = re.search(r"現在値\s*([\d,]+(?:\.\d+)?)", condition)
        trigger_price = to_float(tm.group(1)) if tm else None

    ordered_at = _norm_dt(cells[0])
    expires_on = _norm_dt(cells[1])
    settlement = f"{cells[9]}決済" if cells[9] and cells[9] != "-" else None

    key = "|".join([ordered_at or "", symbol, side, str(quantity or ""), price_txt])
    return Order(
        snapshot_date=snap,
        broker="sbi",
        order_key=key,
        order_no=None,
        ordered_at=ordered_at,
        status=status,
        symbol=symbol,
        name=name,
        side=side,
        account_type=account,
        is_nisa="NISA" in account.upper(),
        market=market,
        quantity=quantity,
        filled_quantity=filled,
        order_type=order_type,
        limit_price=limit_price,
        trigger_price=trigger_price,
        current_price=to_float(cells[7]),
        avg_fill_price=to_float(cells[8]),
        expires_on=expires_on,
        settlement=settlement,
        condition=condition,
    )
