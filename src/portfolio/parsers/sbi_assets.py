"""SBI証券 新サイト「My資産 > 資産残高」の保存HTMLを解析する。

「詳細を表示する」配下の商品別テーブルが li.table-row（div.table-item ×6）:
  [0] 商品名  [1] (空)  [2] 評価額  [3] '評価損益 評価損益率'  [4] '前日比 率'  [5] '前月比 率'
行: 国内株式(現物) / 米国株式 / 投資信託 / 外貨建MMF / 預り金(米ドル) / スィープ専用銀行口座 / 合計
日時は '2026/8/30 01:29' の形式で本文に出る。
"""
from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup

from portfolio.models import Balance, ParseResult
from portfolio.parsers._num import all_floats, to_float

_DT_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2}) \d{2}:\d{2}")

# 画面表記 → (正規化区分, 現金同等物か)
CATEGORY_MAP = {
    "国内株式(現物)": ("国内株式", False),
    "国内株式": ("国内株式", False),
    "米国株式": ("米国株式", False),
    "外国株式": ("米国株式", False),
    "投資信託": ("投資信託", False),
    "外貨建MMF": ("外貨建MMF", True),
    "預り金": ("預り金(JPY)", True),
    "預り金(円)": ("預り金(JPY)", True),
    "預り金(米ドル)": ("預り金(USD)", True),
    "スィープ専用銀行口座": ("銀行口座", True),
    "スイープ専用銀行口座": ("銀行口座", True),
    "円貨建債券": ("国内債券", False),
    "外貨建債券": ("外国債券", False),
    "合計": ("合計", False),
}


def matches(html: str) -> bool:
    return "sbisec" in html and "My資産" in html and "資産構成比率" in html


def parse(html: str) -> ParseResult:
    soup = BeautifulSoup(html, "lxml")
    snapshot_date = _snapshot_date(soup)
    snap = snapshot_date or date.today()
    warnings: list[str] = []
    balances: list[Balance] = []

    for li in soup.select("li.table-row"):
        cells = [c.get_text(" ", strip=True) for c in li.select("div.table-item")]
        if len(cells) < 6 or not cells[0]:
            continue
        label = cells[0]
        cat, is_cash = CATEGORY_MAP.get(label, (label, False))
        pnl = all_floats(cells[3])
        day = all_floats(cells[4])
        month = all_floats(cells[5])
        balances.append(Balance(
            snapshot_date=snap,
            broker="sbi",
            category=cat,
            label=label,
            market_value_jpy=to_float(cells[2]),
            unrealized_pnl_jpy=pnl[0] if pnl else None,
            unrealized_pnl_pct=pnl[1] if len(pnl) > 1 else None,
            day_change_jpy=day[0] if day else None,
            day_change_pct=day[1] if len(day) > 1 else None,
            month_change_jpy=month[0] if month else None,
            month_change_pct=month[1] if len(month) > 1 else None,
            is_cash=is_cash,
            is_total=(cat == "合計"),
        ))

    if not balances:
        warnings.append("SBI My資産: 商品別の行が見つかりませんでした（「詳細を表示する」を開いて保存してください）")
    return ParseResult("sbi", snapshot_date, warnings=warnings, kind="balances", balances=balances)


def _snapshot_date(soup: BeautifulSoup) -> date | None:
    m = _DT_RE.search(soup.get_text(" "))
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
