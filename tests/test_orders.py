from datetime import date
from pathlib import Path

from portfolio import db as dbmod
from portfolio.cli import parse_path
from portfolio.parsers import decode_html, detect, rakuten_orders, sbi_orders

FIX = Path(__file__).parent / "fixtures"


def test_detect_distinguishes_orders_from_holdings():
    assert detect(decode_html((FIX / "sbi_foreign_orders.html").read_bytes())) == ("sbi", "orders")
    assert detect(decode_html((FIX / "sbi_foreign_summary.html").read_bytes())) == ("sbi", "holdings")
    assert detect(decode_html((FIX / "rakuten_orders.html").read_bytes())) == ("rakuten", "orders")
    assert detect(decode_html((FIX / "rakuten_possess_all.html").read_bytes())) == ("rakuten", "holdings")


def test_sbi_orders_parse():
    res = sbi_orders.parse(decode_html((FIX / "sbi_foreign_orders.html").read_bytes()))
    assert res.kind == "orders" and res.warnings == []
    assert res.snapshot_date == date(2026, 8, 29)
    by = {o.symbol: o for o in res.orders}
    assert set(by) == {"GOOG", "NVDA"}

    g = by["GOOG"]
    assert (g.status, g.side, g.account_type, g.is_nisa) == ("注文中", "買", "特定", False)
    assert (g.name, g.market) == ("アルファベット C", "NASDAQ")
    assert (g.ordered_at, g.expires_on) == ("2026-08-29 21:02", "2026-09-04")
    assert (g.quantity, g.filled_quantity) == (1, 0)
    assert (g.order_type, g.limit_price, g.trigger_price) == ("指値", 300.0, None)
    assert (g.current_price, g.avg_fill_price, g.settlement, g.condition) == (342.88, None, "外貨決済", None)
    assert g.order_no is None and g.order_key  # SBI は注文番号が無いので合成キー

    n = by["NVDA"]
    assert (n.status, n.side, n.account_type, n.is_nisa) == ("待機中", "売", "NISA", True)
    assert (n.quantity, n.filled_quantity) == (10, 6)   # 数量10、未約定4 → 約定6
    assert (n.order_type, n.limit_price, n.trigger_price) == ("逆指値/成行", None, 200.0)
    assert n.avg_fill_price == 220.10
    assert "逆指値" in n.condition
    assert g.order_key != n.order_key


def test_rakuten_orders_parse():
    html = decode_html((FIX / "rakuten_orders.html").read_bytes())
    res = rakuten_orders.parse(html, year_hint=2026)
    assert res.kind == "orders" and res.warnings == []
    assert res.snapshot_date == date(2026, 8, 29)
    by = {o.order_no: o for o in res.orders}
    assert list(by) == ["0328", "0326", "0314"]

    e = by["0328"]
    assert (e.symbol, e.name, e.market) == ("EBS", "エマージェント・バイオソリューションズ", "米国市場")
    assert (e.status, e.side, e.account_type, e.is_nisa) == ("執行待ち", "買", "特定", False)
    assert (e.ordered_at, e.expires_on, e.settlement) == ("2026-08-29 22:40", "2026-09-04", "外貨決済")
    assert (e.quantity, e.filled_quantity, e.order_type, e.limit_price) == (1, 0, "指値", 4.0)
    assert e.condition is None and e.linked_order_no is None

    a = by["0326"]
    assert a.linked_order_no == "a-0324-2"
    assert (a.account_type, a.is_nisa, a.side) == ("NISA成長", True, "売")
    assert (a.order_type, a.limit_price, a.trigger_price) == ("逆指値/成行", None, 233.42)
    assert a.expires_on == "2026-10-29"
    assert a.condition.startswith("IFD (執行済)") and "逆指値条件" in a.condition

    f = by["0314"]
    assert f.ordered_at == "2026-07-22 22:38"
    assert (f.order_type, f.limit_price, f.trigger_price) == ("逆指値", None, 114.0)
    assert f.expires_on == "2026-10-29"  # 条件文から補完


def test_rakuten_ordered_at_year_rollover():
    # 12月の注文を翌年1月のスナップショットで見た場合は前年扱い
    assert rakuten_orders._ordered_at("12/30 10:00", date(2027, 1, 5)) == "2026-12-30 10:00"
    assert rakuten_orders._ordered_at("01/03 10:00", date(2027, 1, 5)) == "2027-01-03 10:00"


def test_orders_import_is_idempotent(tmp_path):
    conn = dbmod.connect(tmp_path / "t.db")
    _, res = parse_path(FIX / "rakuten_orders.html")
    res.snapshot_date = date(2026, 8, 29)
    for o in res.orders:
        o.snapshot_date = res.snapshot_date
    dbmod.upsert_orders(conn, res.orders)
    dbmod.upsert_orders(conn, res.orders)
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM latest_orders WHERE is_nisa = 1").fetchone()[0] == 1
    # 別日のスナップショットは別行として履歴が残る
    for o in res.orders:
        o.snapshot_date = date(2026, 8, 30)
    dbmod.upsert_orders(conn, res.orders)
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 6
    assert conn.execute("SELECT COUNT(*) FROM latest_orders").fetchone()[0] == 3


def test_raw_imports_kind_migration(tmp_path):
    import sqlite3

    # kind 列の無い旧スキーマの DB を connect() が拡張できること
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE raw_imports (id INTEGER PRIMARY KEY, snapshot_date TEXT NOT NULL, "
              "broker TEXT NOT NULL, source_file TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE, "
              "row_count INTEGER NOT NULL, imported_at TEXT NOT NULL, content BLOB NOT NULL)")
    c.commit()
    c.close()
    conn = dbmod.connect(p)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(raw_imports)")}
    assert "kind" in cols
    assert dbmod.record_raw_import(conn, snapshot_date="2026-08-29", broker="sbi", source_file="x",
                                   content=b"x", row_count=1, kind="orders") is True
    assert conn.execute("SELECT kind FROM raw_imports").fetchone()[0] == "orders"
