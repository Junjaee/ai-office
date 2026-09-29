"""종목별 '평소' 기준값 — 토스 일봉 21개로 전일 종가·전일 고가·20일 최고가·20일 평균 거래대금(원)을 만든다.

'돈 몰림 점수'는 거래대금을 절대값이 아니라 그 종목의 평소(20일 평균)와 견주기 때문에 이 값이 필요하다. 장 시작 전에 한 번(초당 20건, 200종목 10초).
거래대금 = 종가 × 거래량(일봉에 거래대금이 없어 근사). 오늘 봉이 이미 있으면 뺀다.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Callable

KST = timezone(timedelta(hours=9))
SLOTS_PER_DAY = 78            # 정규장 6.5시간 = 5분 창 78개


def daily_refs(ses, codes: list[str], log: Callable[[str], None] = print, days: int = 20) -> dict[str, dict]:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    out: dict[str, dict] = {}
    errors = 0
    for c in codes:
        try:
            rows = ses.candles(c, "1d", days + 1).get("candles") or []
        except Exception:  # noqa: BLE001
            errors += 1
            continue
        rows = [r for r in rows if r.get("closePrice")]
        past = [r for r in rows if r["timestamp"][:10] < today][:days]      # 최신순 → 어제부터 20일
        if not past:
            continue
        try:
            closes = [float(r["closePrice"]) for r in past]
            highs = [float(r.get("highPrice") or r["closePrice"]) for r in past]
            amts = [float(r["closePrice"]) * float(r.get("volume") or 0) for r in past]
        except (TypeError, ValueError, KeyError):
            continue
        out[c] = {"prev_close": closes[0], "prev_high": highs[0], "high20": max(highs), "avg_amt20": sum(amts) / len(amts),
                  "avg_amt5": sum(amts) / len(amts) / SLOTS_PER_DAY, "days": len(past)}
    if errors:
        log(f"일봉 기준값 조회 실패 {errors}종목")
    return out
