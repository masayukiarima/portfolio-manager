from datetime import date
from pathlib import Path

from portfolio import db as dbmod
from portfolio.cli import main, parse_path
from portfolio.parsers import decode_html, detect, rakuten, sbi_assets

FIX = Path(__file__).parent / "fixtures"


def test_detect_sbi_assets_page():
    assert detect(decode_html((FIX / "sbi_my_assets.html").read_bytes())) == ("sbi", "balances")
    assert detect(decode_html((FIX / "sbi_foreign_summary.html").read_bytes())) == ("sbi", "holdings")
    assert detect(decode_html((FIX / "sbi_funds.html").read_bytes())) == ("sbi", "funds")


def test_sbi_assets_parse():
    res = sbi_assets.parse(decode_html((FIX / "sbi_my_assets.html").read_bytes()))
    assert res.kind == "balances" and res.warnings == []
    assert res.snapshot_date == date(2026, 8, 30)
    by = {b.category: b for b in res.balances}
    assert set(by) == {"国内株式", "米国株式", "預り金(USD)", "銀行口座", "合計"}

    us = by["米国株式"]
    assert (us.label, us.is_cash, us.is_total) == ("米国株式", False, False)
    assert (us.market_value_jpy, us.unrealized_pnl_jpy, us.unrealized_pnl_pct) == (22330275, 9709362, 76.93)
    assert (us.day_change_jpy, us.day_change_pct, us.month_change_jpy, us.month_change_pct) == (0, 0.0, 2379221, 11.93)

    usd = by["預り金(USD)"]
    assert usd.is_cash is True and usd.market_value_jpy == 569562
    assert usd.unrealized_pnl_jpy is None  # '-- --'
    assert usd.month_change_jpy == -513983

    bank = by["銀行口座"]
    assert (bank.label, bank.is_cash, bank.market_value_jpy) == ("スィープ専用銀行口座", True, 455688)

    total = by["合計"]
    assert total.is_total is True and total.market_value_jpy == 25068775


def test_rakuten_holdings_page_also_yields_balances():
    html = decode_html((FIX / "rakuten_possess_all.html").read_bytes())
    res = rakuten.parse(html, year_hint=2026)
    assert res.kind == "holdings" and len(res.holdings) == 3
    by = {b.category: b for b in res.balances}
    # 保有ゼロの区分（国内株式・投資信託・預り金(JPY)）は省かれる
    assert set(by) == {"合計", "保有商品合計", "米国株式", "預り金合計", "預り金(外貨)", "銀行口座"}

    t = by["合計"]
    assert (t.is_total, t.market_value_jpy, t.realized_pnl_jpy) == (True, 1909553, -516112)
    assert (t.day_change_jpy, t.month_change_jpy, t.unrealized_pnl_jpy) == (-70809, 156676, 704301)
    assert (t.day_change_pct, t.month_change_pct, t.unrealized_pnl_pct) == (-3.58, 8.94, None)

    us = by["米国株式"]
    assert (us.market_value_jpy, us.unrealized_pnl_jpy, us.realized_pnl_jpy) == (1888269, 704301, -502987)

    dep = by["預り金合計"]
    assert (dep.label, dep.is_cash, dep.is_total, dep.market_value_jpy) == ("預り金合計", True, True, 21284)
    assert (dep.day_change_jpy, dep.month_change_jpy, dep.unrealized_pnl_jpy) == (73, -144772, None)

    fx = by["預り金(外貨)"]
    assert fx.is_cash is True and fx.market_value_jpy == 21284

    bank = by["銀行口座"]
    assert (bank.label, bank.is_cash, bank.market_value_jpy) == ("楽天銀行普通預金残高", True, 489022)
    assert bank.day_change_jpy is None

    assert all(b.snapshot_date == date(2026, 8, 29) for b in res.balances)


def test_parse_path_stamps_balances_too():
    _, res = parse_path(FIX / "rakuten_possess_all.html")
    assert res.balances and all(b.source_file == "rakuten_possess_all.html" for b in res.balances)
    assert all(b.snapshot_date == res.snapshot_date for b in res.balances)


def test_import_and_balances_command(tmp_path, capsys):
    db = tmp_path / "t.db"
    (tmp_path / "imports").mkdir()
    for name in ("sbi_my_assets.html", "rakuten_possess_all.html"):
        (tmp_path / "imports" / name).write_bytes((FIX / name).read_bytes())
    assert main(["import", "--db", str(db), str(tmp_path / "imports" / "*.html")]) == 0
    out = capsys.readouterr().out
    assert "balances 5件" in out and "holdings 3件, balances 6件" in out

    conn = dbmod.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM balances WHERE broker = 'sbi'").fetchone()[0] == 5
    assert conn.execute("SELECT COUNT(*) FROM balances WHERE broker = 'rakuten'").fetchone()[0] == 6
    cash = conn.execute(
        "SELECT broker, SUM(market_value_jpy) FROM latest_balances WHERE is_cash = 1 AND is_total = 0 GROUP BY broker"
    ).fetchall()
    assert {r[0]: r[1] for r in cash} == {"sbi": 569562 + 455688, "rakuten": 21284 + 489022}
    conn.close()

    assert main(["balances", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "スィープ専用銀行口座" in out and "楽天銀行普通預金残高" in out and "現金同等物" in out

    assert main(["dates", "--db", str(db)]) == 0
    assert "balances" in capsys.readouterr().out
