"""주식 분석 — 미국 공시(8-K)를 항목 번호로 분류한다(순수). 내용은 읽지 않는다 — 종류와 날짜만(설계서 §4.4)."""
from __future__ import annotations

from datetime import date, timedelta

# 8-K 항목 번호 → 화면에 보일 사건 종류. 여기 없는 번호(7.01 공시 규정, 9.01 첨부 등)는 버린다.
ITEM_KIND = {
    "1.01": "주요 계약", "1.03": "파산·회생", "2.01": "인수·매각 완료", "2.02": "실적 발표", "2.05": "구조조정", "2.06": "자산 손상",
    "3.01": "상장 유지 경고", "3.02": "주식 발행(자금 조달)", "4.01": "감사인 교체", "4.02": "재무제표 정정", "5.01": "지배권 변경", "5.02": "임원 교체",
}


def classify(filings: list[dict], as_of: str, days: int = 14) -> list[dict]:
    """as_of 를 포함해 최근 days 일 안의 8-K 를 사건 목록으로. 최근 것부터, 같은 날 같은 종류는 하나."""
    lo = (date.fromisoformat(as_of) - timedelta(days=days)).isoformat()
    seen, out = set(), []
    for f in filings or []:
        if not isinstance(f, dict) or not str(f.get("form") or "").startswith("8-K"):
            continue
        d = str(f.get("date") or "")
        if not (lo <= d <= as_of):
            continue
        for item in str(f.get("items") or "").split(","):
            kind = ITEM_KIND.get(item.strip())
            if kind and (d, kind) not in seen:
                seen.add((d, kind))
                out.append({"date": d, "kind": kind})
    return sorted(out, key=lambda e: e["date"], reverse=True)  # 안정 정렬 — 같은 날은 적힌 순서
