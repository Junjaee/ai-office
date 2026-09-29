"""사이트로 보내는 실시간 자료 — 녹음기가 받은 호가·체결을 종목별로 집계해 5초마다 /api/live 에 올린다(worker/live.ts, 화면 app/office/LiveBoard.tsx).

집계(종목마다, 창 = 최근 5분):
- 체결 방향: 체결가 ≥ 직전 매도1호가 → 매수(B), ≤ 직전 매수1호가 → 매도(S), 그 사이 → 중간(M). 토스 체결에 매수/매도 구분이 없어 이렇게 추정한다.
- 체결강도 = 매수 체결금액 ÷ 매도 체결금액 × 100. 잔량비 = 매수 총잔량 ÷ 매도 총잔량. 벽 = 10단계 중 금액(가격×잔량)이 가장 큰 호가.
- 벽 신호 = 5분 전 표본과 비교해 1~5호가 잔량이 2배 넘게 늘고 금액 1억 이상(2026-09-29 사용자 결정으로 3배·3억에서 낮춤). 매수벽·매도벽을 구분한다.
- 점수(2026-09-29 개편, 사용자 지적 "벽이 작으면 점수가 낮아야"): 전부 방향이 있고 종목의 거래 규모에 견준다. 정렬용이지 예측값이 아니다.
    체결 방향 = clip(log2(매수 체결금액 ÷ 매도 체결금액), -2, 2) × min(1, 5분 합계 ÷ 1억)
    가장 큰 벽 = ±clip(log2(1 + 벽 금액 ÷ 5분 거래대금), 0, 2) (매수벽 +, 매도벽 -, 0.5억 미만 0)
    벽 생김 신호 = ±clip(log2(1 + 새 벽 금액 ÷ 5분 거래대금), 0, 2)
    잔량비 = clip(log2(매수 총잔량 ÷ 매도 총잔량), -1, 1)
- 체결 방향 분류: 체결가 ≥ 매도1 → 매수, ≤ 매수1 → 매도, 그 사이(통합 호가라 자주 생김)는 호가 중간값보다 위면 매수·아래면 매도.
보내는 문서: {ws, automation, task:"record", state, at, summary, started_at, board:{..., items:[...]}} (≤ 1MB, 종목 100개면 약 150KB).
"""
from __future__ import annotations

import json
import math
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


def ts_ms(iso: str, default: int) -> int:
    """'2026-09-29T10:07:15.007+09:00' → ms. 못 읽으면 default(수신 시각)."""
    try:
        return int(datetime.fromisoformat(iso).timestamp() * 1000)
    except (TypeError, ValueError):
        return default


class LiveBoard:
    def __init__(self, names: dict[str, str] | None = None, window_sec: int = 300, wall_mult: float = 2.0, wall_min_amt: float = 1e8, sample_sec: float = 5.0,
                 prev_close: dict[str, float] | None = None, refs: dict[str, dict] | None = None):
        self.names = names or {}
        self.prev_close = prev_close or {}
        self.refs = refs or {}                                # daily_ref.daily_refs(): prev_close·prev_high·high20·avg_amt5
        self.hist: dict[str, deque] = {}                      # code → deque[(ms, mid)] 최근 15분(흐름 계산)
        self.day_high: dict[str, float] = {}                  # 녹음 시작 이후 최고 중간값
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
            if asks and bids:
                mid = (asks[0][0] + bids[0][0]) / 2
                h = self.hist.setdefault(code, deque())
                if not h or recv - h[-1][0] >= 5000:
                    h.append((recv, mid))
                while h and recv - h[0][0] > 15 * 60 * 1000:
                    h.popleft()
                if mid > self.day_high.get(code, 0):
                    self.day_high[code] = mid
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
                a1, b1 = b["asks"][0][0], b["bids"][0][0]
                if price >= a1:
                    side = "B"
                elif price <= b1:
                    side = "S"
                else:                                 # 통합 호가(KRX+NXT)라 호가 사이 체결이 잦다 → 중간값 기준
                    side = "B" if price >= (a1 + b1) / 2 else "S"
            dq = self.trades.setdefault(code, deque())
            t = ts_ms(row.get("timestamp", ""), recv)
            if dq and t < dq[-1][0]:
                t = dq[-1][0]                       # 시각이 뒤로 가면(조회 순서) 정렬 유지
            dq.append((t, row.get("timestamp", ""), price, vol, side))
            self._trim(dq, max(recv, t))
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
        event = ""; event_side = ""; event_amt = 0.0
        smp = self.samples.get(code)
        if b and smp and len(smp) >= 2 and now - smp[0][0] >= self.window_ms * 0.8:
            _, asks0, bids0 = smp[0]
            for sname, skey, cur, old in (("매수", "bid", b["bids"], bids0), ("매도", "ask", b["asks"], asks0)):
                for i in range(min(5, len(cur), len(old))):
                    p1, v1 = cur[i]; v0 = old[i][1]
                    if v1 > self.wall_mult * max(v0, 1) and p1 * v1 >= self.wall_min_amt and p1 * v1 > event_amt:
                        event = f"{sname}{i+1}호가 벽 생김({p1*v1/1e8:.1f}억)"; event_side = skey; event_amt = p1 * v1
        score, parts = self.score(buy, sell, amt, wall, event_side, event_amt, bid_total, ask_total)
        ref = self.refs.get(code, {})
        pc = self.prev_close.get(code) or ref.get("prev_close")
        chg = round((price / pc - 1) * 100, 2) if pc and price else None
        # 돈 몰림 항목: 거래대금 배수(5분 ÷ 평소 5분), 자리(20일 신고가·전일 고가·당일 고가), 15분 흐름
        avg5 = ref.get("avg_amt5") or 0
        amt_ratio = round(amt / avg5, 2) if avg5 > 0 else None
        h = self.hist.get(code)
        mom15 = None
        if h and len(h) >= 2 and now - h[0][0] >= 10 * 60 * 1000 and h[0][1] > 0:
            mom15 = round((price / h[0][1] - 1) * 100, 2) if price else None
        pos = ""
        if price and ref.get("high20") and price > ref["high20"]:
            pos = "20일 신고가"
        elif price and ref.get("prev_high") and price > ref["prev_high"]:
            pos = "전일 고가 돌파"
        elif price and self.day_high.get(code) and price >= self.day_high[code] * 0.999:
            pos = "당일 고가"
        return {
            "amt_ratio": amt_ratio, "pos": pos, "mom15": mom15, "high20": ref.get("high20"), "prev_high": ref.get("prev_high"),
            "code": code, "name": self.names.get(code, code), "price": price, "prev_close": pc, "chg_pct": chg, "strength": strength, "event_side": event_side, "parts": parts,
            "buy_amt": round(buy / 1e8, 3), "sell_amt": round(sell / 1e8, 3), "ratio": ratio, "ask_total": ask_total, "bid_total": bid_total,
            "amt": round(amt / 1e8, 2), "n_trades": len(tr), "score": score, "wall": wall, "event": event,
            "book": {"ts": b["ts"], "asks": [[f"{p:g}", f"{v:g}"] for p, v in b["asks"]], "bids": [[f"{p:g}", f"{v:g}"] for p, v in b["bids"]]} if b else None,
            "trades": [[ts, f"{p:g}", f"{v:g}", s] for _, ts, p, v, s in list(tr)[-20:]],
        }

    @staticmethod
    def score(buy: float, sell: float, amt: float, wall: dict | None, event_side: str, event_amt: float, bid_total: float, ask_total: float) -> tuple[float, dict]:
        """방향 있는 점수와 항목별 기여. 값은 원 단위."""
        def clip(x: float, lo: float, hi: float) -> float:
            return max(lo, min(hi, x))
        base = max(amt, 1e7)                                  # 5분 거래대금(최소 0.1억) — 벽을 이 크기에 견준다
        # 체결 방향: 5분 합계 1억이면 온전히, 그보다 작으면 금액에 비례해 줄인다(소형주는 5분에 1억을 못 채우는 종목이 많아 2026-09-29 자름→비례로)
        total = buy + sell
        weight = min(1.0, total / 1e8)
        raw = clip(math.log2(buy / sell), -2, 2) if (buy > 0 and sell > 0) else (2.0 if buy > 0 else -2.0 if sell > 0 else 0.0)
        flow = raw * weight
        wall_pts = 0.0
        if wall and wall["amt"] * 1e8 >= 5e7:
            wall_pts = clip(math.log2(1 + wall["amt"] * 1e8 / base), 0, 2) * (1 if wall["side"] == "bid" else -1)
        ev_pts = clip(math.log2(1 + event_amt / base), 0, 2) * (1 if event_side == "bid" else -1) if event_side else 0.0
        depth = clip(math.log2(bid_total / ask_total), -1, 1) if bid_total > 0 and ask_total > 0 else (1.0 if bid_total > 0 and ask_total == 0 else -1.0 if ask_total > 0 else 0.0)
        parts = {"flow": round(flow, 2), "wall": round(wall_pts, 2), "event": round(ev_pts, 2), "depth": round(depth, 2)}
        return round(flow + wall_pts + ev_pts + depth, 2), parts

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
