"""保存時刻から「その画面がいつの値か」を判断して助言する部分のテスト。"""
from datetime import date, datetime

from portfolio.cli import timing_notes
from portfolio.models import Holding, ParseResult

TODAY = date(2026, 9, 11)          # 金曜
SAT = datetime(2026, 9, 12, 10, 0)


def _result(*classes: str) -> ParseResult:
    return ParseResult("sbi", TODAY, holdings=[
        Holding(snapshot_date=TODAY, broker="sbi", account_type="特定", is_nisa=False,
                asset_class=c, symbol="X", name="X") for c in classes])


def test_file_saved_on_an_earlier_day_is_called_out():
    notes = timing_notes(datetime(2026, 9, 10, 17, 12), _result("米国株式"), TODAY)
    assert len(notes) == 1
    assert "09/10 17:12 保存" in notes[0] and "2026-09-10 分として取り込みました" in notes[0]


def test_domestic_stocks_saved_before_the_close_are_yesterdays():
    notes = timing_notes(datetime(2026, 9, 11, 8, 39), _result("国内株式", "米国株式"), TODAY)
    assert len(notes) == 1 and "15:30 以降" in notes[0]


def test_no_advice_after_the_close():
    assert timing_notes(datetime(2026, 9, 11, 17, 15), _result("国内株式"), TODAY) == []


def test_no_advice_for_pages_without_domestic_stocks():
    # 投資信託の基準価額は前夕に公表済み、米国株は前夜に引けているので朝の保存でよい
    assert timing_notes(datetime(2026, 9, 11, 8, 36), _result("米国株式"), TODAY) == []
    assert timing_notes(datetime(2026, 9, 11, 8, 36), ParseResult("sbi", TODAY), TODAY) == []


def test_weekend_save_gets_no_close_advice():
    # 土曜は市場が開かないので「15:30以降に保存し直せ」は無意味
    assert timing_notes(SAT, _result("国内株式"), SAT.date()) == []
