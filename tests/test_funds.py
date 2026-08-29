from datetime import date
from pathlib import Path

from portfolio import db as dbmod
from portfolio.cli import main, parse_path
from portfolio.parsers import decode_html, detect, sbi_funds

FIX = Path(__file__).parent / "fixtures"
FANG = "ｉＦｒｅｅＮＥＸＴ　ＦＡＮＧ＋インデックス"
SP500 = "ｅＭＡＸＩＳ　Ｓｌｉｍ　米国株式（Ｓ＆Ｐ５００）"


def test_detect_funds_page():
    assert detect(decode_html((FIX / "sbi_funds.html").read_bytes())) == ("sbi", "funds")
    # 既存ページの判定が壊れていないこと
    assert detect(decode_html((FIX / "sbi_foreign_summary.html").read_bytes())) == ("sbi", "holdings")
    assert detect(decode_html((FIX / "sbi_foreign_orders.html").read_bytes())) == ("sbi", "orders")


def test_sbi_funds_parse():
    res = sbi_funds.parse(decode_html((FIX / "sbi_funds.html").read_bytes()))
    assert res.kind == "funds" and res.warnings == []
    assert res.snapshot_date is None  # ページに日付が無い → 呼び出し側で補完
    by = {(f.account_type, f.name): f for f in res.funds}
    assert set(by) == {("特定", FANG), ("特定", "ＳＢＩ・Ｖ・全米株式インデックス・ファンド"),
                       ("NISAつみたて", SP500), ("旧つみたてNISA", SP500)}

    f = by[("特定", FANG)]
    assert (f.is_nisa, f.is_accumulating) == (False, False)
    assert (f.units, f.selling_units, f.nav, f.avg_cost) == (31129, 0, 100206, 64249)
    assert (f.market_value_jpy, f.acquisition_amount_jpy) == (311931, 200000)
    assert (f.unrealized_pnl_jpy, f.unrealized_pnl_pct) == (111931, 55.97)
    assert (f.day_change_jpy, f.day_change_pct) == (5252, 1.71)

    v = by[("特定", "ＳＢＩ・Ｖ・全米株式インデックス・ファンド")]
    assert v.selling_units == 1000

    t = by[("NISAつみたて", SP500)]
    assert (t.is_nisa, t.is_accumulating) == (True, True)
    assert t.name == SP500  # バッジ「積立設定中」が名前に混ざらない

    o = by[("旧つみたてNISA", SP500)]
    assert o.is_nisa is True
    assert (o.day_change_jpy, o.day_change_pct) == (-23852, -0.86)


def test_normalize_account():
    n = sbi_funds._normalize_account
    assert n("特定") == "特定"
    assert n("NISA (つみたて)") == "NISAつみたて"
    assert n("NISA (成長投資枠)") == "NISA成長"
    assert n("旧つみたてNISA") == "旧つみたてNISA"


def test_funds_import_and_commands(tmp_path, capsys):
    db = tmp_path / "t.db"
    conn = dbmod.connect(db)
    _, res = parse_path(FIX / "sbi_funds.html")
    assert res.snapshot_date is not None  # ファイル更新日時で補完される
    for f in res.funds:
        f.snapshot_date = date(2026, 8, 30)
    dbmod.upsert_funds(conn, res.funds)
    dbmod.upsert_funds(conn, res.funds)
    assert conn.execute("SELECT COUNT(*) FROM funds").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM latest_funds WHERE is_nisa = 1").fetchone()[0] == 2
    # 同名ファンドでも口座区分が違えば別行
    assert conn.execute("SELECT COUNT(*) FROM funds WHERE name = ?", (SP500,)).fetchone()[0] == 2
    conn.close()

    assert main(["funds", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert FANG in out and "NISAつみたて" in out

    assert main(["dates", "--db", str(db)]) == 0
    assert "funds" in capsys.readouterr().out
