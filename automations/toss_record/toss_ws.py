"""토스증권 웹소켓 — 국내 체결(trade:kr)·호가(orderbook:kr) 실시간 수신.

규칙(공식 AsyncAPI, 2026-09-29): 주소 wss://openapi-ws.tossinvest.com/ws/v1, 헤더 Authorization: Bearer <토큰>(handshake 1회).
- 구독은 '선언형': JSON 배열 하나를 보내면 그것이 현재 구독 전체(빠진 항목은 해제). 계정당 연결 2개(초과 시 가장 오래된 연결이 끊김), 연결당 100건(codes 합산), 선언 5회/초.
- 응답: {"type":"subscriptions","subscribed":[...],"rejected":[{target,code,message}]} → {"type":"message","topic":"trade:kr:005930","data":{...}} → {"type":"pong"} → {"type":"error",...}
- 텍스트 "PING" 을 60초마다 보내야 함(180초 무응답이면 서버가 끊음). 시세는 LOSSY(밀리면 중간 프레임 유실).
- 호가 프레임은 전체 스냅샷(asks 낮은 가격순·bids 높은 가격순, 각 10단계). 체결은 price·volume·timestamp 만(매수/매도 구분 없음).
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import websockets

WS_URL = "wss://openapi-ws.tossinvest.com/ws/v1"
PER_CONN_LIMIT = 100
MAX_CONNECTIONS = 2
PING_SEC = 60


@dataclass
class ConnStats:
    frames: int = 0
    trades: int = 0
    books: int = 0
    reconnects: int = 0
    errors: int = 0
    rejected: list = field(default_factory=list)
    subscribed: int = 0
    last_data_ts: float = 0.0


def declaration(codes: list[str], channels: tuple[str, ...] = ("orderbook:kr", "trade:kr")) -> list[dict]:
    """codes × channels 구독 선언(연결당 100건 안인지 검사)."""
    n = len(codes) * len(channels)
    if n > PER_CONN_LIMIT:
        raise ValueError(f"구독 {n}건 > 연결당 한도 {PER_CONN_LIMIT}")
    return [{"id": "rec-1"}] + [{"type": ch, "codes": list(codes)} for ch in channels]


def split_codes(codes: list[str], channels_per_code: int, n_conn: int = MAX_CONNECTIONS) -> list[list[str]]:
    """종목을 연결 수만큼 나눈다(연결당 100건 ÷ 채널 수)."""
    per = PER_CONN_LIMIT // channels_per_code
    chunks = [codes[i:i + per] for i in range(0, len(codes), per)]
    return chunks[:n_conn]


def flatten_book(data: dict) -> dict:
    """호가 스냅샷 → 한 줄(ask1_p ask1_v … bid10_v, 총잔량)."""
    row = {"timestamp": data.get("timestamp") or ""}
    asks = data.get("asks") or []; bids = data.get("bids") or []
    for i in range(10):
        a = asks[i] if i < len(asks) else {}; b = bids[i] if i < len(bids) else {}
        row[f"ask{i+1}_p"] = a.get("price", ""); row[f"ask{i+1}_v"] = a.get("volume", "")
        row[f"bid{i+1}_p"] = b.get("price", ""); row[f"bid{i+1}_v"] = b.get("volume", "")
    row["ask_total"] = str(sum(int(float(a.get("volume", 0) or 0)) for a in asks))
    row["bid_total"] = str(sum(int(float(b.get("volume", 0) or 0)) for b in bids))
    row["levels"] = f"{len(asks)}/{len(bids)}"
    return row


async def run_connection(get_token: Callable[[], str], codes: list[str], channels: tuple[str, ...], on_row: Callable[[str, str, dict], None],
                         until: Callable[[], bool], stats: ConnStats, log: Callable[[str], None], name: str = "c1",
                         on_auth_fail: Callable[[], Awaitable[None]] | None = None, idle_timeout: float = 120.0) -> None:
    """until() 이 참이 될 때까지 연결을 유지·재연결하며 on_row(channel, code, row) 를 부른다."""
    backoff = 2.0
    while not until():
        try:
            headers = {"Authorization": f"Bearer {get_token()}"}
            async with websockets.connect(WS_URL, additional_headers=headers, ping_interval=None, max_size=2**22, open_timeout=20) as ws:
                await ws.send(json.dumps(declaration(codes, channels)))
                last_ping = time.time()
                backoff = 2.0
                while not until():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    except asyncio.TimeoutError:
                        if time.time() - last_ping >= PING_SEC:
                            await ws.send("PING"); last_ping = time.time()
                        if stats.last_data_ts and time.time() - stats.last_data_ts > idle_timeout and time.time() - last_ping > 10:
                            pass  # 장중 무데이터는 종목 특성일 수 있어 끊지 않는다(핑으로 연결만 확인)
                        continue
                    if time.time() - last_ping >= PING_SEC:
                        await ws.send("PING"); last_ping = time.time()
                    stats.frames += 1
                    try:
                        msg = json.loads(raw)
                    except (ValueError, TypeError):
                        stats.errors += 1; continue
                    t = msg.get("type")
                    if t == "message":
                        topic = msg.get("topic", ""); parts = topic.split(":")
                        if len(parts) != 3:
                            continue
                        ch, code = f"{parts[0]}:{parts[1]}", parts[2]
                        data = msg.get("data") or {}
                        try:
                            if parts[0] == "orderbook":
                                stats.books += 1; on_row(ch, code, flatten_book(data))
                            else:
                                stats.trades += 1; on_row(ch, code, {"timestamp": data.get("timestamp", ""), "price": data.get("price", ""), "volume": data.get("volume", "")})
                        except Exception as exc:  # noqa: BLE001 — 저장·집계 오류 하나가 연결을 끊지 않게
                            stats.errors += 1
                            if stats.errors in (1, 10, 100, 1000):
                                log(f"[{name}] 행 처리 오류({stats.errors}회) {code}: {type(exc).__name__}: {str(exc)[:100]}")
                        stats.last_data_ts = time.time()
                    elif t == "subscriptions":
                        stats.subscribed = len(msg.get("subscribed") or [])
                        rej = msg.get("rejected") or []
                        if rej:
                            stats.rejected = [(r.get("target"), r.get("code")) for r in rej]
                            log(f"[{name}] 구독 거부 {len(rej)}건: " + ", ".join(f"{r.get('target')}({r.get('code')})" for r in rej[:5]))
                        log(f"[{name}] 구독 확정 {stats.subscribed}건")
                    elif t == "error":
                        stats.errors += 1
                        err = msg.get("error") or {}
                        log(f"[{name}] 오류 프레임 {err.get('code')}: {str(err.get('message', ''))[:80]}")
                        if err.get("code") == "server-shutdown":
                            break
                    elif t == "pong":
                        pass
        except websockets.exceptions.InvalidStatus as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            stats.errors += 1
            log(f"[{name}] 접속 거절 HTTP {code}" + (" — 토큰 재발급" if code == 401 else " — 허용 IP 확인" if code == 403 else ""))
            if code == 401 and on_auth_fail:
                await on_auth_fail()
            if code == 403:
                await asyncio.sleep(60)
        except (websockets.exceptions.ConnectionClosed, OSError, asyncio.TimeoutError) as exc:
            stats.errors += 1
            log(f"[{name}] 연결 끊김 {type(exc).__name__}")
        if until():
            break
        stats.reconnects += 1
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60.0)
