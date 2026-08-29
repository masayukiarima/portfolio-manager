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
class Order:
    """注文照会画面の1行。スナップショット日ごとに状態を保持する。"""

    snapshot_date: date
    broker: str                     # "sbi" | "rakuten"
    order_key: str                  # 証券会社内で注文を一意に識別するキー（注文番号 or 合成キー）
    order_no: Optional[str]         # 画面上の注文番号（SBI は無し）
    ordered_at: Optional[str]       # 注文日時 "YYYY-MM-DD HH:MM"
    status: str                     # 注文中 / 待機中 / 執行待ち / 執行待ち（繰越） …
    symbol: str
    name: str
    side: str                       # "買" | "売"
    account_type: str               # 特定 / 一般 / NISA …
    is_nisa: bool
    asset_class: str = "米国株式"
    market: Optional[str] = None
    currency: str = "USD"
    quantity: Optional[float] = None
    filled_quantity: Optional[float] = None
    order_type: Optional[str] = None    # 指値 / 成行 / 逆指値 …
    limit_price: Optional[float] = None
    trigger_price: Optional[float] = None   # 逆指値のトリガー価格
    current_price: Optional[float] = None
    avg_fill_price: Optional[float] = None
    expires_on: Optional[str] = None    # 有効期限 "YYYY-MM-DD"
    settlement: Optional[str] = None    # 外貨決済 / 円貨決済
    condition: Optional[str] = None     # 逆指値条件・IFD 等の補足テキスト
    linked_order_no: Optional[str] = None
    source_file: Optional[str] = None

    def to_row(self) -> dict:
        d = asdict(self)
        d["snapshot_date"] = self.snapshot_date.isoformat()
        d["is_nisa"] = int(self.is_nisa)
        return d


@dataclass
class Fund:
    """保有ファンド（投資信託）画面の1行。すべて円建て。"""

    snapshot_date: date
    broker: str
    account_type: str               # 特定 / NISAつみたて / NISA成長 / 旧つみたてNISA …
    is_nisa: bool
    name: str
    units: Optional[float] = None               # 保有口数
    selling_units: Optional[float] = None       # 売却注文中の口数
    nav: Optional[float] = None                 # 基準価額（1万口あたり・円）
    avg_cost: Optional[float] = None            # 取得単価（1万口あたり・円）
    market_value_jpy: Optional[float] = None
    acquisition_amount_jpy: Optional[float] = None
    unrealized_pnl_jpy: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    day_change_jpy: Optional[float] = None
    day_change_pct: Optional[float] = None
    is_accumulating: bool = False               # 積立設定中
    source_file: Optional[str] = None

    def to_row(self) -> dict:
        d = asdict(self)
        d["snapshot_date"] = self.snapshot_date.isoformat()
        d["is_nisa"] = int(self.is_nisa)
        d["is_accumulating"] = int(self.is_accumulating)
        return d


@dataclass
class Balance:
    """資産残高サマリの1行（商品区分ごとの評価額・預り金・銀行残高・合計）。すべて円建て。"""

    snapshot_date: date
    broker: str
    category: str                   # 正規化した区分: 国内株式 / 米国株式 / 投資信託 / 預り金(USD) / 銀行口座 / 合計 …
    label: str                      # 画面表記そのまま
    market_value_jpy: Optional[float] = None
    unrealized_pnl_jpy: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    day_change_jpy: Optional[float] = None
    day_change_pct: Optional[float] = None
    month_change_jpy: Optional[float] = None
    month_change_pct: Optional[float] = None
    realized_pnl_jpy: Optional[float] = None
    is_cash: bool = False           # 預り金・MMF・銀行残高など現金同等物
    is_total: bool = False          # 合計行
    source_file: Optional[str] = None

    def to_row(self) -> dict:
        d = asdict(self)
        d["snapshot_date"] = self.snapshot_date.isoformat()
        d["is_cash"] = int(self.is_cash)
        d["is_total"] = int(self.is_total)
        return d


@dataclass
class ParseResult:
    broker: str
    snapshot_date: Optional[date]   # ページから読めなかった場合は None
    holdings: list[Holding] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    kind: str = "holdings"          # "holdings" | "orders" | "funds" | "balances"
    orders: list[Order] = field(default_factory=list)
    funds: list[Fund] = field(default_factory=list)
    balances: list[Balance] = field(default_factory=list)   # kind に関わらず付随して取れた残高

    @property
    def records(self) -> list:
        return {"orders": self.orders, "funds": self.funds, "balances": self.balances}.get(
            self.kind, self.holdings)

    @property
    def all_records(self) -> list:
        """このページから取れた全レコード（1ページに複数種別が載ることがある）。"""
        return [*self.holdings, *self.orders, *self.funds, *self.balances]
