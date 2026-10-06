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
    big = {"days": {f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}": {} for i in range(KEEP_DAYS + 5)}}
    assert len(merge_history(big, "2026-12-31", {})["days"]) == KEEP_DAYS and "2026-12-31" in merge_history(big, "2026-12-31", {})["days"]
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
    assert one["days"] == 1
    assert s["value"]["3m"] == {"n": 0, "days": 0, "avg": None, "win": None}   # 63거래일 뒤 자료가 아직 없다
    assert s["flow"]["1w"] == {"n": 0, "days": 0, "avg": None, "win": None}
    assert set(s) == {"value", "growth", "event", "flow"} and set(s["value"]) == set(HORIZONS)


def test_score_skips_days_missing_from_a_series_and_bad_rows():
    closes = {"UP": series(100, 2)[3:]}                           # 종목 자료가 1월 4일부터
    hist = {"days": {DAYS[0]: {"value": ["UP"]}, DAYS[4]: {"value": ["UP"], "bogus": ["X"]}, "junk": "x"}}
    s = score_lenses(hist, closes, series(100, 1))
    assert s["value"]["1w"]["n"] == 1                             # 1월 1일 것은 종목 자료에 그 날짜가 없어 건너뜀


def test_merge_history_sanitizes_poisoned_shapes():
    poisoned = {"days": {
        "2026-01-05": {"value": 5, "growth": [["A"]], "event": "AB", "flow": ["X", 3, None, "X", "Y"], "bogus": ["Z"]},
        "2026-01-06": "nope", "not-a-day": {"value": ["A"]}, "2027-01-01": {"value": ["FUTURE"]},   # 오늘(2026-01-10)보다 뒤 날짜
    }}
    d = merge_history(poisoned, "2026-01-10", {"value": ["T", "T"], "growth": "AB"})["days"]
    assert d["2026-01-05"] == {"growth": [], "flow": ["X", "Y"]}    # 숫자·문자열 값은 버리고, 목록은 문자열만·중복은 한 번
    assert set(d) == {"2026-01-05", "2026-01-10"} and d["2026-01-10"] == {"value": ["T"]}
    assert merge_history({"days": []}, "2026-01-10", {})["days"] == {"2026-01-10": {}}


def test_merge_history_future_junk_cannot_push_out_today():
    junk = {"days": {f"2099-{1 + i // 28:02d}-{1 + i % 28:02d}": {"value": ["X"]} for i in range(300)}}
    d = merge_history(junk, "2026-01-10", {"value": ["A"]})["days"]
    assert d == {"2026-01-10": {"value": ["A"]}}


def test_score_never_raises_on_malformed_input():
    index = series(100, 1)
    index[7][1] = None                                               # 지수 종가 하나가 비었다
    closes = {"UP": series(100, 2), "BAD": "x", 5: series(1, 1)}
    hist = {"days": {DAYS[0]: {"value": ["UP", ["L"], 7, "BAD"], "growth": "UP", "event": 5}, DAYS[1]: {"value": ["UP"]},
                     DAYS[2]: ["x"], DAYS[3]: None, 9: {"value": ["UP"]}}}
    s = score_lenses(hist, closes, index)
    assert s["value"]["1w"]["n"] == 2 and s["growth"]["1w"]["n"] == 0 and s["event"]["1w"]["n"] == 0
    for bad in (None, {"days": None}, {"days": "x"}, [], 5):
        assert score_lenses(bad, closes, index)["value"]["1w"]["n"] == 0
    assert score_lenses(hist, None, None)["value"]["1w"]["n"] == 0
    assert score_lenses(hist, {"UP": [["2026-01-01"], None, [DAYS[0], "x"]]}, [None, 3, [DAYS[0], 1]])["value"]["1w"]["n"] == 0


def test_score_measures_ticker_over_the_index_dates():
    up = series(100, 2)
    del up[5]                                                        # 종목 자료에 1월 6일이 없다 — 지수의 5거래일 뒤 날짜
    hist = {"days": {DAYS[0]: {"value": ["UP"]}, DAYS[1]: {"value": ["UP"]}}}
    s = score_lenses(hist, {"UP": up}, series(100, 1))["value"]["1w"]
    assert s["n"] == 1 and s["days"] == 1                            # 1월 1일은 건너뛰고, 1월 2일(→1월 7일)만 잰다
    assert s["avg"] == round((112 / 102 - 106 / 101) * 100, 2)       # 종목: 102→112, 지수: 101→106
