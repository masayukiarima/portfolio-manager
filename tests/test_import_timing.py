"""保存時刻から「その画面がいつの値か」を判断して助言する部分のテスト。

国内は 15:30 引け、投信の基準価額は夕方公表、米国は 22:30（冬時間 23:30）寄り付き。
3つが揃うのは平日 21:00〜22:30 なので、そこから外れたものだけを指摘する。
"""
from datetime import date, datetime, time

from portfolio.cli import timing_notes, us_market_open
from portfolio.models import Fund, Holding, ParseResult

FRI = date(2026, 9, 11)
SAT = date(2026, 9, 12)


def _result(*classes: str, funds: bool = False) -> ParseResult:
    return ParseResult("sbi", FRI, funds=[
        Fund(snapshot_date=FRI, broker="sbi", account_type="特定", is_nisa=False, name="F")
    ] if funds else [], holdings=[
        Holding(snapshot_date=FRI, broker="sbi", account_type="特定", is_nisa=False,
                asset_class=c, symbol="X", name="X") for c in classes])


def test_file_saved_on_an_earlier_day_is_called_out():
    notes = timing_notes(datetime(2026, 9, 10, 21, 30), _result("米国株式"), FRI)
    assert len(notes) == 1
    assert "09/10 21:30 保存" in notes[0] and "2026-09-10 分として取り込みました" in notes[0]


def test_recommended_window_is_quiet():
    at = datetime(2026, 9, 11, 21, 30)
    assert timing_notes(at, _result("国内株式", "米国株式", funds=True), FRI) == []


def test_morning_save_flags_domestic_stocks_and_funds():
    notes = timing_notes(datetime(2026, 9, 11, 8, 49), _result("国内株式", "米国株式", funds=True), FRI)
    assert len(notes) == 2
    assert "国内株式は前営業日の終値" in notes[0] and "15:30 引け" in notes[0]
    assert "投資信託は当日公表分の基準価額ではない" in notes[1]


def test_just_after_the_close_still_flags_funds_only():
    notes = timing_notes(datetime(2026, 9, 11, 15, 45), _result("国内株式", funds=True), FRI)
    assert len(notes) == 1 and "投資信託" in notes[0]


def test_after_the_us_open_flags_intraday_prices():
    notes = timing_notes(datetime(2026, 9, 11, 23, 0), _result("米国株式"), FRI)
    assert len(notes) == 1 and "場中の値" in notes[0] and "22:30" in notes[0]


def test_us_open_follows_daylight_saving():
    assert us_market_open(date(2026, 9, 11)) == time(22, 30)   # 夏時間
    assert us_market_open(date(2026, 12, 11)) == time(23, 30)  # 冬時間
    assert us_market_open(date(2026, 3, 8)) == time(22, 30)    # 3月第2日曜から夏時間
    assert us_market_open(date(2026, 3, 7)) == time(23, 30)
    assert us_market_open(date(2026, 11, 1)) == time(23, 30)   # 11月第1日曜で冬時間へ
    assert us_market_open(date(2026, 10, 31)) == time(22, 30)
    # 冬時間なら 23:00 の保存はまだ寄り付き前
    assert timing_notes(datetime(2026, 12, 11, 23, 0), _result("米国株式"), date(2026, 12, 11)) == []


def test_weekend_save_gets_no_market_advice():
    at = datetime(2026, 9, 12, 10, 0)
    assert timing_notes(at, _result("国内株式", funds=True), SAT) == []
