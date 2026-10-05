"""주식 분석 — AI 오피스 Worker(/api/stock)에서 관심 목록을 읽고 계산 결과를 보낸다."""
from __future__ import annotations

import requests

TIMEOUT = 30


class Site:
    def __init__(self, base_url: str, token: str = "", http=requests):
        self.base = base_url.rstrip("/")
        self.token = token or ""
        self.http = http

    def _headers(self) -> dict:
        return {"X-Live-Token": self.token} if self.token else {}

    def watch(self, market: str) -> list[str]:
        r = self.http.get(f"{self.base}/api/stock", params={"market": market, "view": "watch"}, timeout=TIMEOUT)
        r.raise_for_status()
        return list(r.json().get("watch") or [])

    def ingest(self, market: str, kind: str, doc: dict, ticker: str | None = None) -> None:
        body = {"market": market, "kind": kind, "doc": doc}
        if ticker:
            body["ticker"] = ticker
        r = self.http.post(f"{self.base}/api/stock/ingest", json=body, headers=self._headers(), timeout=TIMEOUT)
        r.raise_for_status()
