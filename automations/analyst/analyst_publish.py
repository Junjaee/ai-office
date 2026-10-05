"""주식 분석 — AI 오피스 Worker(/api/stock)에서 관심 목록을 읽고 계산 결과를 보낸다."""
from __future__ import annotations

import time

import requests

TIMEOUT = 30
RETRY_WAIT = 2   # 보내기에 실패하면 이만큼(초) 쉬고 한 번만 다시 보낸다


class Site:
    def __init__(self, base_url: str, token: str = "", http=requests, sleep=time.sleep):
        self.base = base_url.rstrip("/")
        self.token = token or ""
        self.http = http
        self.sleep = sleep

    def _headers(self) -> dict:
        return {"X-Live-Token": self.token} if self.token else {}

    def _get(self, params: dict) -> dict:
        r = self.http.get(f"{self.base}/api/stock", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict):
        """보낸다. 연결 실패·5xx 면 잠깐 쉬고 한 번만 다시 보낸다. 4xx 는 바로 예외."""
        url = f"{self.base}{path}"
        try:
            r = self.http.post(url, json=body, headers=self._headers(), timeout=TIMEOUT)
        except OSError:   # requests 의 연결·시간 초과 예외도 OSError 의 한 갈래
            r = None
        if r is not None and r.status_code < 500:
            r.raise_for_status()   # 4xx 는 다시 보내도 같다 — 바로 올린다
            return r
        self.sleep(RETRY_WAIT)
        r = self.http.post(url, json=body, headers=self._headers(), timeout=TIMEOUT)
        r.raise_for_status()
        return r

    def watch(self, market: str) -> list[str]:
        return list(self._get({"market": market, "view": "watch"}).get("watch") or [])

    def get_view(self, market: str, view: str) -> dict:
        return self._get({"market": market, "view": view})

    def ticker(self, market: str, ticker: str) -> dict:
        return self._get({"market": market, "ticker": ticker})

    def ingest(self, market: str, kind: str, doc: dict, ticker: str | None = None, date: str | None = None) -> None:
        body = {"market": market, "kind": kind, "doc": doc}
        if ticker:
            body["ticker"] = ticker
        if date:
            body["date"] = date
        self._post("/api/stock/ingest", body)

    def opinion(self, market: str, ticker: str, opinion: dict) -> str:
        """해석 하나를 저장하고 서버가 붙인 id 를 돌려준다."""
        r = self._post("/api/stock/opinion", {"market": market, "ticker": ticker, "opinion": opinion})
        return r.json()["id"]
