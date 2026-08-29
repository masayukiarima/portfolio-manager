from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

from portfolio.models import Holding

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

CREATE TABLE IF NOT EXISTS raw_imports (
    id            INTEGER PRIMARY KEY,
    snapshot_date TEXT NOT NULL,
    broker        TEXT NOT NULL,
    source_file   TEXT NOT NULL,
    sha256        TEXT NOT NULL UNIQUE,
    row_count     INTEGER NOT NULL,
    imported_at   TEXT NOT NULL,
    content       BLOB NOT NULL
);

CREATE VIEW IF NOT EXISTS latest_holdings AS
SELECT h.* FROM holdings h
JOIN (SELECT broker, MAX(snapshot_date) AS d FROM holdings GROUP BY broker) m
  ON h.broker = m.broker AND h.snapshot_date = m.d;
"""

_COLS = [
    "snapshot_date", "broker", "account_type", "is_nisa", "asset_class", "symbol", "name",
    "market", "currency", "quantity", "price", "price_jpy", "avg_cost", "avg_cost_jpy",
    "acquisition_amount", "acquisition_amount_jpy", "market_value", "market_value_jpy",
    "unrealized_pnl", "unrealized_pnl_jpy", "unrealized_pnl_pct", "source_file",
]


def connect(path: Path = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_holdings(conn: sqlite3.Connection, holdings: list[Holding]) -> int:
    """同一 (snapshot_date, broker, account_type, asset_class, symbol) は上書き。"""
    now = datetime.now().isoformat(timespec="seconds")
    sql = (
        f"INSERT INTO holdings ({', '.join(_COLS)}, imported_at) "
        f"VALUES ({', '.join(':' + c for c in _COLS)}, :imported_at) "
        "ON CONFLICT(snapshot_date, broker, account_type, asset_class, symbol) DO UPDATE SET "
        + ", ".join(f"{c}=excluded.{c}" for c in _COLS if c != "snapshot_date")
        + ", imported_at=excluded.imported_at"
    )
    with conn:
        for h in holdings:
            row = h.to_row()
            row["imported_at"] = now
            conn.execute(sql, row)
    return len(holdings)


def record_raw_import(conn: sqlite3.Connection, *, snapshot_date: str, broker: str,
                      source_file: str, content: bytes, row_count: int) -> bool:
    """取込元HTMLを原本として保存する。同一内容 (sha256) は二重登録しない。新規登録なら True。"""
    digest = hashlib.sha256(content).hexdigest()
    with conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO raw_imports "
            "(snapshot_date, broker, source_file, sha256, row_count, imported_at, content) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (snapshot_date, broker, source_file, digest, row_count,
             datetime.now().isoformat(timespec="seconds"), content),
        )
    return cur.rowcount == 1
