"""백필 같은 긴 작업이 사이트에 살아있음 신호를 보내는 작은 도우미(작업별 문서 하나, 60초에 한 번 이상 보내지 않는다).

사용:
    heart = Heart(cfg_path, task="candles", log=log)   # 설정에 live_token 이 없으면 아무 일도 하지 않는다
    heart.beat("running", "종목 20/709")               # 60초 안에 다시 부르면 무시
    heart.end("done", "조각 8,773개")                   # 마지막은 바로 보낸다
"""
from __future__ import annotations

import time
from typing import Callable

from live_board import LivePoster, live_settings, now_iso


class Heart:
    def __init__(self, cfg_path, task: str, ws: str = "home", automation: str = "orderbook", log: Callable[[str], None] = print, min_gap: float = 60.0):
        st = live_settings(cfg_path)
        self.poster = LivePoster(st[0], st[1], ws, automation, task, log) if st else None
        self.min_gap = min_gap; self.last = 0.0; self.started = now_iso()

    def beat(self, state: str, summary: str) -> None:
        if not self.poster or time.time() - self.last < self.min_gap:
            return
        self.last = time.time()
        self.poster.post(state, summary, started_at=self.started)

    def end(self, state: str, summary: str) -> None:
        if not self.poster:
            return
        self.poster.post(state, summary, started_at=self.started, finished_at=now_iso())
