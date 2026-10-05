"""analyst_sources_us — 야후 파이낸스 응답(가짜)을 raw 모양으로."""
import datetime as dt

import pandas as pd
import pytest

import analyst_sources_us as s


class FakeTicker:
    def __init__(self, days=250, info=None, calendar=None):
        idx = pd.date_range("2025-10-06", periods=days, freq="B", tz="America/New_York")
        self._hist = pd.DataFrame({"Close": [100.0 + i for i in range(days)], "Volume": [1000 + i for i in range(days)]}, index=idx)
        self.info = info if info is not None else {"longName": "Test Corp", "exchange": "NMS", "sector": "Technology", "forwardPE": 12.5}
        self.calendar = calendar if calendar is not None else {"Earnings Date": [dt.date(2026, 12, 11)]}
        cols = [pd.Timestamp("2026-05-31"), pd.Timestamp("2025-05-31")]
        self.income_stmt = pd.DataFrame({cols[0]: [67e9, 17e9], cols[1]: [57e9, 12e9]}, index=["Total Revenue", "Net Income"])
        self.cashflow = pd.DataFrame({cols[0]: [-55e9, -23e9], cols[1]: [-21e9, -0.4e9]}, index=["Capital Expenditure", "Free Cash Flow"])

    def history(self, period="1y", auto_adjust=False):
        return self._hist


class FakeYf:
    def __init__(self, ticker):
        self.ticker = ticker

    def Ticker(self, t):
        return self.ticker


def test_fetch_raw_shape():
    raw = s.fetch_raw("TEST", yf=FakeYf(FakeTicker()))
    assert raw["t"] == "TEST" and raw["name"] == "Test Corp" and raw["sector"] == "Technology"
    assert len(raw["closes"]) == 250 and raw["closes"][0][0] == "2025-10-06" and len(raw["volumes"]) == 250
    assert raw["ath"] == 349.0 and raw["ath_date"] == raw["closes"][-1][0]
    assert raw["next_earn"] == "2026-12-11"
    assert raw["annual"] == [{"fy": 2025, "rev": 57e9, "ni": 12e9, "capex": 21e9, "fcf": -0.4e9},
                             {"fy": 2026, "rev": 67e9, "ni": 17e9, "capex": 55e9, "fcf": -23e9}]   # 오래된 해부터, 설비 투자는 양수로


def test_too_little_history_is_an_error():
    with pytest.raises(ValueError):
        s.fetch_raw("NEW", yf=FakeYf(FakeTicker(days=10)))


def test_missing_calendar_and_statements_are_tolerated():
    t = FakeTicker(calendar={})
    t.income_stmt = pd.DataFrame(); t.cashflow = pd.DataFrame()
    raw = s.fetch_raw("TEST", yf=FakeYf(t))
    assert raw["next_earn"] is None and raw["annual"] == []
