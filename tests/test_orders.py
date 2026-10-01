import os
from datetime import date, datetime
from pathlib import Path

from portfolio import db as dbmod
from portfolio.analysis import latest_orders
from portfolio.cli import parse_path
from portfolio.parsers import decode_html, detect, parse_html, rakuten_orders, sbi_orders

FIX = Path(__file__).parent / "fixtures"


def test_detect_distinguishes_orders_from_holdings():
    assert detect(decode_html((FIX / "sbi_foreign_orders.html").read_bytes())) == ("sbi", "orders")
    assert detect(decode_html((FIX / "sbi_foreign_summary.html").read_bytes())) == ("sbi", "holdings")
    assert detect(decode_html((FIX / "rakuten_orders.html").read_bytes())) == ("rakuten", "orders")
    assert detect(decode_html((FIX / "rakuten_possess_all.html").read_bytes())) == ("rakuten", "holdings")


def test_sbi_orders_page_with_no_orders():
    """注文が0件だと見出し行ごと消えるが、保有一覧ではなく注文画面として判定する。"""
    html = ('<html><body class="sbisec"><article class="main-content">'
            '<p>現在の現地約定日 : 2026/09/10</p>'
            '<p>指定された条件での注文履歴は見つかりませんでした。</p>'
            '</article></body></html>')
    assert detect(html) == ("sbi", "orders")
    res = parse_html(html)
    assert res.kind == "orders" and res.orders == []
    assert res.warnings and "注文行が見つかりませんでした" in res.warnings[0]


def test_rakuten_orders_page_with_no_orders():
    """注文が0件だと注文テーブルごと消えるが、判定不能にせず注文画面として 0 件で返す。"""
    html = ('<html><head><title>米国株式取引 注文照会・訂正・取消 | 注文 | 外国株式 | 楽天証券[PC]</title></head>'
            '<body><h1>米国株式取引 注文照会・訂正・取消</h1>'
            '<div><span class="pcmm-art__hdg">該当する情報はありません。</span></div>'
            '</body></html>')
    assert detect(html) == ("rakuten", "orders")
    res = parse_html(html, year_hint=2026)
    assert res.kind == "orders" and res.orders == []
    assert res.warnings == ["楽天注文: 注文行が見つかりませんでした（注文なし）"]
    assert res.snapshot_date is None  # 画面に時刻が出ないので、取込側がファイルの更新日時で補う

    # 同じ空表示の文言は保有商品一覧にも出る（該当なしの商品区分）。注文画面とは判定しない
    holdings = decode_html((FIX / "rakuten_possess_all.html").read_bytes())
    holdings = holdings.replace("</body>", "<span>該当する情報はありません。</span></body>")
    assert detect(holdings) == ("rakuten", "holdings")


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


def test_sql_command(tmp_path, capsys):
    from portfolio.cli import main

    db = str(tmp_path / "t.db")
    _, res = parse_path(FIX / "rakuten_orders.html")
    conn = dbmod.connect(Path(db))
    dbmod.upsert_orders(conn, res.orders)
    conn.close()

    assert main(["sql", "--db", db, "SELECT order_no, symbol FROM orders ORDER BY order_no"]) == 0
    out = capsys.readouterr().out
    assert "order_no" in out and "0314" in out and "(3 rows)" in out

    assert main(["sql", "--db", db, "--csv", "SELECT order_no FROM orders ORDER BY order_no"]) == 0
    assert capsys.readouterr().out.splitlines() == ["order_no", "0314", "0326", "0328"]

    assert main(["sql", "--db", db, "SELEC x"]) == 1
    assert "SQL error" in capsys.readouterr().err


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


def test_empty_orders_capture_supersedes_older_orders(tmp_path):
    """注文を全部取り消した日は 0 件で取り込まれる。行が無くても前の日の注文を残さない。"""
    conn = dbmod.connect(tmp_path / "t.db")
    _, res = parse_path(FIX / "sbi_foreign_orders.html")
    res.snapshot_date = date(2026, 9, 1)
    for o in res.orders:
        o.snapshot_date = res.snapshot_date
    dbmod.upsert_orders(conn, res.orders)
    dbmod.record_raw_import(conn, snapshot_date="2026-09-01", broker="sbi",
                            source_file="orders.html", content=b"x", row_count=len(res.orders),
                            kind="orders")
    assert len(latest_orders(conn, "2026-09-01")) == len(res.orders)
    assert len(conn.execute("SELECT * FROM latest_orders").fetchall()) == len(res.orders)

    # 9/10 に注文0件の画面を取り込む（orders テーブルには行が増えない）
    dbmod.record_raw_import(conn, snapshot_date="2026-09-10", broker="sbi",
                            source_file="orders_empty.html", content=b"y", row_count=0,
                            kind="orders")
    assert latest_orders(conn, "2026-09-10") == []
    assert conn.execute("SELECT * FROM latest_orders").fetchall() == []
    # 取込前の日付で見れば、その時点で有効だった注文は残っている
    assert len(latest_orders(conn, "2026-09-05")) == len(res.orders)


def _save(path: Path, content: bytes, day: int) -> None:
    """2026-08-<day> 21:30 に保存したファイルとして置く（楽天は年を、空の注文照会は日付ごと更新日時から取る）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    at = datetime(2026, 8, day, 21, 30).timestamp()
    os.utime(path, (at, at))


def test_import_assumes_no_orders_when_orders_page_was_not_saved(tmp_path, monkeypatch, capsys):
    """保有一覧だけ保存し直した日は、注文照会が古いまま（または無い）でも注文なしとして取り込む。"""
    from portfolio.cli import main

    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    holdings, orders = tmp_path / "imports" / "h.html", tmp_path / "imports" / "orders" / "o.html"
    _save(orders, (FIX / "rakuten_orders.html").read_bytes(), 29)
    assert main(["import", "--db", db, str(orders), "--date", "2026-08-28"]) == 0   # 前日の注文 3 件
    orders.unlink()
    _save(holdings, (FIX / "rakuten_possess_all.html").read_bytes(), 29)
    capsys.readouterr()

    # ファイルを指定した取込では、注文照会が無くても何も推測しない
    assert main(["import", "--db", db, str(holdings)]) == 0
    assert "注文なし" not in capsys.readouterr().out

    assert main(["import", "--db", db, "--dry-run"]) == 0
    assert "[dry-run] rakuten: imports/orders に 2026-08-29 分の注文照会が無いため" in capsys.readouterr().out
    conn = dbmod.connect(Path(db))
    assert len(conn.execute("SELECT * FROM latest_orders").fetchall()) == 3   # dry-run では書かない

    assert main(["import", "--db", db]) == 0
    out = capsys.readouterr().out
    assert "[note] rakuten: imports/orders に 2026-08-29 分の注文照会が無いため、注文なし（0件）として処理しました" in out
    assert "2026-08-28 取込の 3 件は最新の注文から外れます" in out
    assert conn.execute("SELECT * FROM latest_orders").fetchall() == []
    assert latest_orders(conn, "2026-08-29") == [] and len(latest_orders(conn, "2026-08-28")) == 3
    marks = "SELECT snapshot_date, broker, kind, row_count FROM raw_imports WHERE source_file = ?"
    assert [tuple(r) for r in conn.execute(marks, (dbmod.NO_ORDERS_SOURCE,))] == [("2026-08-29", "rakuten", "orders", 0)]

    # 古い注文照会がフォルダに残っていても同じ。保存し直しは勧めず、同じ日を二重には記録しない
    _save(orders, "<title>米国株式取引 注文照会・訂正・取消 | 楽天証券[PC]</title>"
                  "<span>該当する情報はありません。</span>".encode("euc_jp"), 28)
    assert main(["import", "--db", db]) == 0
    out = capsys.readouterr().out
    assert "rakuten 2026-08-28 orders 0件" in out and "注文なし（0件）として処理しました (記録済み)" in out
    assert [line for line in out.splitlines() if "o.html" in line and "保存し直してください" in line] == []
    assert len(conn.execute(marks, (dbmod.NO_ORDERS_SOURCE,)).fetchall()) == 1


def test_import_keeps_orders_when_orders_page_is_current(tmp_path, monkeypatch, capsys):
    from portfolio.cli import main

    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    _save(tmp_path / "imports" / "h.html", (FIX / "rakuten_possess_all.html").read_bytes(), 29)
    _save(tmp_path / "imports" / "orders" / "o.html", (FIX / "rakuten_orders.html").read_bytes(), 29)
    assert main(["import", "--db", db]) == 0
    assert "注文なし" not in capsys.readouterr().out
    conn = dbmod.connect(Path(db))
    assert len(conn.execute("SELECT * FROM latest_orders").fetchall()) == 3
    marks = "SELECT COUNT(*) FROM raw_imports WHERE source_file = ?"
    assert conn.execute(marks, (dbmod.NO_ORDERS_SOURCE,)).fetchone()[0] == 0

    # 取込後に注文照会を片付けて取り込み直しても、その日の注文は取込済みなので何も足さない
    (tmp_path / "imports" / "orders" / "o.html").unlink()
    assert main(["import", "--db", db]) == 0
    assert "注文なし" not in capsys.readouterr().out
    assert len(conn.execute("SELECT * FROM latest_orders").fetchall()) == 3
    assert conn.execute(marks, (dbmod.NO_ORDERS_SOURCE,)).fetchone()[0] == 0
