"""호가 스냅샷 대상 고르기 — '세력이 움직일 수 있는 크기' 의 종목만, 두 층으로.

근거(14번 연구 자료, 2024~2026 사건 A 3,239건): 사건 종목 시총 중앙값 1,154억, 10%~90% 구간 293억~1조 2천억, 5천억 미만이 82%.
 시총 5천억 이상에서 난 18% 는 삼성전자·하이닉스처럼 시장 전체가 움직인 것이라 '세력' 과 무관 → 제외.
조회 한도(약 0.67건/초)에서 한 바퀴에 넣을 수 있는 종목이 5분에 200개 정도라, 두 층으로 나눈다:
 - A층(매 바퀴): 관심 종목(kis_watchlist) + 후보 파일(세력 흔적 신호) + 시총 범위 안 거래대금 상위 → 기본 150개
 - B층(돌려 가며): 시총 범위 안 나머지 종목을 남는 예산만큼 이어 붙여 몇 바퀴에 한 번씩 훑는다
자료는 네이버 종목 목록(시가총액·거래대금·거래정지 여부) 하나로 정한다. 보통주만(코드 끝 0, 스팩 제외), 거래정지 제외, 주가 하한(기본 500원) 적용.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

LIST_URL = "https://m.stock.naver.com/api/stocks/marketValue/{market}?page={page}&pageSize=100"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.stock.naver.com/"}
CODE_RE = re.compile(r"^\d{6}$")
EOK = 1e8


def _num(s) -> float:
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def fetch_listing(pages_per_market: int = 30, sleep: float = 0.15) -> list[dict]:
    """네이버 목록 전 페이지 → [{code, name, market, mcap(원), amount(원), price, halted}] (보통주만)."""
    rows = []
    for market in ("KOSPI", "KOSDAQ"):
        for page in range(1, pages_per_market + 1):
            j = None
            for _ in range(3):
                try:
                    r = requests.get(LIST_URL.format(market=market, page=page), headers=HEADERS, timeout=15)
                    if r.status_code == 200:
                        j = r.json(); break
                except (requests.RequestException, ValueError):
                    pass
                time.sleep(2)
            if j is None:
                break
            stocks = j.get("stocks", [])
            for s in stocks:
                if s.get("stockEndType") != "stock":
                    continue
                code = str(s.get("itemCode", "")).zfill(6); name = s.get("stockName", "")
                if not CODE_RE.match(code) or not code.endswith("0") or "스팩" in name:
                    continue
                rows.append({"code": code, "name": name, "market": market, "mcap": _num(s.get("marketValueRaw")), "amount": _num(s.get("accumulatedTradingValueRaw")),
                             "price": _num(s.get("closePriceRaw")), "halted": (s.get("tradeStopType") or {}).get("name", "") == "HALTED"})
            if not stocks or page * 100 >= int(j.get("totalCount", 0)):
                break
            time.sleep(sleep)
    seen: set[str] = set()
    uniq = []
    for r in rows:                      # 페이지 사이에 순위가 바뀌면 같은 종목이 두 번 올 수 있다
        if r["code"] not in seen:
            seen.add(r["code"]); uniq.append(r)
    return uniq


@dataclass
class Universe:
    tier_a: list[str]
    tier_b: list[str]
    excluded: dict = field(default_factory=dict)   # 사유 → 종목 수

    def sweep_plan(self, cycle_sec: float, interval: float, sweep_no: int) -> list[str]:
        """이번 바퀴에 조회할 종목: A층 전부 + 남는 예산만큼 B층을 돌려 가며."""
        budget = max(len(self.tier_a), int(cycle_sec / interval))
        room = max(0, budget - len(self.tier_a))
        if not self.tier_b or room == 0:
            return list(self.tier_a)
        start = (sweep_no * room) % len(self.tier_b)
        chunk = [self.tier_b[(start + i) % len(self.tier_b)] for i in range(min(room, len(self.tier_b)))]
        return list(self.tier_a) + chunk


def build_universe(listing: list[dict], watchlist: list[str], candidates: list[str], tier_a_size: int = 150,
                   cap_min_eok: float = 300, cap_max_eok: float = 5000, price_min: float = 500) -> Universe:
    ex = {"거래정지": 0, "시총 범위 밖": 0, "주가 하한": 0}
    pool: list[dict] = []
    for r in listing:
        if r["halted"]:
            ex["거래정지"] += 1; continue
        if not (cap_min_eok * EOK <= r["mcap"] < cap_max_eok * EOK):
            ex["시총 범위 밖"] += 1; continue
        if r["price"] < price_min:
            ex["주가 하한"] += 1; continue
        pool.append(r)
    pool_codes = {r["code"] for r in pool}
    tier_a: list[str] = []
    for c in list(watchlist) + list(candidates):
        if c not in tier_a and CODE_RE.match(c):
            tier_a.append(c)                       # 관심·후보 종목은 시총 범위와 무관하게 A층
    for r in sorted(pool, key=lambda x: -x["amount"]):
        if len(tier_a) >= tier_a_size:
            break
        if r["code"] not in tier_a:
            tier_a.append(r["code"])
    tier_b = [r["code"] for r in sorted(pool, key=lambda x: -x["amount"]) if r["code"] not in set(tier_a)]
    return Universe(tier_a, tier_b, {**ex, "A층": len(tier_a), "B층": len(tier_b), "범위 안 종목": len(pool_codes)})


def load_lines(path: str | Path | None) -> list[str]:
    if not path or not Path(path).exists():
        return []
    return [ln.strip() for ln in Path(path).read_text(encoding="utf-8").splitlines() if CODE_RE.match(ln.strip())]
