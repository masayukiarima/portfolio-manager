"""SBI証券 新サイト「口座管理 > 外国株式 > 保有銘柄」(/account/foreign/summary) の保存HTMLを解析する。

ページは <table> を使わず、
  article.main-content
    p.font-bold.font-md        … セクション見出し「株式(特定)」「株式(NISA)」「外貨建MMF(特定)」「預り金」
    ul.responsive-table
      li.table-row > div.table-item … 1明細
という div ベース構造。ハッシュ付きクラス (css-xxxx) には依存しない。
"""
from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup, Tag

from portfolio.models import Holding, ParseResult
from portfolio.parsers._num import currency_of, to_float

_SECTION_RE = re.compile(r"^(?P<kind>株式|外貨建MMF|預り金)(?:\((?P<account>[^)]+)\))?$")
_DATE_RE = re.compile(r"日本時間[：:]\s*(\d{4})/(\d{2})/(\d{2})")


def matches(html: str) -> bool:
    return "sbisec" in html and "main-content" in html


def parse(html: str) -> ParseResult:
    soup = BeautifulSoup(html, "lxml")
    snapshot_date = _snapshot_date(soup)
    warnings: list[str] = []
    holdings: list[Holding] = []

    article = soup.select_one("article.main-content")
    if article is None:
        raise ValueError("SBI: article.main-content が見つかりません")

    section = None
    for el in article.descendants:
        name = getattr(el, "name", None)
        if name == "p" and {"font-bold", "font-md"} <= set(el.get("class") or []):
            section = _SECTION_RE.match(el.get_text(strip=True))
            continue
        if name == "li" and "table-row" in (el.get("class") or []) and section:
            items = el.select("div.table-item")
            cells = [c.get_text(" ", strip=True) for c in items]
            kind = section.group("kind")
            account = section.group("account") or "-"
            try:
                if kind == "株式":
                    h = _parse_stock(items[0], cells, account)
                elif kind == "外貨建MMF":
                    h = _parse_mmf(cells, account)
                else:
                    h = _parse_cash(cells)
            except Exception as e:  # noqa: BLE001 - 1行の失敗で全体を止めない
                warnings.append(f"SBI {kind}: 解析失敗 {cells[:2]} ({e})")
                continue
            if h is None:
                continue
            h.snapshot_date = snapshot_date or date.today()
            holdings.append(h)

    if not holdings:
        warnings.append("SBI: 明細行が1件も見つかりませんでした")
    return ParseResult("sbi", snapshot_date, holdings, warnings)


def _snapshot_date(soup: BeautifulSoup) -> date | None:
    m = _DATE_RE.search(soup.get_text(" "))
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _parse_stock(head_item: Tag, cells: list[str], account: str) -> Holding | None:
    # cells: ['シスコ システムズ CSCO NASDAQ', '109.93 USD', '17,540 円', '8', '( 0 )',
    #  '116.01 USD', '18,377 円', '928.08 USD', '147,016 円', '879.44 USD', '140,323 円',
    #  '-48.64 USD', '-6,693 円', '現買 現売 積立']
    # head_item: <p class="font-sm"><a>銘柄名</a></p><p class="font-xs"><span>TICKER</span> 市場</p>
    if len(cells) < 13:
        return None
    name, ticker, market = _split_head(head_item)
    currency = currency_of(cells[1], "USD")

    acq = to_float(cells[7])
    pnl = to_float(cells[11])
    pct = round(pnl / acq * 100, 2) if (acq and pnl is not None) else None

    return Holding(
        snapshot_date=date.today(),
        broker="sbi",
        account_type=account,
        is_nisa="NISA" in account.upper(),
        asset_class="米国株式" if currency == "USD" else "外国株式",
        symbol=ticker,
        name=name,
        market=market,
        currency=currency,
        quantity=to_float(cells[3]),
        price=to_float(cells[1]),
        price_jpy=to_float(cells[2]),
        avg_cost=to_float(cells[5]),
        avg_cost_jpy=to_float(cells[6]),
        acquisition_amount=acq,
        acquisition_amount_jpy=to_float(cells[8]),
        market_value=to_float(cells[9]),
        market_value_jpy=to_float(cells[10]),
        unrealized_pnl=pnl,
        unrealized_pnl_jpy=to_float(cells[12]),
        unrealized_pnl_pct=pct,
        extra={"selling_quantity": to_float(cells[4])},
    )


def _split_head(item: Tag) -> tuple[str, str, str | None]:
    """銘柄セルから (銘柄名, ティッカー, 市場) を返す。銘柄名に 'C' 'ADR' 'ETF' 等が含まれても崩れない。"""
    name_el = item.select_one("p.font-sm")
    code_el = item.select_one("p.font-xs")
    if name_el and code_el:
        name = name_el.get_text(" ", strip=True)
        parts = code_el.get_text(" ", strip=True).split(None, 1)
        if parts:
            return name, parts[0], (parts[1] if len(parts) > 1 else None)
    # フォールバック: テキスト末尾を「... TICKER MARKET」とみなす
    tokens = item.get_text(" ", strip=True).split()
    if len(tokens) < 2:
        raise ValueError(f"銘柄セルを解釈できません: {tokens!r}")
    market = tokens[-1]
    if len(tokens) >= 3 and tokens[-2] in ("NYSE", "NASDAQ") and market in ("Arca", "American"):
        market, tokens = f"{tokens[-2]} {market}", tokens[:-1]
    return " ".join(tokens[:-2]), tokens[-2], market


def _parse_mmf(cells: list[str], account: str) -> Holding | None:
    # ['ブラックロック・スーパー・マネー・マーケット・ファンド（米ドル）', '4,201.96', '1 USD',
    #  '4,201.96 USD', '138.74', '670,464 円', '87,486 円', '買付 売却']
    if len(cells) < 7:
        return None
    name = cells[0]
    currency = currency_of(cells[2], "USD")
    fx = to_float(cells[4])
    mv = to_float(cells[3])
    return Holding(
        snapshot_date=date.today(),
        broker="sbi",
        account_type=account,
        is_nisa="NISA" in account.upper(),
        asset_class="外貨建MMF",
        symbol=name,
        name=name,
        currency=currency,
        quantity=to_float(cells[1]),
        price=to_float(cells[2]),
        avg_cost_jpy=fx,  # 取得為替
        acquisition_amount=mv,
        acquisition_amount_jpy=round(mv * fx) if (mv is not None and fx) else None,
        market_value=mv,
        market_value_jpy=to_float(cells[5]),
        unrealized_pnl_jpy=to_float(cells[6]),
    )


def _parse_cash(cells: list[str]) -> Holding | None:
    # ['米ドル', '3,569.58 USD', '569,562 円', '買付 売却']
    if len(cells) < 3:
        return None
    currency = currency_of(cells[1], currency_of(cells[0], "USD"))
    amount = to_float(cells[1])
    return Holding(
        snapshot_date=date.today(),
        broker="sbi",
        account_type="-",
        is_nisa=False,
        asset_class="現金",
        symbol=currency,
        name=f"預り金({cells[0]})",
        currency=currency,
        quantity=amount,
        market_value=amount,
        market_value_jpy=to_float(cells[2]),
    )
