"""주식 분석 — 발굴 관점 채점(순수, 설계서 §5.3). 걸린 날 종가 대비 N거래일 뒤 수익률을 지수와 견준다.

종가는 배당을 뺀 값이다(화면에 "배당 제외"라고 적는다). 잴 자료가 없는 것은 세지 않는다.
기록(history)은 누구나 쓸 수 있는 곳에서 읽어 오므로 모양이 틀려도 죽지 않고, 기록을 돌려줄 때마다 정리한다.
"""
from __future__ import annotations

import math
import re

HORIZONS = {"1w": 5, "1m": 21, "3m": 63}
KEEP_DAYS = 300
LENS_IDS = ["value", "growth", "event", "flow"]
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _clean_hits(hits) -> dict:
    """관점 id 만, 값은 문자열 목록(중복 뺌)만 남긴다. 문자열 하나("AB")를 종목 목록으로 읽지 않는다."""
    if not isinstance(hits, dict):
        return {}
    return {k: list(dict.fromkeys(t for t in hits[k] if isinstance(t, str))) for k in LENS_IDS if isinstance(hits.get(k), list)}


def merge_history(history: dict | None, date: str, hits: dict) -> dict:
    raw = history.get("days") if isinstance(history, dict) else None
    days = {d: _clean_hits(h) for d, h in raw.items() if isinstance(d, str) and _DAY.match(d) and d <= date and isinstance(h, dict)} if isinstance(raw, dict) else {}
    days[date] = _clean_hits(hits)
    return {"days": {d: days[d] for d in sorted(days)[-KEEP_DAYS:]}}


def _num(x) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def _rows(rows) -> list:
    """[(날짜, 종가 또는 None)] — 모양이 틀린 줄은 버린다. 종가가 비어도 줄은 남겨 거래일 세는 자리를 지킨다."""
    if not isinstance(rows, (list, tuple)):
        return []
    return [(r[0], _num(r[1])) for r in rows if isinstance(r, (list, tuple)) and len(r) == 2 and isinstance(r[0], str)]


def score_lenses(history: dict, closes: dict, index: list) -> dict:
    """관점·기간별 {n, days, avg, win}. 종목은 지수와 같은 두 날짜(걸린 날, 지수 N거래일 뒤 날짜)로 잰다."""
    idx = _rows(index)
    ipos = {d: i for i, (d, _) in enumerate(idx)}
    series = {t: dict(_rows(rows)) for t, rows in closes.items() if isinstance(t, str)} if isinstance(closes, dict) else {}
    raw = history.get("days") if isinstance(history, dict) else None
    days = raw if isinstance(raw, dict) else {}
    out = {}
    for lens in LENS_IDS:
        out[lens] = {}
        for name, h in HORIZONS.items():
            ex, hit_days = [], set()
            for day, hits in days.items():
                i = ipos.get(day)
                if i is None or i + h >= len(idx) or not isinstance(hits, dict) or not isinstance(hits.get(lens), list):
                    continue
                tday, i0, i1 = idx[i + h][0], idx[i][1], idx[i + h][1]
                if not i0 or i1 is None:
                    continue
                base = i1 / i0 - 1
                for t in sorted({t for t in hits[lens] if isinstance(t, str)}):
                    c0, c1 = series.get(t, {}).get(day), series.get(t, {}).get(tday)
                    if c0 and c1 is not None:
                        ex.append((c1 / c0 - 1 - base) * 100)
                        hit_days.add(day)
            out[lens][name] = ({"n": len(ex), "days": len(hit_days), "avg": round(sum(ex) / len(ex), 2), "win": round(sum(1 for x in ex if x > 0) / len(ex) * 100, 1)}
                               if ex else {"n": 0, "days": 0, "avg": None, "win": None})
    return out
