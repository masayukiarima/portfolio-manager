from datetime import date
from pathlib import Path

import pytest

from portfolio import db as dbmod
from portfolio.cli import parse_path
from portfolio.parsers import decode_html, detect_broker, rakuten, sbi

FIX = Path(__file__).parent / "fixtures"
MMF = "ブラックロック・スーパー・マネー・マーケット・ファンド（米ドル）"


def test_sbi_parse():
    html = decode_html((FIX / "sbi_foreign_summary.html").read_bytes())
    assert detect_broker(html) == "sbi"
    res = sbi.parse(html)
    assert res.warnings == []
    assert res.snapshot_date == date(2026, 8, 29)
    by = {(h.account_type, h.symbol): h for h in res.holdings}
    assert set(by) == {("特定", "GOOG"), ("特定", "GLDM"), ("NISA", "PFE"), ("特定", MMF), ("-", "USD")}

    g = by[("特定", "GOOG")]
    assert (g.name, g.market, g.currency) == ("アルファベット C", "NASDAQ", "USD")
    assert (g.quantity, g.price, g.price_jpy) == (10, 342.88, 54709)
    assert (g.avg_cost, g.acquisition_amount, g.acquisition_amount_jpy) == (163.84, 1638.40, 243110)
    assert (g.market_value, g.market_value_jpy) == (3428.80, 547099)
    assert (g.unrealized_pnl, g.unrealized_pnl_jpy) == (1790.40, 303989)
    assert g.is_nisa is False and g.asset_class == "米国株式"

    p = by[("NISA", "PFE")]
    assert p.is_nisa is True
    assert (p.unrealized_pnl, p.unrealized_pnl_jpy) == (-95.88, 5982)

    m = by[("特定", MMF)]
    assert m.asset_class == "外貨建MMF"
    assert (m.quantity, m.market_value, m.market_value_jpy, m.unrealized_pnl_jpy) == (4201.96, 4201.96, 670464, 87486)

    c = by[("-", "USD")]
    assert c.asset_class == "現金" and (c.market_value, c.market_value_jpy) == (3569.58, 569562)


def test_rakuten_parse():
    raw = (FIX / "rakuten_possess_all.html").read_bytes()
    html = decode_html(raw)
    assert "楽天証券" in html  # EUC-JP を正しく復号できている
    assert detect_broker(html) == "rakuten"
    res = rakuten.parse(html, year_hint=2026)
    assert res.warnings == []
    assert res.snapshot_date == date(2026, 8, 29)
    by = {h.symbol: h for h in res.holdings}
    assert set(by) == {"ABT", "NVDA", "7203"}

    a = by["ABT"]
    assert (a.asset_class, a.account_type, a.is_nisa, a.currency) == ("米国株式", "特定", False, "USD")
    assert (a.quantity, a.avg_cost, a.price) == (1, 83.47, 112.47)
    assert (a.market_value, a.market_value_jpy, a.unrealized_pnl_jpy, a.unrealized_pnl_pct) == (112.47, 18001, 4839, 36.76)
    assert a.acquisition_amount == 83.47 and a.unrealized_pnl == 29.0

    n = by["NVDA"]
    assert n.is_nisa is True and n.account_type == "NISA成長"

    t = by["7203"]
    assert (t.asset_class, t.currency) == ("国内株式", "JPY")
    assert (t.price, t.price_jpy, t.market_value, t.market_value_jpy) == (2650, 2650, 265000, 265000)
    assert (t.acquisition_amount_jpy, t.unrealized_pnl_jpy) == (250000, 15000)


def test_rakuten_without_year_hint():
    html = decode_html((FIX / "rakuten_possess_all.html").read_bytes())
    assert rakuten.parse(html).snapshot_date is None


def test_import_is_idempotent(tmp_path):
    conn = dbmod.connect(tmp_path / "t.db")
    _, res = parse_path(FIX / "sbi_foreign_summary.html")
    dbmod.upsert_holdings(conn, res.holdings)
    dbmod.upsert_holdings(conn, res.holdings)  # 同じ日付の再取込は上書き
    assert conn.execute("SELECT COUNT(*) FROM holdings").fetchone()[0] == 5
    assert conn.execute("SELECT COUNT(*) FROM holdings WHERE is_nisa = 1").fetchone()[0] == 1

    raw = (FIX / "sbi_foreign_summary.html").read_bytes()
    kw = dict(snapshot_date="2026-08-29", broker="sbi", source_file="x.html", content=raw, row_count=5)
    assert dbmod.record_raw_import(conn, **kw) is True
    assert dbmod.record_raw_import(conn, **kw) is False

    latest = conn.execute("SELECT broker, COUNT(*) FROM latest_holdings GROUP BY broker").fetchall()
    assert [tuple(r) for r in latest] == [("sbi", 5)]


def test_expand_handles_glob_metachars_in_filename(tmp_path):
    from portfolio.cli import _expand

    # 楽天の保存ファイル名は "[PC]" を含む。bash が展開済みの実パスを glob と誤認しないこと
    f = tmp_path / "保有商品一覧 _ 楽天証券[PC].html"
    f.write_text("x", encoding="utf-8")
    assert _expand(str(f)) == [f]
    # 存在しないパスは glob パターンとして扱う
    assert _expand(str(tmp_path / "*.html")) == [f]
    assert _expand(str(tmp_path / "nothing*.html")) == []
    # 「ウェブページ、完全」の付随フォルダ (<name>_files/) 内の HTML は再帰 glob から除外
    sub = tmp_path / "page_files"
    sub.mkdir()
    (sub / "frame.html").write_text("x", encoding="utf-8")
    assert _expand(str(tmp_path / "**" / "*.html")) == [f]


def test_unknown_file_raises(tmp_path):
    f = tmp_path / "x.html"
    f.write_text("<html><body>hello</body></html>", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_path(f)
