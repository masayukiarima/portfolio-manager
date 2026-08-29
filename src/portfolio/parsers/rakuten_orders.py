"""楽天証券「米国株式取引 注文照会・訂正・取消」の保存HTML (EUC-JP) を解析する。

table.pcmm-foreign-stock-tbl--inquiry の tr が1注文。td 内は ul > li に項目が分かれている:
  td0: 注文番号 / 注文日時 / 逆指値執行日時 / 決済方法
  td1: 状況 / 状況（逆指値注文）
  td2: 'TICKER / 銘柄名 米国市場'
  td3: '現物 買付 ・特定' / 執行条件 / 期限 / 時間外取引 / 注文区分
  td4: 信用区分
  td5: 注文数量 / 約定数量 / 注文単価
  td6: 約定日 等
td が1つだけの tr は直前の注文の補足行（逆指値条件、IFD など）。
"""
from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup, Tag

from portfolio.models import Order, ParseResult
from portfolio.parsers._num import to_float

_TIME_RE = re.compile(r"(\d{2})/(\d{2}) (\d{2}:\d{2})")
_YMD_RE = re.compile(r"(\d{4})/(\d{2})/(\d{2})")
_ORDER_NO_RE = re.compile(r"^\s*(\S+)(?:\s*\((\S+)\))?", re.S)


def matches(html: str) -> bool:
    return "楽天証券" in html and "pcmm-foreign-stock-tbl--inquiry" in html


def parse(html: str, year_hint: int | None = None) -> ParseResult:
    soup = BeautifulSoup(html, "lxml")
    warnings: list[str] = []
    orders: list[Order] = []
    snapshot_date = _snapshot_date(soup, year_hint)
    snap = snapshot_date or date.today()

    table = soup.select_one("table.pcmm-foreign-stock-tbl--inquiry")
    if table is None:
        warnings.append("楽天注文: 注文テーブルが見つかりません")
        return ParseResult("rakuten", snapshot_date, warnings=warnings, kind="orders")

    for tr in table.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) >= 7:
            try:
                orders.append(_parse_row(tds, snap))
            except Exception as e:  # noqa: BLE001
                warnings.append(f"楽天注文: 解析失敗 {[t.get_text(' ', strip=True)[:20] for t in tds[:3]]} ({e})")
        elif len(tds) == 1 and orders:
            note = re.sub(r"\s+", " ", tds[0].get_text(" ", strip=True))
            if note:
                o = orders[-1]
                o.condition = f"{o.condition} / {note}" if o.condition else note
                _apply_condition(o, note)

    if not orders and not warnings:
        warnings.append("楽天注文: 注文行が見つかりませんでした（注文なし）")
    return ParseResult("rakuten", snapshot_date, warnings=warnings, kind="orders", orders=orders)


def _snapshot_date(soup: BeautifulSoup, year_hint: int | None) -> date | None:
    m = _TIME_RE.search(soup.get_text(" "))
    if not m or year_hint is None:
        return None
    return date(year_hint, int(m.group(1)), int(m.group(2)))


def _lis(td: Tag) -> list[str]:
    lis = [re.sub(r"\s+", " ", li.get_text(" ", strip=True)) for li in td.select("li")]
    return lis or [re.sub(r"\s+", " ", td.get_text(" ", strip=True))]


def _parse_row(tds: list[Tag], snap: date) -> Order:
    c0, c1, c3, c5 = _lis(tds[0]), _lis(tds[1]), _lis(tds[3]), _lis(tds[5])

    m = _ORDER_NO_RE.match(c0[0])
    order_no = m.group(1) if m else c0[0]
    linked = m.group(2) if m else None
    ordered_at = _ordered_at(c0[1] if len(c0) > 1 else "", snap)
    settlement = c0[3] if len(c0) > 3 and c0[3] != "-" else None

    status = next((s for s in c1 if s and s != "-"), "")

    head = re.sub(r"\s+", " ", tds[2].get_text(" ", strip=True))
    market = None
    if head.endswith("米国市場"):
        head, market = head[: -len("米国市場")].strip(), "米国市場"
    symbol, _, name = (x.strip() for x in head.partition("/"))
    if not name:
        symbol, name = head, head

    trade = c3[0] if c3 else ""
    side = "売" if "売" in trade else "買"
    acc_m = re.search(r"・(\S+)$", trade)
    account = acc_m.group(1) if acc_m else "-"
    expires_on = None
    for s in c3[1:]:
        ym = _YMD_RE.search(s)
        if ym and "まで" in s:
            expires_on = f"{ym.group(1)}-{ym.group(2)}-{ym.group(3)}"
    order_kind = c3[-1] if len(c3) > 1 else ""

    quantity = to_float(c5[0]) if c5 else None
    filled = to_float(c5[1]) if len(c5) > 1 else None
    price_txt = c5[2] if len(c5) > 2 else "-"
    if "成行" in price_txt:
        order_type, limit_price = "成行", None
    elif price_txt == "-":
        order_type, limit_price = None, None
    else:
        order_type, limit_price = "指値", to_float(price_txt)
    if "逆指値" in order_kind:
        order_type = f"逆指値/{order_type}" if order_type else "逆指値"

    return Order(
        snapshot_date=snap,
        broker="rakuten",
        order_key=order_no,
        order_no=order_no,
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
        expires_on=expires_on,
        settlement=settlement,
        linked_order_no=linked,
    )


def _apply_condition(o: Order, note: str) -> None:
    """補足行 '逆指値条件：市場価格が156.00ドル以下なら成行で執行(2026/11/18)' から
    トリガー価格と（未設定なら）期限を補完する。"""
    if "逆指値条件" not in note:
        return
    tm = re.search(r"市場価格が\s*([\d,]+(?:\.\d+)?)\s*ドル", note)
    if tm and o.trigger_price is None:
        o.trigger_price = to_float(tm.group(1))
    ym = _YMD_RE.search(note)
    if ym and not o.expires_on:
        o.expires_on = f"{ym.group(1)}-{ym.group(2)}-{ym.group(3)}"


def _ordered_at(text: str, snap: date) -> str | None:
    """'08/29 22:40' → 'YYYY-08-29 22:40'。年はスナップショット日から補完（未来なら前年）。"""
    m = _TIME_RE.search(text)
    if not m:
        return None
    mo, d, hm = int(m.group(1)), int(m.group(2)), m.group(3)
    year = snap.year
    if (mo, d) > (snap.month, snap.day):
        year -= 1
    return f"{year:04d}-{mo:02d}-{d:02d} {hm}"
