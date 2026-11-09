"""SEC 재무값 해석 — 시점(공시일)을 지키는지, 분기→12개월 합이 맞는지."""
import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stock_fund as F  # noqa: E402


def _fact(start, end, val, filed, form="10-Q"):
    d = {"end": end, "val": val, "filed": filed, "form": form, "fy": 2025, "fp": "Q1"}
    if start:
        d["start"] = start
    return d


def _cf():
    q = 100.0
    facts = [
        _fact("2025-01-01", "2025-03-31", q, "2025-05-01"),
        _fact("2025-01-01", "2025-06-30", 2 * q, "2025-08-01"),      # 반기 누적 → 2분기 = 200-100
        _fact("2025-04-01", "2025-06-30", q, "2025-08-01"),
        _fact("2025-01-01", "2025-09-30", 3 * q, "2025-11-01"),      # 3분기: 누적 차이로만
        _fact("2025-01-01", "2025-12-31", 4 * q + 40, "2026-02-15", "10-K"),  # 연간 → 4분기 = 140
        _fact("2025-01-01", "2025-03-31", 999.0, "2026-02-15", "10-K"),        # 나중에 정정된 값은 무시(처음 값 사용)
    ]
    return {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": facts}},
        "StockholdersEquity": {"units": {"USD": [_fact(None, "2025-12-31", 500.0, "2026-02-15"),
                                                 _fact(None, "2025-09-30", 450.0, "2025-11-01")]}},
    }, "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        _fact(None, "2026-02-01", 900000.0, "2026-02-15")] * 3 + [          # 똑같은 중복은 한 번만
        _fact(None, "2026-02-01", 100000.0, "2026-02-15")]}}}}}             # 다른 값(다른 주식 종류)은 합친다


def test_ttm_from_quarters_and_cumulative():
    p = F.parse(_cf())
    rev = p["rev"]
    ends = [e.date() for e, _, _ in rev]
    assert date(2025, 12, 31) in ends
    ttm = dict((e.date(), v) for e, _, v in rev)
    assert ttm[date(2025, 12, 31)] == 100 + 100 + 100 + 140      # 4분기 = 연간 − 9개월 누적


def test_as_of_respects_filing_date():
    p = F.parse(_cf())
    v, e = F.as_of(p["rev"], date(2026, 1, 31))     # 연간 공시(2/15) 전 → 아직 12월 TTM 은 모른다
    assert e != date(2025, 12, 31)
    v2, e2 = F.as_of(p["rev"], date(2026, 3, 1))
    assert e2 == date(2025, 12, 31) and v2 == 440
    eq, _ = F.as_of(p["equity"], date(2025, 12, 1))
    assert eq == 450.0
    vals = F.values_as_of(p, date(2026, 3, 1))
    assert vals["shares"] == 1000000.0 and vals["equity"] == 500.0
    assert vals["shares_end"] == date(2026, 2, 1)
    assert np.isnan(vals["ni"])


def test_coverage_counts_complete_rows():
    full = dict(ni=1.0, rev=1.0, ocf=1.0, equity=1.0, shares=1.0)
    part = dict(full, ocf=float("nan"))
    assert F.coverage({"A": full, "B": part}) == 1
