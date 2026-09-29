"""오늘 녹음할 종목 고르기.

우선순위: (1) config.yaml 의 kis_watchlist(코드 목록, 따옴표로 감싼 6자리 문자열) → (2) 네이버 모바일 종목 목록에서 거래대금 상위.
- 아침 08:50 의 네이버 거래대금이 전날 값인지 당일 0 으로 초기화된 값인지 확실하지 않다(2026-09-28 미검증). 값이 전부 0 이면 거래대금 정렬을
  믿지 않고 어제 실행의 종목(가장 최근 summary.json) → 관심 종목 순으로 물러난다. 후보가 비면 예외.
- 한도(연결당 3건) 때문에 보통 2~3종목이다. 나중에 KRX Open API 나 14번 연구의 세력 흔적 지표로 바꿔 끼울 수 있게 함수 하나로 둔다.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests
import yaml

LIST_URL = "https://m.stock.naver.com/api/stocks/marketValue/{market}?page={page}&pageSize=100"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.stock.naver.com/"}
CODE_RE = re.compile(r"^\d{6}$")


def _num(s) -> float:
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def watchlist(cfg_path: str | Path) -> list[str]:
    """kis_watchlist 를 전부 문자열로 읽는다(BaseLoader — 005930 같은 값이 8진수 정수로 읽히는 사고 방지). 6자리가 아니면 거절."""
    data = yaml.load(Path(cfg_path).read_text(encoding="utf-8"), Loader=yaml.BaseLoader) or {}
    wl = data.get("kis_watchlist") or []
    if isinstance(wl, str):
        wl = [wl]
    out = []
    for c in wl:
        c = str(c).strip()
        if not CODE_RE.match(c):
            raise SystemExit(f"kis_watchlist 의 '{c}' 는 6자리 종목코드가 아닙니다 — 따옴표로 감싼 6자리(예 \"000660\")로 적어 주세요")
        out.append(c)
    return out


def _get(url: str, retries: int = 3):
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}"
        except (requests.RequestException, ValueError) as exc:
            last = type(exc).__name__
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"네이버 목록 실패: {last}")


def top_by_trading_value(n: int, pages_per_market: int = 8) -> list[str]:
    """거래대금 상위 n 종목(보통주, 거래정지 제외). 거래대금이 전부 0 이면 빈 목록(정렬 불가)."""
    rows = []
    for market in ("KOSPI", "KOSDAQ"):
        for page in range(1, pages_per_market + 1):
            j = _get(LIST_URL.format(market=market, page=page))
            stocks = j.get("stocks", [])
            for s in stocks:
                if s.get("stockEndType") != "stock":
                    continue
                code = str(s.get("itemCode", "")).zfill(6)
                if not CODE_RE.match(code) or not code.endswith("0") or "스팩" in s.get("stockName", ""):
                    continue
                if (s.get("tradeStopType") or {}).get("name", "") == "HALTED":
                    continue
                rows.append((code, _num(s.get("accumulatedTradingValueRaw"))))
            if not stocks or page * 100 >= int(j.get("totalCount", 0)):
                break
            time.sleep(0.2)
    if not rows or max(v for _, v in rows) <= 0:
        return []
    rows.sort(key=lambda x: -x[1])
    return [c for c, _ in rows[:n]]


def yesterday_codes(out_dir: Path | None) -> list[str]:
    """가장 최근 실행의 summary.json 에 적힌 종목."""
    if out_dir is None or not out_dir.exists():
        return []
    files = sorted(out_dir.glob("*/run_*/summary.json"))
    if not files:
        return []
    try:
        return [c for c in json.loads(files[-1].read_text(encoding="utf-8")).get("codes", []) if CODE_RE.match(str(c))]
    except (ValueError, OSError):
        return []


def today_picks(cfg_path: str | Path, limit: int = 3, log=print, out_dir: Path | None = None) -> list[str]:
    picks = watchlist(cfg_path)[:limit]
    source = ["관심 종목"] if picks else []
    if len(picks) < limit:
        try:
            top = top_by_trading_value(limit * 2)
        except RuntimeError as exc:
            log(f"{exc} — 어제 종목·관심 종목으로 대체"); top = []
        if not top:
            top = yesterday_codes(out_dir)
            if top:
                source.append("어제 종목")
        else:
            source.append("거래대금 상위")
        for c in top:
            if c not in picks:
                picks.append(c)
            if len(picks) >= limit:
                break
    if not picks:
        raise SystemExit("녹음할 종목을 정하지 못했습니다 — config.yaml 에 kis_watchlist 를 적어 주세요")
    log(f"종목 선택 근거: {' + '.join(source)}")
    return picks


if __name__ == "__main__":
    import sys
    cfg = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[2] / "ai-home" / "02_주식신호" / "config.yaml")
    print(today_picks(cfg))
