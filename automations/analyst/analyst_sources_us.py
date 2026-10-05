"""주식 분석 — 미국 종목 원자료를 야후 파이낸스(yfinance)에서 받는다.

야후는 공식 서비스가 아니라 가끔 막히거나 값이 빈다. 여기서는 한 종목만 받고, 실패는 예외로 올린다
(몇 종목 실패는 run_analyst 가 세고 넘어간다). 값이 없으면 None 으로 두고 계산 쪽이 "자료 없음"으로 처리한다.
"""
from __future__ import annotations

MIN_DAYS = 30


def _stmt(df, row: str, col):
    try:
        v = float(df.loc[row, col])
    except Exception:  # noqa: BLE001 — 행이 없거나 NaN
        return None
    return v if v == v else None


def _annual(tk) -> list[dict]:
    """최근 4개 회계연도: 매출·순이익·설비 투자(양수)·쓰고 남은 현금. 오래된 해부터."""
    try:
        inc, cf = tk.income_stmt, tk.cashflow
        cols = list(inc.columns)[:4]
    except Exception:  # noqa: BLE001
        return []
    out = []
    for col in cols:
        capex = _stmt(cf, "Capital Expenditure", col)
        out.append({"fy": int(col.year), "rev": _stmt(inc, "Total Revenue", col), "ni": _stmt(inc, "Net Income", col),
                    "capex": None if capex is None else abs(capex), "fcf": _stmt(cf, "Free Cash Flow", col)})
    return sorted(out, key=lambda x: x["fy"])


def _next_earn(tk) -> str | None:
    try:
        cal = tk.calendar
        dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
        return str(dates[0]) if dates else None
    except Exception:  # noqa: BLE001
        return None


def fetch_raw(ticker: str, yf=None) -> dict:
    if yf is None:
        import yfinance as yf  # noqa: PLC0415 — 시험에서는 가짜를 넣는다
    tk = yf.Ticker(ticker)
    hist = tk.history(period="max", auto_adjust=False)
    close = hist["Close"].dropna()
    if len(close) < MIN_DAYS:
        raise ValueError(f"가격 자료가 {len(close)}일뿐")
    year = close.iloc[-252:]
    vol = hist["Volume"].reindex(year.index).fillna(0)
    info = dict(tk.info or {})
    return {
        "t": ticker, "name": info.get("longName") or info.get("shortName") or ticker,
        "exchange": info.get("exchange") or "", "sector": info.get("sector") or "",
        "closes": [[d.strftime("%Y-%m-%d"), float(v)] for d, v in year.items()],
        "volumes": [float(v) for v in vol.tolist()],
        "ath": float(close.max()), "ath_date": close.idxmax().strftime("%Y-%m-%d"),
        "info": info, "next_earn": _next_earn(tk), "annual": _annual(tk),
    }
