"""DB の各テーブルを資産クラス別に集計し、レポート用のデータを組み立てる。

資産クラス（表示順固定）:
  米国株式 / 投資信託 / 金 / 国内株式 / 暗号資産 / 現金同等物 / その他
- holdings のうち 現金・外貨建MMF は balances 側（is_cash）で数えるので除外する
- balances の合計行 (is_total) は除外する
- 銘柄→資産クラスの上書きは symbol_classes テーブル（無ければ DEFAULT_SYMBOL_CLASSES）
- 推移は「各日付時点で、各ソース（証券会社×テーブル、手入力の各項目）の最新スナップショット」を
  足し合わせる（取込日がずれてもゼロにならないよう前回値を引き継ぐ）
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date

ASSET_CLASSES = ["米国株式", "投資信託", "金", "国内株式", "暗号資産", "現金同等物", "その他"]
DEFAULT_SYMBOL_CLASSES = {"GLDM": "金", "GLD": "金", "IAU": "金", "IAUM": "金", "1540": "金", "1326": "金"}
_CASH_HOLDING_CLASSES = {"現金", "外貨建MMF"}
_USD_CASH_CATEGORIES = {"預り金(USD)", "預り金(外貨)", "外貨建MMF"}


@dataclass
class Snapshot:
    """ある日付時点の資産の断面（各ソースの最新スナップショットを合算したもの）。"""

    date: str
    by_class: dict[str, float]                   # 資産クラス → 円
    cash_usd: float = 0.0                        # 現金同等物のうち外貨（預り金USD・外貨建MMF・USD建の手入力）
    cash_jpy: float = 0.0                        # 現金同等物のうち円
    nisa: float = 0.0                            # NISA 口座の評価額（株式 + 投信）
    cost: float = 0.0                            # 取得額（株式 + 投信 + MMF、含み益の分母）
    pnl: float = 0.0                             # 含み益（株式 + 投信 + MMF）
    usd_jpy: float | None = None                 # 実効レート（USD建て保有の 円換算額 ÷ ドル額）
    flow: float = 0.0                            # この日に反映された入出金（出金は負）

    @property
    def total(self) -> float:
        return sum(self.by_class.values())

    @property
    def yield_pct(self) -> float | None:
        """簿価ベースの含み損益率。年率換算ではない。"""
        return self.pnl / self.cost * 100 if self.cost else None


@dataclass
class Analysis:
    as_of: str
    allocation: dict[str, float]                 # 資産クラス → 円
    history: list[Snapshot]
    total: float
    unrealized_pnl: float
    nisa_value: float
    taxable_pnl: float                           # 特定口座の含み益（株式 + 投信 + MMF）
    currency: dict[str, float]                   # USD / JPY / 暗号資産 → 円
    top_positions: list[dict]                    # symbol, name, cls, mv, pct
    cash_items: list[dict]                       # broker/name, label, mv
    stop_covered_value: float                    # 逆指値が入っている保有の評価額
    equity_value: float                          # 米国株 + 国内株の評価額（逆指値カバー率の分母）
    flows: list[dict] = field(default_factory=list)           # 入出金（date, label, amount, note）
    holdings_rows: list[dict] = field(default_factory=list)   # 全保有銘柄（一覧タブ用）
    funds_rows: list[dict] = field(default_factory=list)
    manual_rows: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def attach_flows(history: list[Snapshot], flows: list[dict]) -> None:
    """入出金を、その日以降で最初にスナップショットがある日に載せる。

    入金した日に必ず取込があるとは限らないので、資産に反映されて見える最初の日に寄せる。
    最終スナップショットより後の入出金は載せる先が無いので捨てる（次回の取込で載る）。
    """
    for s in history:
        s.flow = 0.0
    for f in flows:
        s = next((s for s in history if s.date >= f["date"]), None)
        if s is not None:
            s.flow += f["amount"]


def modified_dietz(rows: list[Snapshot]) -> tuple[float, float, float | None]:
    """(運用損益, 入出金合計, 修正ディーツ利回り%) を返す。rows[0] を期初とする。

    期初の残高は rows[0] の時点の値なので、その日に載った入出金はすでに含まれている。
    期中の入出金は「残っていた日数 ÷ 期間」で加重して分母に足す。
    """
    if len(rows) < 2:
        return 0.0, 0.0, None
    d0, d1 = date.fromisoformat(rows[0].date), date.fromisoformat(rows[-1].date)
    days = (d1 - d0).days
    moves = [(date.fromisoformat(r.date), r.flow) for r in rows[1:] if r.flow]
    total_flow = sum(a for _, a in moves)
    gain = rows[-1].total - rows[0].total - total_flow
    den = rows[0].total + (sum(a * (days - (d - d0).days) / days for d, a in moves) if days else 0)
    return gain, total_flow, (gain / den * 100 if den else None)


def classify_symbol(symbol: str, default_class: str, overrides: dict[str, str]) -> str:
    return overrides.get(symbol, DEFAULT_SYMBOL_CLASSES.get(symbol, default_class))


def _holding_class(row, overrides) -> str | None:
    ac = row["asset_class"]
    if ac in _CASH_HOLDING_CLASSES:
        return None
    base = "米国株式" if ac in ("米国株式", "外国株式") else "国内株式" if ac == "国内株式" else "その他"
    return classify_symbol(row["symbol"], base, overrides)


def _latest_per_key(conn: sqlite3.Connection, table: str, key_col: str, upto: str) -> list:
    """各 key について upto 以前で最新の snapshot_date の行を返す。key_col はカンマ区切りで複合可。

    holdings は同じ証券会社でも「米国株ページ」「国内株ページ」のように保存元が分かれ、日付がずれるため
    broker + asset_class を単位にする（片方だけ新しい日付で取り込んでも、もう片方が消えない）。
    """
    cols = [c.strip() for c in key_col.split(",")]
    on = " AND ".join(f"t.{c} = m.{c}" for c in cols)
    return conn.execute(
        f"SELECT t.* FROM {table} t JOIN (SELECT {', '.join(cols)}, MAX(snapshot_date) d FROM {table} "
        f"WHERE snapshot_date <= ? GROUP BY {', '.join(cols)}) m ON {on} AND t.snapshot_date = m.d",
        (upto,),
    ).fetchall()


def _cost_jpy(row) -> float | None:
    """取得額（円）。画面に取得額が無い証券会社（楽天）は 評価額 − 損益 で補う。"""
    if row["acquisition_amount_jpy"] is not None:
        return row["acquisition_amount_jpy"]
    pnl = row["unrealized_pnl_jpy"]
    return (row["market_value_jpy"] or 0) - pnl if pnl is not None else None


def _build_snapshot(date: str, hold, funds, bals, manual, overrides: dict[str, str]) -> Snapshot:
    """同一日付として扱う行の集合から断面を組み立てる。"""
    alloc = {c: 0.0 for c in ASSET_CLASSES}
    cash = {"USD": 0.0, "JPY": 0.0}
    for r in hold:
        cls = _holding_class(r, overrides)
        if cls:
            alloc[cls if cls in alloc else "その他"] += r["market_value_jpy"] or 0
    for r in funds:
        alloc["投資信託"] += r["market_value_jpy"] or 0
    brokers_with_balances = {r["broker"] for r in bals}
    for r in bals:
        if r["is_cash"] and not r["is_total"]:
            cash["USD" if r["category"] in _USD_CASH_CATEGORIES else "JPY"] += r["market_value_jpy"] or 0
    # balances がまだ無い証券会社は holdings の 現金/MMF 行で代用
    for r in hold:
        if r["broker"] not in brokers_with_balances and r["asset_class"] in _CASH_HOLDING_CLASSES:
            cash["USD" if r["currency"] == "USD" else "JPY"] += r["market_value_jpy"] or 0
    for r in manual:
        cls = r["asset_class"] if r["asset_class"] in alloc else "その他"
        if cls == "現金同等物":
            cash["USD" if r["currency"] == "USD" else "JPY"] += r["amount_jpy"]
        else:
            alloc[cls] += r["amount_jpy"]
    alloc["現金同等物"] += cash["USD"] + cash["JPY"]

    sec = [r for r in hold if r["asset_class"] not in _CASH_HOLDING_CLASSES]
    # 含み益・取得額の対象は 株式・投信・外貨建MMF（預り金は損益を持たない）
    pnl_rows = sec + [r for r in hold if r["asset_class"] == "外貨建MMF"] + list(funds)
    # レートは持たずに保有から逆算する。同じ行から出すので円換算額と必ず整合する
    usd = [r for r in hold if r["currency"] == "USD" and r["market_value"] and r["market_value_jpy"]]
    return Snapshot(
        date=date, by_class={k: v for k, v in alloc.items() if v},
        cash_usd=cash["USD"], cash_jpy=cash["JPY"],
        nisa=sum(r["market_value_jpy"] or 0 for r in sec + list(funds) if r["is_nisa"]),
        cost=sum(c for c in (_cost_jpy(r) for r in pnl_rows) if c is not None),
        pnl=sum(r["unrealized_pnl_jpy"] or 0 for r in pnl_rows),
        usd_jpy=(sum(r["market_value_jpy"] for r in usd) / sum(r["market_value"] for r in usd)) if usd else None,
    )


def snapshot_at(conn: sqlite3.Connection, upto: str, overrides: dict[str, str]) -> Snapshot:
    """upto 以前で各ソースが持つ最新の行を集めて、その日付時点の断面を返す。"""
    return _build_snapshot(
        upto,
        _latest_per_key(conn, "holdings", "broker, asset_class", upto),
        _latest_per_key(conn, "funds", "broker", upto),
        _latest_per_key(conn, "balances", "broker", upto),
        _latest_per_key(conn, "manual_assets", "name", upto),
        overrides,
    )


def allocation_at(conn: sqlite3.Connection, upto: str, overrides: dict[str, str]) -> dict[str, float]:
    return snapshot_at(conn, upto, overrides).by_class


def analyze(conn: sqlite3.Connection) -> Analysis:
    overrides = {r["symbol"]: r["asset_class"] for r in conn.execute("SELECT symbol, asset_class FROM symbol_classes")}
    dates = sorted({r[0] for t in ("holdings", "funds", "balances", "manual_assets")
                    for r in conn.execute(f"SELECT DISTINCT snapshot_date FROM {t}")})
    if not dates:
        raise ValueError("データがありません。先に portfolio import を実行してください")
    as_of = dates[-1]
    hold = _latest_per_key(conn, "holdings", "broker, asset_class", as_of)
    funds = _latest_per_key(conn, "funds", "broker", as_of)
    bals_all = _latest_per_key(conn, "balances", "broker", as_of)
    bals = [r for r in bals_all if r["is_cash"] and not r["is_total"]]
    manual = _latest_per_key(conn, "manual_assets", "name", as_of)
    orders = _latest_per_key(conn, "orders", "broker", as_of)

    # 最新日は取得済みの行から組み立て、それ以前の日付は都度引き直す
    current = _build_snapshot(as_of, hold, funds, bals_all, manual, overrides)
    history = [snapshot_at(conn, d, overrides) for d in dates[:-1]] + [current]
    flows = [{"date": r["snapshot_date"], "label": r["label"], "amount": r["amount_jpy"], "note": r["note"]}
             for r in conn.execute("SELECT * FROM cash_flows ORDER BY snapshot_date, label")]
    attach_flows(history, flows)
    allocation = current.by_class
    total = current.total

    sec = [r for r in hold if r["asset_class"] not in _CASH_HOLDING_CLASSES]
    unrealized = current.pnl
    nisa = current.nisa
    taxable = sum(r["unrealized_pnl_jpy"] or 0 for r in sec if not r["is_nisa"]) \
        + sum(f["unrealized_pnl_jpy"] or 0 for f in funds if not f["is_nisa"]) \
        + sum(r["unrealized_pnl_jpy"] or 0 for r in hold if r["asset_class"] == "外貨建MMF")

    cur = {"USD": 0.0, "JPY": 0.0, "暗号資産": 0.0, "その他": 0.0}
    for r in sec:
        cur["USD" if r["currency"] == "USD" else "JPY" if r["currency"] == "JPY" else "その他"] += r["market_value_jpy"] or 0
    cur["USD"] += sum(f["market_value_jpy"] or 0 for f in funds)  # 対応投信はすべて米国株指数
    for r in bals:
        cur["USD" if r["category"] in _USD_CASH_CATEGORIES else "JPY"] += r["market_value_jpy"] or 0
    for r in manual:
        if r["asset_class"] == "暗号資産":
            cur["暗号資産"] += r["amount_jpy"]
        else:
            cur["USD" if r["currency"] == "USD" else "JPY" if r["currency"] == "JPY" else "その他"] += r["amount_jpy"]
    currency = {k: v for k, v in cur.items() if v}

    by_symbol: dict[str, dict] = {}
    for r in sec:
        d = by_symbol.setdefault(r["symbol"], {"symbol": r["symbol"], "name": r["name"], "mv": 0.0,
                                                "cls": _holding_class(r, overrides)})
        d["mv"] += r["market_value_jpy"] or 0
    for f in funds:
        d = by_symbol.setdefault(f["name"], {"symbol": "投信", "name": f["name"], "mv": 0.0, "cls": "投資信託"})
        d["mv"] += f["market_value_jpy"] or 0
    top = sorted(by_symbol.values(), key=lambda d: -d["mv"])[:12]
    for d in top:
        d["pct"] = d["mv"] / total * 100 if total else 0

    # 0円の手入力は「この日以降は実データを使う」ための打ち切り行なので一覧には出さない
    cash_items = [{"who": r["broker"], "label": r["label"], "mv": r["market_value_jpy"] or 0} for r in bals] \
        + [{"who": "手入力", "label": r["name"], "mv": r["amount_jpy"]} for r in manual
           if r["asset_class"] == "現金同等物" and r["amount_jpy"]]

    stops = {(o["broker"], o["symbol"]) for o in orders if o["side"] == "売" and o["trigger_price"] is not None}
    equity = [r for r in sec if r["asset_class"] in ("米国株式", "外国株式", "国内株式")]
    equity_value = sum(r["market_value_jpy"] or 0 for r in equity)
    covered = sum(r["market_value_jpy"] or 0 for r in equity if (r["broker"], r["symbol"]) in stops)

    holdings_rows = sorted((
        {"broker": r["broker"], "account": r["account_type"], "nisa": bool(r["is_nisa"]), "cls": _holding_class(r, overrides),
         "asset_class": r["asset_class"], "symbol": r["symbol"], "name": r["name"], "qty": r["quantity"],
         "currency": r["currency"], "price": r["price"], "avg_cost": r["avg_cost"],
         # 楽天は円建て取得額が画面に無いので 評価額 − 損益 で補う
         "cost_jpy": r["acquisition_amount_jpy"] if r["acquisition_amount_jpy"] is not None
         else ((r["market_value_jpy"] or 0) - r["unrealized_pnl_jpy"] if r["unrealized_pnl_jpy"] is not None else None),
         "mv": r["market_value_jpy"] or 0, "pnl": r["unrealized_pnl_jpy"],
         "pct": r["unrealized_pnl_pct"], "date": r["snapshot_date"],
         "stop": (r["broker"], r["symbol"]) in stops, "share": (r["market_value_jpy"] or 0) / total * 100 if total else 0}
        for r in sec), key=lambda d: -d["mv"])
    funds_rows = sorted((
        {"broker": f["broker"], "account": f["account_type"], "nisa": bool(f["is_nisa"]), "name": f["name"],
         "units": f["units"], "nav": f["nav"], "avg_cost": f["avg_cost"], "cost_jpy": f["acquisition_amount_jpy"],
         "mv": f["market_value_jpy"] or 0, "pnl": f["unrealized_pnl_jpy"], "pct": f["unrealized_pnl_pct"],
         "date": f["snapshot_date"], "share": (f["market_value_jpy"] or 0) / total * 100 if total else 0}
        for f in funds), key=lambda d: -d["mv"])
    manual_rows = [{"name": r["name"], "cls": r["asset_class"], "currency": r["currency"], "mv": r["amount_jpy"],
                    "date": r["snapshot_date"], "note": r["note"], "share": r["amount_jpy"] / total * 100 if total else 0}
                   for r in manual if r["amount_jpy"]]

    return Analysis(
        as_of=as_of, allocation=allocation, history=history, total=total, unrealized_pnl=unrealized,
        nisa_value=nisa, taxable_pnl=taxable, currency=currency, top_positions=top, cash_items=cash_items,
        stop_covered_value=covered, equity_value=equity_value, flows=flows,
        holdings_rows=holdings_rows, funds_rows=funds_rows, manual_rows=manual_rows,
    )
