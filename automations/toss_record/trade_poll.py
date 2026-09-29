"""체결을 조회로 채우기 — 호가 200종목을 웹소켓으로 다 쓰면 체결 채널이 없으니, '최근 체결 50건' 조회(초당 15건)를 돌려 체결 흐름을 이어 붙인다.

- 한 바퀴 = 활발한 종목(직전 조회에서 새 체결 8건 이상)은 매번, 조용한 종목은 4번에 한 번. 조회는 4갈래 병렬(실측 초당 10~12건) → 활발한 종목 몇 초, 조용한 종목 약 25초 주기.
- 중복 제거: 직전 응답의 (시각, 가격, 수량) 묶음을 기억해 새 것만 넘긴다. 같은 밀리초에 같은 가격·수량이 두 번 체결되면 하나로 보는 한계가 있다.
- 13초 안에 50건 넘게 체결되는 종목은 일부가 빠질 수 있다(시총 300억~5,000억에서는 드묾).
- 전일 종가: 일봉 2개를 종목마다 한 번 받아(초당 20건) 등락률 계산에 쓴다.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Callable

KST = timezone(timedelta(hours=9))


def prev_closes(ses, codes: list[str], log: Callable[[str], None] = print) -> dict[str, float]:
    """종목 → 전일 종가. 오늘 일봉이 이미 있으면 그 앞 봉, 없으면 첫 봉."""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    out: dict[str, float] = {}
    errors = 0
    for c in codes:
        try:
            rows = ses.candles(c, "1d", 3).get("candles") or []
        except Exception:  # noqa: BLE001
            errors += 1
            continue
        rows = [r for r in rows if r.get("closePrice")]
        if not rows:
            continue
        pick = rows[1] if rows[0]["timestamp"][:10] == today and len(rows) > 1 else rows[0]
        try:
            out[c] = float(pick["closePrice"])
        except (TypeError, ValueError):
            pass
    if errors:
        log(f"전일 종가 조회 실패 {errors}종목")
    return out


class TradePoller(threading.Thread):
    def __init__(self, ses, codes: list[str], on_row: Callable[[str, str, dict], None], log: Callable[[str], None], stop: threading.Event,
                 hot_threshold: int = 8, cold_every: int = 4, count: int = 50, workers: int = 4):
        super().__init__(name="trade-poll", daemon=True)
        self.ses = ses; self.codes = list(codes); self.on_row = on_row; self.log = log; self.stop = stop
        self.hot_threshold = hot_threshold; self.cold_every = cold_every; self.count = count; self.workers = workers
        self._lock = threading.Lock()
        self.seen: dict[str, set] = {}
        self.hot: dict[str, bool] = {}
        self.stats = {"calls": 0, "new": 0, "errors": 0, "rounds": 0, "hot": 0, "full": 0}

    def poll_one(self, code: str) -> int:
        rows = self.ses.trades(code, self.count)
        rows = sorted(rows, key=lambda r: r.get("timestamp", ""))
        keys = [(r.get("timestamp"), r.get("price"), r.get("volume")) for r in rows]
        prev = self.seen.get(code)
        fresh = [r for r, k in zip(rows, keys) if prev is None or k not in prev]
        if prev is None:
            fresh = fresh[-10:]                      # 첫 조회: 이미 지난 체결은 최근 10건만(창 채우기용)
        with self._lock:                             # on_row(저장·집계)는 한 번에 하나만
            self.seen[code] = set(keys)
            for r in fresh:
                self.on_row("trade:kr", code, {"timestamp": r.get("timestamp", ""), "price": r.get("price", ""), "volume": r.get("volume", "")})
            self.stats["calls"] += 1
            if len(rows) >= self.count and len(fresh) >= self.count:
                self.stats["full"] += 1              # 50건 전부 새 것 = 그 사이 더 있었을 수 있음(누락 가능)
            self.hot[code] = len(fresh) >= self.hot_threshold
            self.stats["new"] += len(fresh)
        return len(fresh)

    def _safe_poll(self, code: str) -> None:
        if self.stop.is_set():
            return
        try:
            self.poll_one(code)
        except Exception as exc:  # noqa: BLE001 — 한 종목 실패가 바퀴를 멈추지 않게
            self.stats["errors"] += 1
            if self.stats["errors"] in (1, 10, 100):
                self.log(f"체결 조회 실패({self.stats['errors']}회) {code}: {type(exc).__name__}")

    def run(self) -> None:
        # 순차 호출은 응답 시간 때문에 초당 4건밖에 안 나와(실측) 4갈래로 나눠 초당 15건을 채운다(간격 제한은 세션이 공유, 넘치면 429 재시도)
        from concurrent.futures import ThreadPoolExecutor
        rnd = 0
        with ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="trade-poll") as pool:
            while not self.stop.is_set():
                rnd += 1; self.stats["rounds"] = rnd
                t0 = time.time()
                todo = [c for c in self.codes if self.hot.get(c, True) or rnd % self.cold_every == 0]
                list(pool.map(self._safe_poll, todo))
                self.stats["hot"] = sum(1 for v in self.hot.values() if v)
                if time.time() - t0 < 1.0:
                    self.stop.wait(1.0)
