"""주식 분석 — 발굴 관점 채점(순수, 설계서 §5.3). 걸린 날 종가 대비 N거래일 뒤 수익률을 지수와 견준다.

종가는 배당을 뺀 값이다(화면에 "배당 제외"라고 적는다). 잴 자료가 없는 것은 세지 않는다.
"""
from __future__ import annotations

HORIZONS = {"1w": 5, "1m": 21, "3m": 63}
KEEP_DAYS = 300
LENS_IDS = ["value", "growth", "event", "flow"]


def merge_history(history: dict | None, date: str, hits: dict) -> dict:
    days = dict(history["days"]) if isinstance(history, dict) and isinstance(history.get("days"), dict) else {}
    days[date] = {k: list(v) for k, v in (hits or {}).items()}
    return {"days": {d: days[d] for d in sorted(days)[-KEEP_DAYS:]}}


def _ret(pos: dict, values: list, day: str, h: int) -> float | None:
    i = pos.get(day)
    if i is None or i + h >= len(values) or not values[i]:
        return None
    return values[i + h] / values[i] - 1


def score_lenses(history: dict, closes: dict, index: list) -> dict:
    ipos = {d: i for i, (d, _) in enumerate(index)}
    ivals = [c for _, c in index]
    series = {t: ({d: i for i, (d, _) in enumerate(rows)}, [c for _, c in rows]) for t, rows in closes.items()}
    out = {}
    for lens in LENS_IDS:
        out[lens] = {}
        for name, h in HORIZONS.items():
            ex = []
            for day, hits in ((history or {}).get("days") or {}).items():
                if not isinstance(hits, dict):
                    continue
                base = _ret(ipos, ivals, day, h)
                if base is None:
                    continue
                for t in hits.get(lens) or []:
                    if t in series:
                        r = _ret(series[t][0], series[t][1], day, h)
                        if r is not None:
                            ex.append((r - base) * 100)
            out[lens][name] = {"n": len(ex), "avg": round(sum(ex) / len(ex), 2), "win": round(sum(1 for x in ex if x > 0) / len(ex) * 100, 1)} if ex else {"n": 0, "avg": None, "win": None}
    return out
