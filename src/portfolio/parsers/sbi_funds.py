"""SBI証券 新サイト「投資信託 > 保有ファンド」の保存HTMLを解析する。

外国株式ページと同じ div ベース構造:
  article.main-content
    p.font-bold.font-sm   … 預り区分見出し「特定預り (2件)」「NISA (つみたて)預り (3件)」「旧つみたてNISA預り (1件)」
    ul.responsive-table
      li.table-row > div.table-item … 1ファンド
        [0] ファンド名 (+ label.stamp '積立設定中')  [1] '31,129口 (0口)'  [2] 基準価額  [3] 取得単価
        [4] 評価額  [5] 取得金額  [6] '+111,931円 (+55.97％)'  [7] 前日比 '+5,252円 (+1.71％)'  [8] 取引
このページには日付表示が無いため snapshot_date は None（呼び出し側がファイル更新日時で補完）。
"""
from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup, Tag

from portfolio.models import Fund, ParseResult
from portfolio.parsers._num import all_floats, to_float

_SECTION_RE = re.compile(r"^(?P<account>.+?)預り\s*\((\d+)件\)")


def matches(html: str) -> bool:
    return "sbisec" in html and "保有ファンド" in html and "ファンド名" in html


def parse(html: str) -> ParseResult:
    soup = BeautifulSoup(html, "lxml")
    warnings: list[str] = []
    funds: list[Fund] = []

    article = soup.select_one("article.main-content")
    if article is None:
        raise ValueError("SBI: article.main-content が見つかりません")

    account = None
    for el in article.descendants:
        name = getattr(el, "name", None)
        if name == "p" and "font-bold" in (el.get("class") or []):
            m = _SECTION_RE.match(el.get_text(" ", strip=True))
            if m:
                account = _normalize_account(m.group("account"))
            continue
        if name == "li" and "table-row" in (el.get("class") or []) and account:
            items = el.select("div.table-item")
            cells = [c.get_text(" ", strip=True) for c in items]
            if len(cells) < 8:
                continue
            try:
                funds.append(_parse_row(items, cells, account))
            except Exception as e:  # noqa: BLE001
                warnings.append(f"SBI投信: 解析失敗 {cells[:2]} ({e})")

    if not funds:
        warnings.append("SBI投信: 明細行が見つかりませんでした")
    return ParseResult("sbi", None, warnings=warnings, kind="funds", funds=funds)


def _normalize_account(text: str) -> str:
    """'特定' / 'NISA (つみたて)' / '旧つみたてNISA' / 'NISA (成長投資枠)' などを正規化。"""
    t = re.sub(r"\s+", "", text)
    t = t.replace("（", "(").replace("）", ")")
    m = re.match(r"^NISA\((.+)\)$", t)
    if m:
        inner = m.group(1)
        if "つみたて" in inner:
            return "NISAつみたて"
        if "成長" in inner:
            return "NISA成長"
        return f"NISA{inner}"
    return t


def _parse_row(items: list[Tag], cells: list[str], account: str) -> Fund:
    link = items[0].find("a")
    name = link.get_text(" ", strip=True) if link else re.sub(r"\s*積立設定中\s*$", "", cells[0])
    is_acc = "積立設定中" in cells[0]

    units_nums = all_floats(cells[1])
    pnl = all_floats(cells[6])
    day = all_floats(cells[7])

    return Fund(
        snapshot_date=date.today(),
        broker="sbi",
        account_type=account,
        is_nisa="NISA" in account.upper(),
        name=name,
        units=units_nums[0] if units_nums else None,
        selling_units=units_nums[1] if len(units_nums) > 1 else None,
        nav=to_float(cells[2]),
        avg_cost=to_float(cells[3]),
        market_value_jpy=to_float(cells[4]),
        acquisition_amount_jpy=to_float(cells[5]),
        unrealized_pnl_jpy=pnl[0] if pnl else None,
        unrealized_pnl_pct=pnl[1] if len(pnl) > 1 else None,
        day_change_jpy=day[0] if day else None,
        day_change_pct=day[1] if len(day) > 1 else None,
        is_accumulating=is_acc,
    )
