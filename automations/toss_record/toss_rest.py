"""토스증권 Open API REST 공통 — 토큰(클라이언트당 1개, 파일로 공유), 유량(응답 헤더 X-RateLimit-*), 재시도, 시세 편의 함수.

- 문서: https://openapi.tossinvest.com/openapi-docs/overview.md , 명세 https://openapi.tossinvest.com/openapi-docs/latest/openapi.json (2026-09-29 확인)
- 토큰: POST /oauth2/token (form, client_credentials). **클라이언트당 유효 토큰 1개** — 새로 발급하면 이전 토큰이 즉시 무효(401 token-revoked).
  그래서 모든 프로세스가 %LOCALAPPDATA%\\toss-record\\token.json 하나를 공유하고, 만료 60초 전이나 401 일 때만 재발급한다(재발급 직전에 파일을 다시 읽어 다른 프로세스가 먼저 갱신했으면 그것을 쓴다).
- 유량: 그룹별 초당 한도(MARKET_DATA 15, MARKET_DATA_CHART 20, AUTH 5). 성공 응답에도 X-RateLimit-Remaining 이 오므로 0 이면 X-RateLimit-Reset 초만큼 쉰다. 429 면 Retry-After.
- 허용 IP: WTS 설정 > Open API 에 등록한 IP 에서만 됨(아니면 403). IP 가 바뀌면 다시 등록.
- 값(client_id·secret·토큰)은 로그·오류 문구에 넣지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Callable

import requests

REST_URL = "https://openapi.tossinvest.com"
WS_URL = "wss://openapi-ws.tossinvest.com/ws/v1"
DEFAULT_OUT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "toss-record"
TOKEN_FILE = DEFAULT_OUT / "token.json"
GROUP_RATE = {"MARKET_DATA": 15, "MARKET_DATA_CHART": 20, "AUTH": 5, "ACCOUNT": 1, "ASSET": 5}
HISTORY_START_KR = "2022-11-23"        # FAQ: 국내 과거 시세 제공 시작일


class TossError(RuntimeError):
    pass


def load_secrets(cfg_path: str | Path) -> None:
    """config.yaml 의 toss_client_id·toss_client_secret 을 환경변수로(값은 돌려주지도 찍지도 않는다). 형식만 검사."""
    import yaml
    data = yaml.load(Path(cfg_path).read_text(encoding="utf-8"), Loader=yaml.BaseLoader) or {}
    for key, env, min_len in (("toss_client_id", "TOSS_CLIENT_ID", 16), ("toss_client_secret", "TOSS_CLIENT_SECRET", 24)):
        v = str(data.get(key, "") or "").strip().strip('"').strip("'")
        if not v or v.startswith("여기에"):
            raise SystemExit(f"config.yaml 의 {key} 가 비어 있습니다 — 토스증권 WTS 설정 > Open API 에서 발급한 값을 넣어 주세요")
        if len(v) < min_len or not re.fullmatch(r"[A-Za-z0-9+/=_\-.]+", v):
            raise SystemExit(f"config.yaml 의 {key} 형식이 이상합니다(길이 {len(v)}) — 앞뒤 공백·줄바꿈을 확인해 주세요")
        os.environ[env] = v


class Session:
    def __init__(self, log: Callable[[str], None] = print, token_file: Path = TOKEN_FILE, timeout: float = 20.0, http=None):
        self.client_id = os.environ["TOSS_CLIENT_ID"]
        self.client_secret = os.environ["TOSS_CLIENT_SECRET"]
        self.log = log
        self.token_file = Path(token_file)
        self.timeout = timeout
        self.http = http or requests.Session()
        self.calls = 0
        self.rate_hits = 0
        self.retries = 0
        self.last_call: dict[str, float] = {}
        self.token = self._load_token() or self._issue_token()

    # ---------------- 토큰
    def _load_token(self) -> str | None:
        try:
            d = json.loads(self.token_file.read_text(encoding="utf-8"))
            if float(d.get("expires_at", 0)) - 60 > time.time() and d.get("access_token"):
                return d["access_token"]
        except (OSError, ValueError):
            pass
        return None

    def _issue_token(self) -> str:
        fresh = self._load_token()
        if fresh and fresh != getattr(self, "token", None):
            return fresh                      # 다른 프로세스가 방금 갱신했으면 그것을 쓴다(내 재발급이 그 토큰을 무효화하지 않게)
        try:
            r = self.http.post(f"{REST_URL}/oauth2/token", timeout=self.timeout,
                               data={"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.client_secret},
                               headers={"Content-Type": "application/x-www-form-urlencoded"})
        except requests.RequestException as exc:
            raise TossError(f"토큰 발급 실패: {type(exc).__name__}") from None
        if r.status_code != 200:
            hint = ""
            try:
                hint = str(r.json().get("error", ""))[:60]
            except ValueError:
                pass
            raise TossError(f"토큰 발급 실패: HTTP {r.status_code} {re.sub(r'[^A-Za-z_ :]', '', hint)}")
        d = r.json()
        tok = d.get("access_token")
        if not tok:
            raise TossError("토큰 발급 실패: access_token 없음")
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(json.dumps({"access_token": tok, "expires_at": time.time() + int(d.get("expires_in", 3600))}), encoding="utf-8")
        self.log(f"토큰 발급(유효 {int(d.get('expires_in', 0))//60}분)")
        return tok

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    # ---------------- 호출
    def _pace(self, group: str) -> None:
        gap = 1.0 / GROUP_RATE.get(group, 5) - (time.time() - self.last_call.get(group, 0.0))
        if gap > 0:
            time.sleep(gap)
        self.last_call[group] = time.time()

    def get(self, path: str, params: dict | None = None, group: str = "MARKET_DATA", retries: int = 5):
        """조회 하나 → result 페이로드. 429·5xx·401(토큰) 은 재시도, 그 밖 4xx 는 TossError(code)."""
        last = ""
        for attempt in range(retries):
            self._pace(group)
            self.calls += 1
            try:
                r = self.http.get(f"{REST_URL}{path}", headers=self._headers(), params=params or {}, timeout=self.timeout)
            except requests.RequestException as exc:
                last = type(exc).__name__; self.retries += 1
                time.sleep(1.5 * (attempt + 1)); continue
            try:
                remaining = int(r.headers.get("X-RateLimit-Remaining", "1"))
                if remaining <= 0:
                    time.sleep(max(0.05, float(r.headers.get("X-RateLimit-Reset", "1"))))
            except ValueError:
                pass
            if r.status_code == 200:
                try:
                    return r.json().get("result")
                except ValueError:
                    raise TossError(f"응답 해석 실패 {path}") from None
            if r.status_code == 429:
                self.rate_hits += 1; self.retries += 1
                time.sleep(float(r.headers.get("Retry-After", "1")) + 0.2 * attempt); continue
            code = ""
            try:
                code = str(r.json().get("error", {}).get("code", ""))
            except ValueError:
                pass
            if r.status_code == 401:
                self.retries += 1
                self.token = self._issue_token(); continue
            if r.status_code >= 500:
                self.retries += 1; last = f"HTTP {r.status_code} {code}"
                time.sleep(2.0 * (attempt + 1)); continue
            if r.status_code == 403:
                raise TossError(f"403 {code or 'forbidden'} — 허용 IP 미등록일 수 있음(WTS 설정 > Open API)")
            raise TossError(f"조회 거절 {path} HTTP {r.status_code} {re.sub(r'[^A-Za-z0-9_-]', '', code)[:40]}")
        raise TossError(f"조회 실패 {path}: {last or '재시도 초과'}")

    # ---------------- 시세 편의 함수
    def orderbook(self, symbol: str) -> dict:
        """{timestamp, currency, asks:[{price,volume}...](낮은 가격순), bids:[...](높은 가격순)} — KRX+NXT 통합 호가."""
        return self.get("/api/v1/orderbook", {"symbol": symbol}) or {}

    def prices(self, symbols: list[str]) -> list[dict]:
        """현재가 다건(최대 200)."""
        return self.get("/api/v1/prices", {"symbols": ",".join(symbols[:200])}) or []

    def trades(self, symbol: str, count: int = 50) -> list[dict]:
        """당일 최근 체결(최대 50, 과거 페이지 없음)."""
        return self.get("/api/v1/trades", {"symbol": symbol, "count": count}) or []

    def candles(self, symbol: str, interval: str = "1m", count: int = 200, before: str | None = None, adjusted: bool | None = None) -> dict:
        """{candles:[{timestamp,openPrice,highPrice,lowPrice,closePrice,volume,currency}...] 최신순, nextBefore}."""
        p = {"symbol": symbol, "interval": interval, "count": count}
        if before:
            p["before"] = before
        if adjusted is not None:
            p["adjusted"] = "true" if adjusted else "false"
        return self.get("/api/v1/candles", p, group="MARKET_DATA_CHART") or {}

    def candles_all(self, symbol: str, interval: str = "1m", since: str | None = None, adjusted: bool | None = None, max_calls: int = 400) -> list[dict]:
        """과거 방향으로 페이지를 이어 받는다. since(ISO 날짜) 보다 오래된 봉이 나오면 멈춘다. 오래된 것 → 최신 순으로 돌려준다."""
        out: list[dict] = []
        before = None
        for _ in range(max_calls):
            d = self.candles(symbol, interval, 200, before, adjusted)
            rows = d.get("candles") or []
            if not rows:
                break
            out.extend(rows)
            before = d.get("nextBefore")
            if not before or (since and rows[-1]["timestamp"][:10] < since):
                break
        if since:
            out = [r for r in out if r["timestamp"][:10] >= since]
        seen = set(); uniq = []
        for r in out:
            if r["timestamp"] not in seen:
                seen.add(r["timestamp"]); uniq.append(r)
        return sorted(uniq, key=lambda r: r["timestamp"])

    def daily_series(self, symbol: str, kind: str, count: int = 100, until: str | None = None) -> dict:
        """kind: investor-trading | program-trades | short-selling | credit-trades | securities-lending → {records:[...최신순], nextUntil}."""
        p: dict[str, str | int] = {"count": count}
        if until:
            p["until"] = until
        return self.get(f"/api/v1/stocks/{symbol}/{kind}", p) or {}

    def daily_series_all(self, symbol: str, kind: str, since: str | None = None, max_calls: int = 200) -> list[dict]:
        out: list[dict] = []
        until = None
        for _ in range(max_calls):
            d = self.daily_series(symbol, kind, 100, until)
            rows = d.get("records") or []
            if not rows:
                break
            out.extend(rows)
            until = d.get("nextUntil")
            if not until or (since and rows[-1]["date"] < since):
                break
        if since:
            out = [r for r in out if r["date"] >= since]
        return sorted({r["date"]: r for r in out}.values(), key=lambda r: r["date"])

    def stocks_all(self, market: str = "KOSPI", common_only: bool = True, security_type: str | None = "STOCK") -> list[dict]:
        p = {"market": market, "status": "ACTIVE"}
        if common_only:
            p["commonShare"] = "true"
        if security_type:
            p["securityType"] = security_type
        return self.get("/api/v1/stocks/all", p) or []
