"""사이트로 보내는 실시간 자료 — 녹음기가 받은 호가·체결을 종목별로 집계해 5초마다 /api/live 에 올린다(worker/live.ts, 화면 app/office/LiveBoard.tsx).

집계(종목마다, 창 = 최근 5분):
- 체결 방향: 체결가 ≥ 직전 매도1호가 → 매수(B), ≤ 직전 매수1호가 → 매도(S), 그 사이 → 중간(M). 토스 체결에 매수/매도 구분이 없어 이렇게 추정한다.
- 체결강도 = 매수 체결금액 ÷ 매도 체결금액 × 100. 잔량비 = 매수 총잔량 ÷ 매도 총잔량. 벽 = 10단계 중 금액(가격×잔량)이 가장 큰 호가.
- 벽 신호 = 5분 전 표본과 비교해 1~5호가 잔량이 3배 넘게 늘고 금액 3억 이상.
- 점수 = min(체결강도, 400)/100 + 벽 금액(억)/10 + 신호 2점 — 정렬용이지 예측값이 아니다.
보내는 문서: {ws, automation, task:"record", state, at, summary, started_at, board:{..., items:[...]}} (≤ 1MB, 종목 100개면 약 150KB).
"""
from __future__ import annotations

import json
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Callable

import requests

KST = timezone(timedelta(hours=9))
DEFAULT_LIVE_URL = "https://ai-office.smartjohn-d34.workers.dev/api/live"


def now_iso() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


class LiveBoard:
    def __init__(self, names: dict[str, str] | None = None, window_sec: int = 300, wall_mult: float = 3.0, wall_min_amt: float = 3e8, sample_sec: float = 5.0):
        self.names = names or {}
        self.window_ms = window_sec * 1000
        self.wall_mult = wall_mult; self.wall_min_amt = wall_min_amt; self.sample_ms = sample_sec * 1000
        self.book: dict[str, dict] = {}                      # code → {"ts","asks":[(p,v)..],"bids":[(p,v)..],"recv"}
        self.samples: dict[str, deque] = {}                  # code → deque[(recv_ms, asks, bids)] 5초마다 하나
        self.trades: dict[str, deque] = {}                   # code → deque[(recv_ms, ts, price, vol, side)]
        self.books = 0; self.trades_n = 0

    # ---------------- 수신
    def on_row(self, channel: str, code: str, row: dict) -> None:
        recv = int(time.time() * 1000)
        if channel.startswith("orderbook"):
            asks = [(_f(row.get(f"ask{i}_p")), _f(row.get(f"ask{i}_v"))) for i in range(1, 11) if row.get(f"ask{i}_p")]
            bids = [(_f(row.get(f"bid{i}_p")), _f(row.get(f"bid{i}_v"))) for i in range(1, 11) if row.get(f"bid{i}_p")]
            self.book[code] = {"ts": row.get("timestamp", ""), "asks": asks, "bids": bids, "recv": recv}
            dq = self.samples.setdefault(code, deque())
            if not dq or recv - dq[-1][0] >= self.sample_ms:
                dq.append((recv, asks, bids))
            self._trim(dq, recv)
            self.books += 1
        else:
            price = _f(row.get("price")); vol = _f(row.get("volume"))
            b = self.book.get(code)
            side = "M"
            if b and b["asks"] and b["bids"]:
                if price >= b["asks"][0][0]:
                    side = "B"
                elif price <= b["bids"][0][0]:
                    side = "S"
            dq = self.trades.setdefault(code, deque())
            dq.append((recv, row.get("timestamp", ""), price, vol, side))
            self._trim(dq, recv)
            self.trades_n += 1

    def _trim(self, dq: deque, recv: int) -> None:
        while dq and recv - dq[0][0] > self.window_ms:
            dq.popleft()

    # ---------------- 집계
    def item(self, code: str) -> dict:
        b = self.book.get(code); tr = self.trades.get(code, deque()); now = int(time.time() * 1000)
        self._trim(tr, now)
        buy = sum(p * v for _, _, p, v, s in tr if s == "B"); sell = sum(p * v for _, _, p, v, s in tr if s == "S")
        amt = sum(p * v for _, _, p, v, _ in tr)
        strength = round(buy / sell * 100, 1) if sell > 0 else (999.0 if buy > 0 else None)
        price = tr[-1][2] if tr else (b["bids"][0][0] if b and b["bids"] else (b["asks"][0][0] if b and b["asks"] else 0))
        ask_total = sum(v for _, v in b["asks"]) if b else 0; bid_total = sum(v for _, v in b["bids"]) if b else 0
        ratio = round(bid_total / ask_total, 2) if ask_total > 0 else None
        wall = None
        if b:
            cands = [("ask", i + 1, p, v, p * v) for i, (p, v) in enumerate(b["asks"])] + [("bid", i + 1, p, v, p * v) for i, (p, v) in enumerate(b["bids"])]
            if cands:
                side, lv, p, v, a = max(cands, key=lambda c: c[4])
                wall = {"side": side, "level": lv, "price": p, "amt": round(a / 1e8, 2)}
        event = ""
        smp = self.samples.get(code)
        if b and smp and len(smp) >= 2 and now - smp[0][0] >= self.window_ms * 0.8:
            _, asks0, bids0 = smp[0]
            for side, cur, old in (("매도", b["asks"], asks0), ("매수", b["bids"], bids0)):
                for i in range(min(5, len(cur), len(old))):
                    p1, v1 = cur[i]; v0 = old[i][1]
                    if v1 > self.wall_mult * max(v0, 1) and p1 * v1 >= self.wall_min_amt:
                        event = f"{side}{i+1}호가 벽 생김({p1*v1/1e8:.1f}억)"
                        break
                if event:
                    break
        score = round(min(strength or 0, 400) / 100 + (wall["amt"] / 10 if wall else 0) + (2 if event else 0), 2)
        return {
            "code": code, "name": self.names.get(code, code), "price": price, "strength": strength,
            "buy_amt": round(buy / 1e8, 3), "sell_amt": round(sell / 1e8, 3), "ratio": ratio, "ask_total": ask_total, "bid_total": bid_total,
            "amt": round(amt / 1e8, 2), "n_trades": len(tr), "score": score, "wall": wall, "event": event,
            "book": {"ts": b["ts"], "asks": [[f"{p:g}", f"{v:g}"] for p, v in b["asks"]], "bids": [[f"{p:g}", f"{v:g}"] for p, v in b["bids"]]} if b else None,
            "trades": [[ts, f"{p:g}", f"{v:g}", s] for _, ts, p, v, s in list(tr)[-20:]],
        }

    def board(self, codes: list[str], meta: dict) -> dict:
        items = [self.item(c) for c in codes]
        items.sort(key=lambda x: -x["score"])
        return {"at": now_iso(), "codes_n": len(codes), "books": self.books, "trades": self.trades_n, "window_sec": self.window_ms // 1000, **meta, "items": items}


class LivePoster:
    """/api/live 에 문서를 올린다. 실패는 세고 로그는 처음 몇 번만(토큰·주소는 찍지 않는다)."""

    def __init__(self, url: str, token: str, ws: str, automation: str, task: str, log: Callable[[str], None] = print, timeout: float = 8.0):
        self.url = url; self.token = token; self.ws = ws; self.automation = automation; self.task = task
        self.log = log; self.timeout = timeout
        self.sent = 0; self.failed = 0; self.last_error = ""
        self.http = requests.Session()

    def post(self, state: str, summary: str, board: dict | None = None, started_at: str | None = None, finished_at: str | None = None) -> bool:
        doc: dict[str, object] = {"ws": self.ws, "automation": self.automation, "task": self.task, "state": state, "at": now_iso(), "summary": summary}
        if started_at:
            doc["started_at"] = started_at
        if finished_at:
            doc["finished_at"] = finished_at
        if board is not None:
            doc["board"] = board
        try:
            headers = {"Content-Type": "application/json"}
            if self.token:
                headers["X-Live-Token"] = self.token
            r = self.http.post(self.url, data=json.dumps(doc, ensure_ascii=False).encode("utf-8"), headers=headers, timeout=self.timeout)
            if r.status_code == 200:
                self.sent += 1; return True
            self.failed += 1
            msg = f"HTTP {r.status_code}" + (" — 사이트의 LIVE_TOKEN 이 다르거나 없음" if r.status_code == 401 else " — 사이트가 아직 배포되지 않음" if r.status_code in (404, 503) else "")
        except requests.RequestException as exc:
            self.failed += 1; msg = type(exc).__name__
        if msg != self.last_error or self.failed in (1, 10, 100):
            self.log(f"실시간 전송 실패({self.failed}회): {msg}")
        self.last_error = msg
        return False


def live_settings(cfg_path) -> tuple[str, str] | None:
    """config.yaml 의 live_url(선택, 기본 운영 사이트)·live_token(선택 — 사이트에 LIVE_TOKEN 이 있을 때만 필요, 사용자 결정 2026-09-29 은 토큰 없이 운영).
    live_url 이 "off" 면 None(전송 안 함). 값은 돌려주되 찍지 않는다."""
    import yaml
    from pathlib import Path
    try:
        d = yaml.load(Path(cfg_path).read_text(encoding="utf-8"), Loader=yaml.BaseLoader) or {}
    except OSError:
        d = {}
    url = str(d.get("live_url", "") or DEFAULT_LIVE_URL).strip()
    if url.lower() == "off":
        return None
    return url, str(d.get("live_token", "") or "").strip()
