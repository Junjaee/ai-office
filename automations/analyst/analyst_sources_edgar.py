"""주식 분석 — 미국 증권거래위원회(EDGAR)에서 종목별 최근 제출 목록을 받는다(무료, 인증키 없음).

EDGAR 는 누가 부르는지(이름·이메일) User-Agent 에 적으라고 요구하고 1초에 10번까지만 받는다.
문구는 환경변수 SEC_USER_AGENT 로 받는다(github 가 든 문구는 막는다). 기호→CIK 표는 한 번 받아 둔다.
실패는 예외로 올린다 — run_analyst 가 세고, 공시 없이 계속한다.
"""
from __future__ import annotations

import time

import requests

TIMEOUT = 20


class Edgar:
    def __init__(self, http=requests, delay: float = 0.12, user_agent: str = ""):
        self.http, self.delay, self._cik = http, delay, None
        self.headers = {"User-Agent": user_agent}

    def _map(self) -> dict[str, int]:
        if self._cik is None:
            r = self.http.get("https://www.sec.gov/files/company_tickers.json", headers=self.headers, timeout=TIMEOUT)
            r.raise_for_status()
            self._cik = {str(v["ticker"]).upper(): int(v["cik_str"]) for v in r.json().values()}
        return self._cik

    def filings(self, ticker: str, since: str) -> list[dict]:
        cik = self._map().get(ticker.upper())
        if cik is None:
            return []
        if self.delay:
            time.sleep(self.delay)
        r = self.http.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", headers=self.headers, timeout=TIMEOUT)
        r.raise_for_status()
        rec = (r.json().get("filings") or {}).get("recent") or {}
        rows = zip(rec.get("form") or [], rec.get("filingDate") or [], rec.get("items") or [])
        return [{"form": f, "date": d, "items": i or ""} for f, d, i in rows if d >= since]
