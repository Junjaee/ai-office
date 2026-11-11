"""발사대의 시각 계산 — 여기가 틀리면 하루 늦게 쏘거나 1초 늦게 쏜다."""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from launcher import KST, next_open_at, sleep_until, target_date  # noqa: E402


def test_오픈시각은_9시가_안_지났으면_오늘():
    now = datetime(2026, 11, 11, 8, 30, tzinfo=KST)
    assert next_open_at(now) == datetime(2026, 11, 11, 9, 0, tzinfo=KST)


def test_오픈시각은_9시가_지났으면_내일():
    now = datetime(2026, 11, 11, 9, 0, 1, tzinfo=KST)
    assert next_open_at(now) == datetime(2026, 11, 12, 9, 0, tzinfo=KST)


def test_정각_직후도_내일로_넘긴다():
    """09:00:00.000 은 '지났다'로 본다 — 그 순간은 이미 쏜 뒤다."""
    now = datetime(2026, 11, 11, 9, 0, 0, tzinfo=KST)
    assert next_open_at(now).day == 12


def test_이용일은_14일_뒤():
    now = datetime(2026, 11, 11, 9, 0, tzinfo=KST)
    assert target_date(14, now) == "20261125"


def test_PC시계가_빠르면_그만큼_더_기다린다():
    """PC 가 서버보다 300ms 빠르면, PC 시계로는 300ms 늦게 쏴야 서버 정각이다."""
    target = datetime.now(KST) + timedelta(seconds=0.4)
    started = time.monotonic()
    sleep_until(target, offset_ms=300, progress=lambda _: None)
    waited = time.monotonic() - started
    assert 0.6 < waited < 0.9, waited


def test_먼저_깨우기가_먹는다():
    target = datetime.now(KST) + timedelta(seconds=0.5)
    started = time.monotonic()
    sleep_until(target, offset_ms=0, lead_ms=300, progress=lambda _: None)
    waited = time.monotonic() - started
    assert 0.1 < waited < 0.35, waited


def test_이미_지난_시각이면_곧바로_돌아온다():
    target = datetime.now(KST) - timedelta(seconds=5)
    started = time.monotonic()
    sleep_until(target, offset_ms=0, progress=lambda _: None)
    assert time.monotonic() - started < 0.05


# ── 창에서 고르는 이용일 ──
from app import default_use_date, parse_open_at  # noqa: E402


def test_저장된_이용일이_아직_안_지났으면_그대로():
    now = datetime(2026, 11, 11, 8, 0, tzinfo=KST)
    assert default_use_date("2026-11-25", now) == "2026-11-25"


def test_저장된_이용일이_지났으면_오늘_기준_14일_뒤():
    """앱을 새로 켜면 오늘 09시에 열리는 날짜가 저절로 들어가야 한다."""
    now = datetime(2026, 11, 11, 8, 0, tzinfo=KST)
    assert default_use_date("2026-10-01", now) == "2026-11-25"


def test_이용일이_비어_있어도_14일_뒤():
    now = datetime(2026, 11, 11, 8, 0, tzinfo=KST)
    assert default_use_date("", now) == "2026-11-25"


def test_오늘_날짜는_지난_것으로_치지_않는다():
    now = datetime(2026, 11, 11, 23, 0, tzinfo=KST)
    assert default_use_date("2026-11-11", now) == "2026-11-11"


def test_오픈시각_문자열을_다음_그_시각으로():
    now = datetime(2026, 11, 11, 8, 30, tzinfo=KST)
    assert parse_open_at("09:00:00", now) == datetime(2026, 11, 11, 9, 0, tzinfo=KST)
    assert parse_open_at("09:00:00", datetime(2026, 11, 11, 9, 30, tzinfo=KST)).day == 12


# ── 실제로 고를 수 있는 시간만 (정시 단위, 09~18) ──
from app import CLOSE_HOUR, MAX_HOURS, OPEN_HOURS, hour_range  # noqa: E402


def test_시작시각과_시간수로_정시_구간을_만든다():
    assert hour_range(9, 4) == ("09:00", "13:00")
    assert hour_range(13, 1) == ("13:00", "14:00")


def test_닫는_시각을_넘지_않는다():
    assert hour_range(17, 9) == ("17:00", "18:00")


def test_고를_수_있는_값은_화면과_같다():
    """화면의 시간 칸은 09~17, 이용시간은 1~9 (2026-11-11 실측)."""
    assert list(OPEN_HOURS) == list(range(9, 18))
    assert list(MAX_HOURS) == list(range(1, 10))
    assert CLOSE_HOUR == 18
