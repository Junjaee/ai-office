"""한국투자증권 REST 조회 공통 — 접근토큰 캐시, 호출 간격 제한, 재시도, 오류 분류.

- 토큰: POST /oauth2/tokenP. 24시간 유효. %LOCALAPPDATA%\\kis-record\\token.json 에 만료 시각과 함께 저장해 재사용한다
  (한투는 1분에 1회만 발급해 주고, 6시간 안 재발급은 같은 토큰을 준다). 값은 로그·오류 문구에 넣지 않는다.
- 한도: 문서상 실전 1초 20건이지만 2026-09-28 실측(백필 멈춘 상태, 간격별 30회): 간격 2.0·1.5초 → 초과 0회·응답 0.08초, 1.2초 → 6회, 1.0초 → 3회,
  0.8초 → 15회(응답 1.2초로 느려짐). 즉 이 계정은 **약 1.5초에 1건(0.67건/초)** 이 안전선이다. 기본 간격 1.5초, 초과 오류가 오면 1.5초 쉬고 다시. 한도가 풀리면 --interval 을 줄인다.
- 세션은 한 프로세스에서 하나만 쓰고(호출 순서 보장), 여러 프로세스가 같은 계좌를 동시에 두드리지 않는다(한도는 계좌 단위).
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Callable

import requests

REST_URL = "https://openapi.koreainvestment.com:9443"
TOKEN_FILE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "kis-record" / "token.json"
PATH_ASKING = "/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"   # 주식현재가 호가/예상체결 [FHKST01010200]
PATH_MINUTES = "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice"  # 주식일별분봉조회 [FHKST03010230], 1년 보관
TR_ASKING, TR_MINUTES = "FHKST01010200", "FHKST03010230"
RATE_LIMIT_CODE = "EGW00201"          # 초당 거래건수 초과
TOKEN_ERROR_CODES = {"EGW00123", "EGW00121"}   # 토큰 만료·유효하지 않음


class KISError(RuntimeError):
    pass


def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class Session:
    def __init__(self, interval: float = 1.5, log: Callable[[str], None] = print, token_file: Path = TOKEN_FILE, timeout: float = 20.0, http=None):
        self.app_key = os.environ["KIS_APP_KEY"]
        self.app_secret = os.environ["KIS_APP_SECRET"]
        self.interval = interval
        self.log = log
        self.token_file = Path(token_file)
        self.timeout = timeout
        self.http = http or requests.Session()      # 시험에서 가짜 세션을 끼울 수 있게
        self.last_call = 0.0
        self.calls = 0
        self.rate_hits = 0
        self.retries = 0
        self.token = self._load_token() or self._issue_token()

    # ---------------- 토큰
    def _load_token(self) -> str | None:
        try:
            d = json.loads(self.token_file.read_text(encoding="utf-8"))
            if d.get("expired", "") > _now_str() and d.get("access_token"):
                return d["access_token"]
        except (OSError, ValueError):
            pass
        return None

    def _issue_token(self) -> str:
        try:
            r = self.http.post(f"{REST_URL}/oauth2/tokenP", timeout=self.timeout,
                               json={"grant_type": "client_credentials", "appkey": self.app_key, "appsecret": self.app_secret})
        except requests.RequestException as exc:
            raise KISError(f"토큰 발급 실패: {type(exc).__name__}") from None
        if r.status_code != 200:
            raise KISError(f"토큰 발급 실패: HTTP {r.status_code}")
        d = r.json()
        tok = d.get("access_token")
        if not tok:
            raise KISError("토큰 발급 실패: access_token 없음")
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(json.dumps({"access_token": tok, "expired": d.get("access_token_token_expired", "")}), encoding="utf-8")
        self.log("접근토큰 발급")
        return tok

    def _headers(self, tr_id: str) -> dict:
        return {"authorization": f"Bearer {self.token}", "appkey": self.app_key, "appsecret": self.app_secret, "tr_id": tr_id, "custtype": "P"}

    # ---------------- 호출
    def _wait(self) -> None:
        gap = self.interval - (time.time() - self.last_call)
        if gap > 0:
            time.sleep(gap)
        self.last_call = time.time()

    def get(self, path: str, tr_id: str, params: dict, retries: int = 4) -> dict:
        """조회 하나. rt_cd=0 인 응답 JSON 을 돌려준다. 한도 초과·5xx·토큰 만료는 재시도, 그 밖은 KISError."""
        last = ""
        for attempt in range(retries):
            self._wait()
            self.calls += 1
            try:
                r = self.http.get(f"{REST_URL}{path}", headers=self._headers(tr_id), params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last = type(exc).__name__
                self.retries += 1
                time.sleep(2.0 * (attempt + 1))
                continue
            try:
                j = r.json()
            except ValueError:
                j = {}
            code = str(j.get("msg_cd", ""))
            if r.status_code == 200 and j.get("rt_cd") == "0":
                return j
            if code == RATE_LIMIT_CODE or r.status_code == 429:
                self.rate_hits += 1
                self.retries += 1
                time.sleep(1.5 * (attempt + 1))
                continue
            if code in TOKEN_ERROR_CODES or r.status_code == 401:
                self.token = self._issue_token()
                self.retries += 1
                continue
            if r.status_code >= 500:
                self.retries += 1
                last = f"HTTP {r.status_code} {code}"
                time.sleep(2.0 * (attempt + 1))
                continue
            msg = re.sub(r"[^가-힣A-Za-z0-9 _]", "", str(j.get("msg1", "")))[:40]
            raise KISError(f"조회 거절 {tr_id} {code} {msg}")
        raise KISError(f"조회 실패 {tr_id}: {last or '재시도 초과'}")

    # ---------------- 편의 함수
    def asking_price(self, code: str) -> dict:
        """호가 10단계·잔량·예상체결(output1, 71개 항목)."""
        return self.get(PATH_ASKING, TR_ASKING, {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}).get("output1", {})

    def minutes(self, code: str, date: str, hour: str = "153000") -> list[dict]:
        """date(YYYYMMDD) 의 hour(HHMMSS) 이전 1분봉 최대 120개(최근 것부터). 열: stck_bsop_date·stck_cntg_hour·stck_prpr·stck_oprc·stck_hgpr·stck_lwpr·cntg_vol·acml_tr_pbmn."""
        j = self.get(PATH_MINUTES, TR_MINUTES, {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code, "FID_INPUT_HOUR_1": hour,
                                                 "FID_INPUT_DATE_1": date, "FID_PW_DATA_INCU_YN": "N", "FID_FAKE_TICK_INCU_YN": "N"})
        return [row for row in (j.get("output2") or []) if row.get("stck_bsop_date")]

    def day_minutes(self, code: str, date: str) -> list[dict]:
        """하루 전체 1분봉(09:00~15:30, 약 381개). 15:30 부터 120개씩 거슬러 부른다(보통 4회). 날짜가 다른 행(휴장이면 전 거래일)은 버린다."""
        out: list[dict] = []
        hour = "153000"
        for _ in range(6):
            rows = self.minutes(code, date, hour)
            rows = [r for r in rows if r["stck_bsop_date"] == date]
            if not rows:
                break
            out.extend(rows)
            earliest = min(r["stck_cntg_hour"] for r in rows)
            if earliest <= "090000" or len(rows) < 100:
                break
            hh, mm = int(earliest[:2]), int(earliest[2:4]) - 1
            if mm < 0:
                hh, mm = hh - 1, 59
            hour = f"{hh:02d}{mm:02d}00"
        seen = set()
        uniq = []
        for r in out:
            if r["stck_cntg_hour"] not in seen:
                seen.add(r["stck_cntg_hour"]); uniq.append(r)
        return sorted(uniq, key=lambda r: r["stck_cntg_hour"])
