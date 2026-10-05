import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analyst_sources_edgar import Edgar  # noqa: E402


UA = "Test Agent test@example.com"


class FakeResp:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


class FakeHttp:
    def __init__(self, status=200):
        self.calls, self.status = [], status

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        if url.endswith("company_tickers.json"):
            return FakeResp({"0": {"cik_str": 320193, "ticker": "AAPL"}, "1": {"cik_str": 1067983, "ticker": "BRK-B"}}, self.status)
        return FakeResp({"filings": {"recent": {"form": ["8-K", "10-Q", "8-K"], "filingDate": ["2026-09-30", "2026-09-20", "2026-08-01"], "items": ["2.02,9.01", "", "5.02"]}}})


def test_filings_maps_ticker_to_cik_and_filters_by_date():
    http = FakeHttp()
    e = Edgar(http=http, delay=0, user_agent=UA)
    assert e.filings("AAPL", "2026-09-01") == [{"form": "8-K", "date": "2026-09-30", "items": "2.02,9.01"}, {"form": "10-Q", "date": "2026-09-20", "items": ""}]
    assert http.calls[1][0] == "https://data.sec.gov/submissions/CIK0000320193.json"
    assert all(h == {"User-Agent": UA} for _, h in http.calls)
    e.filings("BRK-B", "2026-09-01")
    assert sum(1 for u, _ in http.calls if u.endswith("company_tickers.json")) == 1   # 표는 한 번만 받는다


def test_unknown_ticker_is_empty_and_network_error_raises():
    assert Edgar(http=FakeHttp(), delay=0).filings("ZZZZ", "2026-09-01") == []
    with pytest.raises(RuntimeError):
        Edgar(http=FakeHttp(status=403), delay=0).filings("AAPL", "2026-09-01")
