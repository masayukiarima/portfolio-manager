from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional


@dataclass
class Holding:
    """証券会社を横断した保有商品1行分の共通レコード。

    金額系の *_jpy は円換算値。外貨建て商品は price / avg_cost などに外貨の値と
    currency を持ち、国内商品は currency="JPY" で price == price_jpy となる。
    """

    snapshot_date: date
    broker: str                 # "sbi" | "rakuten"
    account_type: str           # "特定" | "一般" | "NISA" | "NISA成長" | "NISAつみたて" | "-"
    is_nisa: bool
    asset_class: str            # "米国株式" | "国内株式" | "投資信託" | "外貨建MMF" | "現金" ...
    symbol: str                 # ティッカー/銘柄コード。無い場合は銘柄名
    name: str
    market: Optional[str] = None
    currency: str = "JPY"
    quantity: Optional[float] = None
    price: Optional[float] = None
    price_jpy: Optional[float] = None
    avg_cost: Optional[float] = None
    avg_cost_jpy: Optional[float] = None
    acquisition_amount: Optional[float] = None
    acquisition_amount_jpy: Optional[float] = None
    market_value: Optional[float] = None
    market_value_jpy: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    unrealized_pnl_jpy: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    source_file: Optional[str] = None
    extra: dict = field(default_factory=dict)

    def to_row(self) -> dict:
        d = asdict(self)
        d["snapshot_date"] = self.snapshot_date.isoformat()
        d["is_nisa"] = int(self.is_nisa)
        d.pop("extra")
        return d


@dataclass
class ParseResult:
    broker: str
    snapshot_date: Optional[date]   # ページから読めなかった場合は None
    holdings: list[Holding]
    warnings: list[str] = field(default_factory=list)
