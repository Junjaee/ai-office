"""주식 분석 — 국내 종목 원자료. 야후 파이낸스의 국내 표기(코드.KS = 코스피, 코드.KQ = 코스닥)로 받는다.

받는 일은 미국 쪽 fetch_raw 가 그대로 하고, 여기서는 거래소 접미사를 붙이고 키 몇 개만 국내 값으로 바꾼다.
"""
from __future__ import annotations

import analyst_sources_us as us

EXCHANGE = {"KS": "코스피", "KQ": "코스닥"}


def _try(code: str, exch: str, yf):
    raw = us.fetch_raw(f"{code}.{exch}", yf)
    return raw, exch


def fetch_raw_kr(code: str, meta: dict | None, yf=None) -> dict:
    """meta 에 거래소(KS|KQ)가 있으면 한 번만 부르고, 없으면 .KS 를 받아 보고 실패하면 .KQ."""
    meta = meta or {}
    known = meta.get("exch")
    if known:
        raw, exch = _try(code, known, yf)
    else:
        try:
            raw, exch = _try(code, "KS", yf)
        except Exception:  # noqa: BLE001 — 예외 내용엔 기호가 들어 있어 버리고 다른 거래소로
            raw, exch = _try(code, "KQ", yf)
    return {**raw, "t": code, "exchange": EXCHANGE.get(exch, ""), "name_local": meta.get("name"), "currency": "KRW"}
