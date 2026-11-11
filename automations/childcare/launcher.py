"""정각 발사대 — 사장님이 로그인해 둔 크롬에 붙고, 아이사랑 서버 시각에 맞춰 기다린다.

시간제보육 독립반은 **이용일 14일 전 09:00 정각**에 자리가 열리고, 10자리에 1,000명이 몰린다.
그래서 이 파일이 하는 일은 둘뿐이다.

1. **크롬 이어받기** — 사람이 로그인(인증서든 아이디든)해 둔 크롬에 그대로 붙는다.
   크롬을 디버그 포트로 띄워 두어야 한다:
       chrome.exe --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\\childcare-chrome"
2. **시계 맞추기** — 이 PC 시계는 몇 초씩 틀린다. 아이사랑이 응답에 실어 보내는 `Date` 로
   보정한 뒤 목표 시각까지 기다린다. 일찍 쏘면 "아직 열리지 않았습니다", 늦게 쏘면 매진이다.

여기엔 예약 동작이 없다. 발사대만이다.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
CDP_PORT = 9222
# 시각만 재는 가벼운 주소(본문을 받지 않는다). 아이사랑과 같은 서버의 시계를 본다.
CLOCK_URL = "https://www.childcare.go.kr/cms/gen/images/logo.svg"


HOST = "childcare.go.kr"


def attach_chrome(playwright, port: int = CDP_PORT, go_to: str = ""):
    """이미 떠 있는 크롬에서 **아이사랑 탭**을 찾아 붙는다. 로그인 상태를 그대로 쓴다.

    다른 사이트 탭에 붙으면 서버 시각을 못 읽는다(브라우저가 남의 집 응답 헤더를 안 보여 준다).
    그래서 아이사랑 탭을 찾고, 없으면 하나 열어 거기로 간다.
    """
    browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
    if not browser.contexts:
        raise RuntimeError("크롬은 떠 있는데 창이 없어요. 탭을 하나 열어 주세요")
    ctx = browser.contexts[0]
    page = next((pg for pg in ctx.pages if HOST in pg.url), None)
    if page is None:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(go_to or f"https://www.{HOST}/", wait_until="domcontentloaded", timeout=60000)
    page.bring_to_front()
    return browser, page


def server_offset_ms(page, samples: int = 6) -> float:
    """이 PC 시계가 아이사랑 서버보다 얼마나 빠른지(ms). 양수면 PC 가 빠르다.

    응답 헤더 `Date` 는 초 단위라서 값만 읽으면 최대 1초가 틀린다.
    그래서 초가 **넘어가는 순간**을 잡는다 — 짧은 간격으로 계속 찔러 보다가
    Date 가 바뀌면 그 순간이 서버의 '정확히 X초 000ms' 다.
    """
    best = None
    for _ in range(samples):
        prev = _head_date(page)
        deadline = time.time() + 1.5
        while time.time() < deadline:
            local_before = time.time()
            now = _head_date(page)
            if now != prev:
                # 서버가 막 새 초로 넘어갔다. 요청이 날아가는 시간만큼은 어쩔 수 없다.
                rtt = time.time() - local_before
                offset = (local_before + rtt / 2) * 1000 - now * 1000
                if best is None or abs(offset) < abs(best):
                    best = offset
                break
    if best is None:
        raise RuntimeError("서버 시각을 못 읽었어요")
    return best


def _head_date(page) -> float:
    """아이사랑 응답의 Date 헤더를 초 단위 epoch 으로."""
    ms = page.evaluate(
        """async (url) => {
             const r = await fetch(url + '?t=' + Math.random(), {method: 'HEAD', cache: 'no-store'});
             const d = r.headers.get('date');
             return d ? Date.parse(d) : 0;
           }""",
        CLOCK_URL,
    )
    if not ms:
        raise RuntimeError("Date 헤더가 없어요")
    return ms / 1000.0


def next_open_at(now: datetime | None = None, hour: int = 9) -> datetime:
    """다음 오픈 시각(KST). 오늘 9시가 지났으면 내일 9시."""
    now = now or datetime.now(KST)
    today = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return today if now < today else today + timedelta(days=1)


def sleep_until(target: datetime, offset_ms: float, lead_ms: float = 0.0, progress=print) -> None:
    """목표 시각까지 기다린다. offset_ms 로 PC 시계를 보정하고, lead_ms 만큼 먼저 깨운다.

    마지막 2초는 쉬지 않고 돌며 기다린다(sleep 은 Windows 에서 15ms 씩 늦는다).
    """
    target_epoch = target.timestamp() + (offset_ms - lead_ms) / 1000.0
    while True:
        left = target_epoch - time.time()
        if left <= 0:
            return
        if left > 10:
            progress(f"발사까지 {left:.0f}초")
            time.sleep(min(left - 5, 30))
        elif left > 2:
            time.sleep(left - 2)
        else:
            while time.time() < target_epoch:
                pass
            return


def target_date(days_ahead: int = 14, now: datetime | None = None) -> str:
    """오늘 09:00 에 열리는 이용일(기본 14일 뒤)을 YYYYMMDD 로."""
    now = now or datetime.now(KST)
    return (now + timedelta(days=days_ahead)).strftime("%Y%m%d")
