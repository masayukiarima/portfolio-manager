from pathlib import Path

from portfolio import db as dbmod
from portfolio.analysis import ASSET_CLASSES, allocation_at, analyze
from portfolio.cli import main
from portfolio.report import render

FIX = Path(__file__).parent / "fixtures"


def _seed(db: Path, capsys) -> None:
    # 8/29: 楽天 保有一覧(+残高)、SBI 米国株 / 8/30: SBI 保有証券一覧(国内株+投信)、SBI My資産
    for f, d in (("rakuten_possess_all.html", "2026-08-29"), ("sbi_foreign_summary.html", "2026-08-29"),
                 ("sbi_account.html", "2026-08-30"), ("sbi_my_assets.html", "2026-08-30")):
        assert main(["import", "--db", str(db), str(FIX / f), "--date", d]) == 0
    assert main(["manual", "add", "--db", str(db), "別口座現金", "1800000", "--date", "2026-08-29"]) == 0
    assert main(["manual", "add", "--db", str(db), "BTC/ETH", "2700000", "--class", "暗号資産",
                 "--currency", "BTC", "--date", "2026-08-29"]) == 0
    capsys.readouterr()


def test_allocation_classes_and_carry_forward(tmp_path, capsys):
    db = tmp_path / "t.db"
    _seed(db, capsys)
    conn = dbmod.connect(db)

    a29 = allocation_at(conn, "2026-08-29", {})
    # GLDM は既定で「金」に分類され、米国株式から除かれる
    assert a29["金"] == 1674709
    assert a29["暗号資産"] == 2700000
    # 8/29 時点: SBI は balances 未取込 → holdings の 預り金/MMF 行で現金を代用、楽天は balances から
    assert a29["現金同等物"] == 1800000 + 569562 + 670464 + (21284 + 489022)
    assert "投資信託" not in a29
    assert a29["国内株式"] == 265000  # 楽天フィクスチャの 7203

    a30 = allocation_at(conn, "2026-08-30", {})
    assert a30["投資信託"] == 311931 + 944045 + 1111408 + 2801923
    # SBI 国内株(8/30 保有証券一覧) + 楽天 国内株(8/29 引き継ぎ)
    assert a30["国内株式"] == 342650 + 1370600 + 265000
    # 8/30 は SBI の balances があるので、SBI 現金は balances 側（預り金USD + スイープ）から
    assert a30["現金同等物"] == 1800000 + 569562 + 455688 + (21284 + 489022)
    # 米国株・金は 8/29 の値を引き継ぐ
    assert a30["金"] == a29["金"] and a30["米国株式"] == a29["米国株式"]
    assert set(a30) <= set(ASSET_CLASSES)


def test_symbol_class_override(tmp_path, capsys):
    db = tmp_path / "t.db"
    _seed(db, capsys)
    assert main(["classify", "--db", str(db), "GLDM", "その他"]) == 0
    conn = dbmod.connect(db)
    a = allocation_at(conn, "2026-08-30", dbmod.symbol_classes(conn))
    assert "金" not in a and a["その他"] == 1674709
    assert main(["classify", "--db", str(db), "GLDM", "不正な区分"]) == 2
    assert main(["classify", "--db", str(db), "GLDM", "--reset"]) == 0
    assert dbmod.symbol_classes(conn) == {}


def test_analyze_and_render(tmp_path, capsys):
    db = tmp_path / "t.db"
    _seed(db, capsys)
    a = analyze(dbmod.connect(db))
    assert a.as_of == "2026-08-30" and [s.date for s in a.history] == ["2026-08-29", "2026-08-30"]
    assert a.total == sum(a.allocation.values())
    assert a.currency["暗号資産"] == 2700000
    assert a.currency["JPY"] == 1800000 + 455688 + 489022 + 342650 + 1370600 + 265000
    assert a.nisa_value > 0 and a.taxable_pnl > 0
    assert a.top_positions[0]["cls"] == "投資信託"  # 旧つみたてNISA の S&P500 が最大
    gldm = next(p for p in a.top_positions if p["symbol"] == "GLDM")
    assert gldm["cls"] == "金" and gldm["mv"] == 1674709
    assert any(c["label"] == "別口座現金" for c in a.cash_items)

    assert len(a.holdings_rows) == 5 + 3 + 2 - 2  # SBI米国株5(うち現金/MMF2は除外) + 楽天3 + SBI国内株2
    assert a.holdings_rows[0]["mv"] >= a.holdings_rows[-1]["mv"]
    assert any(r["symbol"] == "7203" and r["cls"] == "国内株式" for r in a.holdings_rows)
    assert len(a.funds_rows) == 4 and len(a.manual_rows) == 2

    html = render(a)
    assert "<svg" in html and "資産配分" in html and "資産推移" in html
    assert 'id="tab-holdings"' in html and "保有一覧" in html and "GLDM" in html and "7203" in html
    assert "別口座現金" in html and "暗号資産" in html
    assert 'href="http' not in html and "<script src" not in html  # 自己完結

    out = tmp_path / "r.html"
    assert main(["report", "--db", str(db), "-o", str(out)]) == 0
    assert out.stat().st_size > 5000 and "を生成" in capsys.readouterr().out


def test_manual_list_and_delete(tmp_path, capsys):
    db = tmp_path / "t.db"
    _seed(db, capsys)
    assert main(["manual", "list", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "別口座現金" in out and "1,800,000" in out
    assert main(["manual", "delete", "--db", str(db), "BTC/ETH", "--date", "2026-08-29"]) == 0
    assert "1件" in capsys.readouterr().out
    assert "暗号資産" not in allocation_at(dbmod.connect(db), "2026-08-30", {})
