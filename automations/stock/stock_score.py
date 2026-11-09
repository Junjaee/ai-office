"""시장 상태와 가치+주주환원 점수 (순수 함수 — 바깥과 통신하지 않는다).

규칙(사용자 결정 2026-09-22, 근거 docs/stock/12-재무제표-팩터-검증.md):
  가치 = z(E/P)·z(B/P)·z(S/P)·z(CF/P) 평균, 주주환원 = z((배당+자사주)/시총), 점수 = 둘의 평균.
  후보 안에서 표준화하고 ±3 에서 자른다. 상위 N 을 동일가중(또는 역변동성).
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

VIX_BUCKETS = [(15, "낮음"), (20, "보통"), (30, "높음"), (10**9, "매우 높음")]


def quarter_of(d: date) -> str:
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def is_new_quarter(last_screen_quarter: str | None, today: date) -> bool:
    """직전 분기 알림 이후 분기가 바뀌었나. 한 번도 안 보냈으면 참."""
    return last_screen_quarter != quarter_of(today)


def market_state(close: pd.DataFrame) -> dict:
    """SPY·VIX·환율의 마지막 값과 상태. close 는 야후 종가표(SPY 기준 거래일)."""
    spy = close["SPY"].dropna()
    last = spy.index[-1]
    ma200 = float(spy.tail(200).mean()) if len(spy) >= 200 else float("nan")
    vix = close["^VIX"].dropna() if "^VIX" in close else pd.Series(dtype=float)
    krw = close["KRW=X"].dropna() if "KRW=X" in close else pd.Series(dtype=float)
    v = float(vix.iloc[-1]) if len(vix) else float("nan")
    bucket = next((lab for cut, lab in VIX_BUCKETS if v < cut), "?") if np.isfinite(v) else "?"
    k = float(krw.iloc[-1]) if len(krw) else float("nan")
    kchg = float(krw.iloc[-1] / krw.iloc[-2] - 1) if len(krw) >= 2 else float("nan")
    return {
        "date": last.date(),
        "spy": float(spy.iloc[-1]),
        "spy_chg": float(spy.iloc[-1] / spy.iloc[-2] - 1) if len(spy) >= 2 else float("nan"),
        "spy_above_ma200": bool(spy.iloc[-1] > ma200) if np.isfinite(ma200) else None,
        "spy_vs_ma200": float(spy.iloc[-1] / ma200 - 1) if np.isfinite(ma200) else float("nan"),
        "spy_dd_1y": float(spy.iloc[-1] / spy.tail(252).max() - 1),
        "vix": v, "vix_bucket": bucket,
        "krw": k, "krw_chg": kchg,
    }


def zscore(s: pd.Series) -> pd.Series:
    sd = s.std()
    if not np.isfinite(sd) or sd == 0:
        return pd.Series(np.nan, index=s.index)
    return ((s - s.mean()) / sd).clip(-3, 3)


def _ratio(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b) & (b > 0)
    return np.where(ok, a / np.where(ok, b, 1), np.nan)


SANE = {"E/P": (-1.0, 1.0), "B/P": (0.0, 20.0), "S/P": (0.0, 20.0), "CF/P": (-1.0, 1.0), "주주환원": (0.0, 0.6)}
MAX_SHARES_AGE = 400   # 주식수 자료가 이보다 오래됐으면 시총을 믿지 않는다(일)


def _winsor(s: pd.Series, lo: float = 0.02, hi: float = 0.98) -> pd.Series:
    """극단값 몇 개가 표준화를 망가뜨리지 않게 2%·98% 지점에서 자른다."""
    return s.clip(s.quantile(lo), s.quantile(hi))


def score_table(members: pd.DataFrame, last_close: pd.Series, fund: dict[str, dict],
                asof: date | None = None) -> pd.DataFrame:
    """종목별 비율과 점수. 시가총액 = 종가 × 공시 주식수. 핵심 값이 없거나 자료가 이상한 종목은 뺀다."""
    rows = []
    for r in members.itertuples():
        f = fund.get(r.ticker)
        px = last_close.get(r.ticker, np.nan)
        if not f or not np.isfinite(px) or px <= 0:
            continue
        se = f.get("shares_end")
        if asof is not None and se is not None and (asof - se).days > MAX_SHARES_AGE:
            continue
        rows.append(dict(ticker=r.ticker, name=r.name, sector=r.sector, price=float(px),
                         mktcap=px * f.get("shares", np.nan), ni=f.get("ni"), rev=f.get("rev"),
                         ocf=f.get("ocf"), equity=f.get("equity"),
                         payout=(0 if not np.isfinite(f.get("div", np.nan)) else f["div"])
                         + (0 if not np.isfinite(f.get("buyback", np.nan)) else f["buyback"]),
                         period_end=f.get("period_end")))
    t = pd.DataFrame(rows)
    if t.empty:
        return t
    t = t[np.isfinite(t["mktcap"]) & (t["mktcap"] > 0)].copy()
    t["E/P"] = _ratio(t["ni"], t["mktcap"])
    t["B/P"] = _ratio(t["equity"], t["mktcap"])
    t["S/P"] = _ratio(t["rev"], t["mktcap"])
    t["CF/P"] = _ratio(t["ocf"], t["mktcap"])
    t["주주환원"] = _ratio(t["payout"], t["mktcap"])
    core = t[["E/P", "B/P", "S/P", "CF/P"]].notna().all(axis=1)
    for c, (lo, hi) in SANE.items():   # 자료 오류(주식수 단위 틀림 등)는 후보에서 뺀다
        core &= t[c].isna() | ((t[c] >= lo) & (t[c] <= hi))
    t = t[core].copy()
    t["가치z"] = pd.concat([zscore(_winsor(t[c])) for c in ("E/P", "B/P", "S/P", "CF/P")], axis=1).mean(axis=1)
    t["환원z"] = zscore(_winsor(t["주주환원"].fillna(0.0)))
    t["점수"] = (t["가치z"] + t["환원z"]) / 2
    return t.sort_values("점수", ascending=False).reset_index(drop=True)


def top_n(table: pd.DataFrame, n: int, weight: str = "equal", close: pd.DataFrame | None = None) -> pd.DataFrame:
    """상위 N 과 비중. weight='invvol' 이면 최근 60일 변동성의 역수로."""
    top = table.head(n).copy()
    if top.empty:
        return top
    if weight == "invvol" and close is not None:
        vol = close[top["ticker"]].tail(61).pct_change().std()
        iv = (1 / vol.replace(0, np.nan)).fillna(0)
        w = (iv / iv.sum()).values if iv.sum() > 0 else np.full(len(top), 1 / len(top))
    else:
        w = np.full(len(top), 1 / len(top))
    top["비중"] = w
    return top


def diff_picks(new: list[str], old: list[str] | None) -> tuple[list[str], list[str]]:
    """(새로 들어온 것, 빠진 것). 지난 목록이 없으면 전부 새것."""
    if not old:
        return list(new), []
    ns, os_ = set(new), set(old)
    return [t for t in new if t not in os_], [t for t in old if t not in ns]
