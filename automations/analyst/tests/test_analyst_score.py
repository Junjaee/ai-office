import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analyst_score import HORIZONS, KEEP_DAYS, merge_history, score_lenses  # noqa: E402

DAYS = [f"2026-01-{d:02d}" for d in range(1, 31)]            # 30거래일이라 치자


def series(start, step):
    return [[d, start + step * i] for i, d in enumerate(DAYS)]


def test_merge_history_adds_overwrites_and_trims():
    h = merge_history(None, "2026-01-02", {"value": ["A"], "growth": [], "event": [], "flow": []})
    h2 = merge_history(h, "2026-01-02", {"value": ["B"], "growth": [], "event": [], "flow": []})
    assert h2["days"]["2026-01-02"]["value"] == ["B"] and h["days"]["2026-01-02"]["value"] == ["A"]   # 입력은 그대로
    big = {"days": {f"d{i:04d}": {} for i in range(KEEP_DAYS + 5)}}
    assert len(merge_history(big, "z-last", {})["days"]) == KEEP_DAYS and "z-last" in merge_history(big, "z-last", {})["days"]
    assert merge_history({"days": "broken"}, "2026-01-02", {})["days"] == {"2026-01-02": {}}


def test_score_measures_excess_return_over_index_by_trading_days():
    closes = {"UP": series(100, 2), "DN": series(100, -1)}       # 5일 뒤: UP +10/100, DN -5/100
    index = series(100, 1)                                        # 5일 뒤: +5/100
    hist = {"days": {DAYS[0]: {"value": ["UP", "DN", "GONE"], "growth": [], "event": [], "flow": []}}}
    s = score_lenses(hist, closes, index)
    one = s["value"]["1w"]
    assert one["n"] == 2                                          # GONE 은 종가가 없어 못 잰다
    assert one["avg"] == round(((10 - 5) + (-5 - 5)) / 2, 2)      # %p
    assert one["win"] == 50.0
    assert s["value"]["3m"] == {"n": 0, "avg": None, "win": None}   # 63거래일 뒤 자료가 아직 없다
    assert s["flow"]["1w"] == {"n": 0, "avg": None, "win": None}
    assert set(s) == {"value", "growth", "event", "flow"} and set(s["value"]) == set(HORIZONS)


def test_score_skips_days_missing_from_a_series_and_bad_rows():
    closes = {"UP": series(100, 2)[3:]}                           # 종목 자료가 1월 4일부터
    hist = {"days": {DAYS[0]: {"value": ["UP"]}, DAYS[4]: {"value": ["UP"], "bogus": ["X"]}, "junk": "x"}}
    s = score_lenses(hist, closes, series(100, 1))
    assert s["value"]["1w"]["n"] == 1                             # 1월 1일 것은 종목 자료에 그 날짜가 없어 건너뜀
