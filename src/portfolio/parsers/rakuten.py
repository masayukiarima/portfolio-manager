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
    balances = parse_balances(soup, snapshot_date or date.today())
    return ParseResult("rakuten", snapshot_date, holdings, warnings, balances=balances)


# 画面表記 → (正規化区分, 現金同等物か, 合計行か)
_BALANCE_MAP = {
    "資産合計": ("合計", False, True),
    "保有商品の評価額合計": ("保有商品合計", False, True),
    "国内株式": ("国内株式", False, False),
    "米国株式": ("米国株式", False, False),
    "中国株式": ("中国株式", False, False),
    "アセアン株式": ("アセアン株式", False, False),
    "投資信託": ("投資信託", False, False),
    "楽天・マネーファンド": ("MRF", True, False),
    "外貨建MMF": ("外貨建MMF", True, False),
    "国内債券": ("国内債券", False, False),
    "外国債券": ("外国債券", False, False),
    "金・プラチナ": ("金・プラチナ", False, False),
    "預り金合計": ("預り金合計", True, True),
    "預り金": ("預り金(JPY)", True, False),
    "外貨預り金": ("預り金(外貨)", True, False),
    "信用保証金": ("信用保証金", True, False),
    "信用評価損益": ("信用評価損益", False, False),
    "FX証拠金（純資産）": ("FX証拠金", True, False),
    "楽天銀行普通預金残高": ("銀行口座", True, False),
}
_TOKEN_RE = re.compile(r"([+-]?\d[\d,]*(?:\.\d+)?)\s*(円|％|%)|(?<![\d,])(-)(?![\d,])")


def _tokens(text: str) -> list[float | None]:
    """'-70,809 円 +156,676 円 +704,301 円 -3.58 % +8.94 % -' → [day, month, pnl, day%, month%, pnl%]"""
    out: list[float | None] = []
    for num, _unit, dash in _TOKEN_RE.findall(text):
        out.append(None if dash else to_float(num))
    return out


def parse_balances(soup: BeautifulSoup, snap: date) -> list["Balance"]:
    """保有商品一覧の上部にある資産残高テーブル (table.balance-tbl) を読む。"""
    from portfolio.models import Balance

    table = soup.find("table", class_="balance-tbl")
    if table is None:
        return []
    out: list[Balance] = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 2:
            continue
        label = re.sub(r"\s*→.*$", "", tds[0].get_text(" ", strip=True))  # '預り金合計 →口座明細' 等のリンクを除去
        if label not in _BALANCE_MAP:
            continue
        cat, is_cash, is_total = _BALANCE_MAP[label]
        mv = to_float(tds[1].get_text(" ", strip=True))
        if mv is None:
            continue
        t = _tokens(tds[2].get_text(" ", strip=True)) if len(tds) > 2 else []
        t += [None] * (6 - len(t))
        realized = to_float(tds[4].get_text(" ", strip=True)) if len(tds) > 4 else None
        if mv == 0 and not is_total and not any(v for v in t[:3]):
            continue  # 保有の無い区分は省く
        out.append(Balance(
            snapshot_date=snap, broker="rakuten", category=cat, label=label,
            market_value_jpy=mv, day_change_jpy=t[0], month_change_jpy=t[1],
            unrealized_pnl_jpy=t[2], day_change_pct=t[3], month_change_pct=t[4],
            unrealized_pnl_pct=t[5], realized_pnl_jpy=realized, is_cash=is_cash, is_total=is_total,
        ))
    return out


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
