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

    def watch(self, market: str) -> list[str]:
        r = self.http.get(f"{self.base}/api/stock", params={"market": market, "view": "watch"}, timeout=TIMEOUT)
        r.raise_for_status()
        return list(r.json().get("watch") or [])

    def ingest(self, market: str, kind: str, doc: dict, ticker: str | None = None, date: str | None = None) -> None:
        body = {"market": market, "kind": kind, "doc": doc}
        if ticker:
            body["ticker"] = ticker
        if date:
            body["date"] = date
        url = f"{self.base}/api/stock/ingest"
        try:
            r = self.http.post(url, json=body, headers=self._headers(), timeout=TIMEOUT)
        except OSError:   # requests 의 연결·시간 초과 예외도 OSError 의 한 갈래
            r = None
        if r is not None and r.status_code < 500:
            r.raise_for_status()   # 4xx 는 다시 보내도 같다 — 바로 올린다
            return
        self.sleep(RETRY_WAIT)
        self.http.post(url, json=body, headers=self._headers(), timeout=TIMEOUT).raise_for_status()
