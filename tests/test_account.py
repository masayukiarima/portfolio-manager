from pathlib import Path

from portfolio import db as dbmod
from portfolio.cli import main
from portfolio.parsers import decode_html, detect, sbi_account

FIX = Path(__file__).parent / "fixtures"
FANG = "ｉＦｒｅｅＮＥＸＴ　ＦＡＮＧ＋インデックス"
SP500 = "ｅＭＡＸＩＳ　Ｓｌｉｍ　米国株式（Ｓ＆Ｐ５００）"


def test_detect_account_page_and_no_regression():
    assert detect(decode_html((FIX / "sbi_account.html").read_bytes())) == ("sbi", "account")
    for name, expected in (("sbi_funds.html", "funds"), ("sbi_my_assets.html", "balances"),
                           ("sbi_foreign_summary.html", "holdings"), ("sbi_foreign_orders.html", "orders")):
        assert detect(decode_html((FIX / name).read_bytes())) == ("sbi", expected), name


def test_sbi_account_parse_stocks_and_funds():
    res = sbi_account.parse(decode_html((FIX / "sbi_account.html").read_bytes()))
    assert res.warnings == []
    assert res.snapshot_date is None

    stocks = {(h.account_type, h.symbol): h for h in res.holdings}
    assert set(stocks) == {("特定", "1320"), ("NISA成長", "1320")}
    s = stocks[("特定", "1320")]
    assert (s.name, s.asset_class, s.currency, s.market, s.is_nisa) == ("ｉＦ２２５年１", "国内株式", "JPY", "東証", False)
    assert (s.quantity, s.avg_cost, s.price, s.price_jpy) == (5, 53610, 68530, 68530)
    assert (s.acquisition_amount_jpy, s.market_value_jpy, s.unrealized_pnl_jpy) == (268050, 342650, 74600)
    assert s.unrealized_pnl_pct == 27.83
    n = stocks[("NISA成長", "1320")]
    assert n.is_nisa is True and (n.quantity, n.extra["selling_quantity"]) == (20, 5)
    assert (n.market_value_jpy, n.unrealized_pnl_jpy) == (1370600, 200600)

    funds = {(f.account_type, f.name): f for f in res.funds}
    assert set(funds) == {("特定", FANG), ("特定", "ＳＢＩ・Ｖ・全米株式インデックス・ファンド"),
                          ("NISAつみたて", SP500), ("旧つみたてNISA", SP500)}
    f = funds[("特定", FANG)]
    assert (f.units, f.avg_cost, f.nav) == (31129, 64249, 100206)
    assert (f.acquisition_amount_jpy, f.market_value_jpy, f.unrealized_pnl_jpy, f.unrealized_pnl_pct) == (200000, 311931, 111931, 55.97)
    assert f.is_accumulating is False and f.day_change_jpy is None  # このページには無い項目
    o = funds[("旧つみたてNISA", SP500)]
    assert o.is_nisa is True and o.market_value_jpy == 2801923


def test_account_page_imports_into_both_tables(tmp_path, capsys):
    db = tmp_path / "t.db"
    assert main(["import", "--db", str(db), str(FIX / "sbi_account.html"), "--date", "2026-08-30"]) == 0
    out = capsys.readouterr().out
    assert "holdings 2件, funds 4件" in out

    conn = dbmod.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM holdings WHERE asset_class = '国内株式'").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM funds").fetchone()[0] == 4
    assert conn.execute("SELECT kind FROM raw_imports").fetchone()[0] == "holdings+funds"
    mv = conn.execute("SELECT SUM(market_value_jpy) FROM latest_holdings WHERE asset_class = '国内株式'").fetchone()[0]
    assert mv == 342650 + 1370600

    # 保有ファンドページを同日に取り込むと同じ funds 行が上書きされ、行は増えない
    assert main(["import", "--db", str(db), str(FIX / "sbi_funds.html"), "--date", "2026-08-30"]) == 0
    assert conn.execute("SELECT COUNT(*) FROM funds").fetchone()[0] == 4
    assert conn.execute("SELECT is_accumulating FROM funds WHERE account_type = 'NISAつみたて'").fetchone()[0] == 1
