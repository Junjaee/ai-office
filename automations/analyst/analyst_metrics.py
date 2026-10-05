"""주식 분석 — 원자료(raw) → 화면용 종목 기록(record). 순수 계산만(네트워크·시계 없음).

자료 모양은 docs/superpowers/plans/2026-10-05-주식-분석-봇-1단계-미국-관심종목.md 의 "자료 모양".
값이 없으면 0 이 아니라 None 으로 둔다(화면은 "자료 없음"으로 보인다).
"""
from __future__ import annotations

import math

SPARK_POINTS = 60      # 판의 흐름선 점 수
CHART_POINTS = 130     # 종목 한 장 그래프 점 수(이틀에 한 점쯤)
BIG_MOVE_PCT = 7.0     # 이만큼 넘게 움직인 날을 "큰 변동일"로 찍는다
FINANCIAL_SECTORS = {"Financial Services"}


def num(v) -> float | None:
    """숫자가 아니거나 NaN·무한대면 None."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def thin(values: list, n: int) -> list:
    """고르게 n 개만 남긴다(처음과 마지막은 반드시 포함)."""
    if len(values) <= n or n < 2:
        return list(values)
    step = (len(values) - 1) / (n - 1)
    return [values[round(i * step)] for i in range(n)]


def big_moves(closes: list, limit: int = 4, floor: float = BIG_MOVE_PCT) -> list[dict]:
    """하루 등락이 floor% 이상인 날 중 큰 순서로 limit 개, 날짜순으로 돌려준다."""
    out = []
    for (_, prev), (day, cur) in zip(closes, closes[1:]):
        if not prev:
            continue
        p = (cur / prev - 1) * 100
        if abs(p) >= floor:
            out.append({"date": day, "pct": round(p, 1), "close": round(cur, 2)})
    out.sort(key=lambda x: -abs(x["pct"]))
    return sorted(out[:limit], key=lambda x: x["date"])


def _dv_ratio(closes: list, volumes: list) -> float | None:
    """최근 5일 평균 거래대금 ÷ 60일 평균 거래대금."""
    dv = [c * v for (_, c), v in zip(closes, volumes) if c and v]
    if len(dv) < 60:
        return None
    base = sum(dv[-60:]) / 60
    return round(sum(dv[-5:]) / 5 / base, 2) if base else None


def _pct(v) -> float | None:
    f = num(v)
    return None if f is None else round(f * 100, 1)


def build_record(raw: dict) -> dict:
    closes = [[d, float(c)] for d, c in raw["closes"]]
    info = raw.get("info") or {}
    price, prev = closes[-1][1], closes[-2][1]
    values = [c for _, c in closes]
    hi52, lo52 = max(values), min(values)
    ath = num(raw.get("ath")) or hi52
    debt, cash, ebitda = num(info.get("totalDebt")), num(info.get("totalCash")), num(info.get("ebitda"))
    nde = None
    if debt is not None and cash is not None and ebitda and ebitda > 0:
        nde = round((debt - cash) / ebitda, 2)
    tmean = num(info.get("targetMeanPrice"))
    tgt = None if tmean is None else {"mean": tmean, "lo": num(info.get("targetLowPrice")), "hi": num(info.get("targetHighPrice")),
                                      "n": int(num(info.get("numberOfAnalystOpinions")) or 0)}
    return {
        "t": raw["t"], "name": raw.get("name") or raw["t"], "exchange": raw.get("exchange") or "", "sector": raw.get("sector") or "",
        "financial": (raw.get("sector") or "") in FINANCIAL_SECTORS,
        "as_of": closes[-1][0], "price": round(price, 2), "chg_pct": round((price / prev - 1) * 100, 2) if prev else None,
        "hi52": hi52, "lo52": lo52, "off_hi_pct": round((price / hi52 - 1) * 100, 1),
        "ath": ath, "ath_date": raw.get("ath_date") or "", "ath_pct": round((price / ath - 1) * 100, 1),
        "y_ret_pct": round((price / values[0] - 1) * 100, 1) if values[0] else None,
        "spark": [round(v, 2) for v in thin(values, SPARK_POINTS)],
        "chart": [[d, round(c, 2)] for d, c in thin(closes, CHART_POINTS)],
        "moves": big_moves(closes),
        "dv_ratio": _dv_ratio(closes, raw.get("volumes") or []),
        "fpe": num(info.get("forwardPE")), "tpe": num(info.get("trailingPE")), "pb": num(info.get("priceToBook")), "mcap": num(info.get("marketCap")),
        "rev_g": _pct(info.get("revenueGrowth")), "eps_g": _pct(info.get("earningsGrowth")), "opm": _pct(info.get("operatingMargins")),
        "net_debt_ebitda": nde, "debt": debt, "cash": cash, "fcf": num(info.get("freeCashflow")), "ocf": num(info.get("operatingCashflow")),
        "rev": num(info.get("totalRevenue")), "tgt": tgt, "next_earn": raw.get("next_earn") or None, "annual": list(raw.get("annual") or []),
    }
