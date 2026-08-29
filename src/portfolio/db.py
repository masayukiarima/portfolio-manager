from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

from portfolio.models import Holding, Order

DEFAULT_DB = Path("portfolio.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS holdings (
    id                     INTEGER PRIMARY KEY,
    snapshot_date          TEXT NOT NULL,
    broker                 TEXT NOT NULL,
    account_type           TEXT NOT NULL,
    is_nisa                INTEGER NOT NULL DEFAULT 0,
    asset_class            TEXT NOT NULL,
    symbol                 TEXT NOT NULL,
    name                   TEXT NOT NULL,
    market                 TEXT,
    currency               TEXT NOT NULL,
    quantity               REAL,
    price                  REAL,
    price_jpy              REAL,
    avg_cost               REAL,
    avg_cost_jpy           REAL,
    acquisition_amount     REAL,
    acquisition_amount_jpy REAL,
    market_value           REAL,
    market_value_jpy       REAL,
    unrealized_pnl         REAL,
    unrealized_pnl_jpy     REAL,
    unrealized_pnl_pct     REAL,
    source_file            TEXT,
    imported_at            TEXT NOT NULL,
    UNIQUE (snapshot_date, broker, account_type, asset_class, symbol)
);
CREATE INDEX IF NOT EXISTS idx_holdings_symbol ON holdings (symbol, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_holdings_date   ON holdings (snapshot_date);

CREATE TABLE IF NOT EXISTS orders (
    id               INTEGER PRIMARY KEY,
    snapshot_date    TEXT NOT NULL,
    broker           TEXT NOT NULL,
    order_key        TEXT NOT NULL,
    order_no         TEXT,
    ordered_at       TEXT,
    status           TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    name             TEXT NOT NULL,
    side             TEXT NOT NULL,
    account_type     TEXT NOT NULL,
    is_nisa          INTEGER NOT NULL DEFAULT 0,
    asset_class      TEXT NOT NULL,
    market           TEXT,
    currency         TEXT NOT NULL,
    quantity         REAL,
    filled_quantity  REAL,
    order_type       TEXT,
    limit_price      REAL,
    trigger_price    REAL,
    current_price    REAL,
    avg_fill_price   REAL,
    expires_on       TEXT,
    settlement       TEXT,
    condition        TEXT,
    linked_order_no  TEXT,
    source_file      TEXT,
    imported_at      TEXT NOT NULL,
    UNIQUE (snapshot_date, broker, order_key)
);
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders (symbol, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_orders_date   ON orders (snapshot_date);

CREATE TABLE IF NOT EXISTS raw_imports (
    id            INTEGER PRIMARY KEY,
    snapshot_date TEXT NOT NULL,
    broker        TEXT NOT NULL,
    source_file   TEXT NOT NULL,
    sha256        TEXT NOT NULL UNIQUE,
    row_count     INTEGER NOT NULL,
    imported_at   TEXT NOT NULL,
    content       BLOB NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'holdings'
);

CREATE VIEW IF NOT EXISTS latest_holdings AS
SELECT h.* FROM holdings h
JOIN (SELECT broker, MAX(snapshot_date) AS d FROM holdings GROUP BY broker) m
  ON h.broker = m.broker AND h.snapshot_date = m.d;

CREATE VIEW IF NOT EXISTS latest_orders AS
SELECT o.* FROM orders o
JOIN (SELECT broker, MAX(snapshot_date) AS d FROM orders GROUP BY broker) m
  ON o.broker = m.broker AND o.snapshot_date = m.d;
"""

# 既存DBへの追加列（列名, 定義）。CREATE TABLE 側にも同じ列を入れておくこと。
_MIGRATIONS = [
    ("raw_imports", "kind", "TEXT NOT NULL DEFAULT 'holdings'"),
]

_HOLDING_COLS = [
    "snapshot_date", "broker", "account_type", "is_nisa", "asset_class", "symbol", "name",
    "market", "currency", "quantity", "price", "price_jpy", "avg_cost", "avg_cost_jpy",
    "acquisition_amount", "acquisition_amount_jpy", "market_value", "market_value_jpy",
    "unrealized_pnl", "unrealized_pnl_jpy", "unrealized_pnl_pct", "source_file",
]
_ORDER_COLS = [
    "snapshot_date", "broker", "order_key", "order_no", "ordered_at", "status", "symbol", "name",
    "side", "account_type", "is_nisa", "asset_class", "market", "currency", "quantity",
    "filled_quantity", "order_type", "limit_price", "trigger_price", "current_price", "avg_fill_price",
    "expires_on", "settlement", "condition", "linked_order_no", "source_file",
]


def connect(path: Path = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for table, col, ddl in _MIGRATIONS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    conn.commit()
    return conn


def _upsert(conn: sqlite3.Connection, table: str, cols: list[str], conflict: str, rows: list[dict]) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    sql = (
        f"INSERT INTO {table} ({', '.join(cols)}, imported_at) "
        f"VALUES ({', '.join(':' + c for c in cols)}, :imported_at) "
        f"ON CONFLICT({conflict}) DO UPDATE SET "
        + ", ".join(f"{c}=excluded.{c}" for c in cols if c != "snapshot_date")
        + ", imported_at=excluded.imported_at"
    )
    with conn:
        for row in rows:
            row["imported_at"] = now
            conn.execute(sql, row)
    return len(rows)


def upsert_holdings(conn: sqlite3.Connection, holdings: list[Holding]) -> int:
    """同一 (snapshot_date, broker, account_type, asset_class, symbol) は上書き。"""
    return _upsert(conn, "holdings", _HOLDING_COLS,
                   "snapshot_date, broker, account_type, asset_class, symbol",
                   [h.to_row() for h in holdings])


def upsert_orders(conn: sqlite3.Connection, orders: list[Order]) -> int:
    """同一 (snapshot_date, broker, order_key) は上書き。"""
    return _upsert(conn, "orders", _ORDER_COLS, "snapshot_date, broker, order_key",
                   [o.to_row() for o in orders])


def record_raw_import(conn: sqlite3.Connection, *, snapshot_date: str, broker: str,
                      source_file: str, content: bytes, row_count: int,
                      kind: str = "holdings") -> bool:
    """取込元HTMLを原本として保存する。同一内容 (sha256) は二重登録しない。新規登録なら True。"""
    digest = hashlib.sha256(content).hexdigest()
    with conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO raw_imports "
            "(snapshot_date, broker, source_file, sha256, row_count, imported_at, content, kind) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (snapshot_date, broker, source_file, digest, row_count,
             datetime.now().isoformat(timespec="seconds"), content, kind),
        )
    return cur.rowcount == 1
