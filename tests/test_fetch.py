"""fetch モジュールのうちブラウザ無しで検証できる部分。"""
from datetime import date
from pathlib import Path

from portfolio import fetch
from portfolio.parsers import decode_html, detect


def test_pages_registry_is_consistent():
    for key, spec in fetch.PAGES.items():
        assert spec.key == key
        assert spec.url.startswith("https://")
        assert spec.ready and spec.note
        assert spec.subdir in ("", "assets", "funds", "orders")


def test_out_path_is_dated_and_under_subdir():
    p = fetch.out_path(fetch.PAGES["sbi-assets"], Path("imports"), date(2026, 9, 1))
    assert p == Path("imports/assets/20260901-sbi-assets.html")
    p = fetch.out_path(fetch.PAGES["sbi-foreign"], Path("imports"), date(2026, 9, 1))
    assert p == Path("imports/20260901-sbi-foreign.html")


def test_funds_page_comes_after_account_page():
    """保有ファンド（前日比付き）が保有証券一覧を上書きする順で取り込む。"""
    keys = list(fetch.PAGES)
    assert keys.index("sbi-account") < keys.index("sbi-funds")


def test_ready_markers_exist_in_fixtures():
    """描画完了の目印がフィクスチャ（実画面の保存）に実在すること。"""
    fixtures = {
        "sbi-assets": "sbi_my_assets.html", "sbi-foreign": "sbi_foreign_summary.html",
        "sbi-account": "sbi_account.html", "sbi-funds": "sbi_funds.html", "sbi-orders": "sbi_foreign_orders.html",
    }
    for key, name in fixtures.items():
        html = decode_html((Path("tests/fixtures") / name).read_bytes())
        assert any(t in html for t in fetch.PAGES[key].ready), key


def test_saved_html_prefix_forces_utf8_and_keeps_detection():
    """page.content() の先頭に付ける utf-8 宣言が、既存パーサの判定を壊さないこと。"""
    raw = Path("imports/assets").glob("*.html")
    fixture = next(iter(Path("tests/fixtures").glob("*assets*")), None) or next(raw, None)
    if fixture is None:
        return
    html = fixture.read_text(encoding="utf-8", errors="replace")
    prefixed = '<!-- saved by portfolio fetch --><meta charset="utf-8">\n' + html
    assert detect(decode_html(prefixed.encode("utf-8"))) == ("sbi", "balances")
