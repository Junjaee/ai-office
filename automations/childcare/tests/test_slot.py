"""장전 값이 실제 화면과 글자 하나까지 같은지.

2026-11-11 에 힐스송파 화면에서 '추가' 를 눌러 실제로 찍힌 값을 그대로 기준으로 삼는다.
여기가 틀리면 서버가 조용히 거절하고, 정각 한 방을 날린다.
"""
from __future__ import annotations

import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from childcare_site import _slot, _ymd_dash  # noqa: E402

# 화면에서 실제로 읽은 값 (1시간, 들꽃향기, 2026-11-24 09시)
REAL = {
    "sdate": "2026-11-24(화)",
    "restime": "09 : 00  ~  10 : 00 ",
    "resdt": "20261124",
    "resbgntm": "09 : 00",
    "resendtm": "10 : 00",
    "rtm": "1",
    "resclseq": "15",
    "resclname": "들꽃향기",
}


def test_실제_화면값과_똑같이_만든다():
    assert _slot("20261124", "09:00", "10:00", "15", "들꽃향기") == REAL


def test_요일이_한글로_붙는다():
    assert _slot("20261125", "09:30", "13:30", "15", "x")["sdate"] == "2026-11-25(수)"
    assert _slot("20261121", "09:00", "10:00", "15", "x")["sdate"] == "2026-11-21(토)"


def test_이용시간수는_시각_차이():
    assert _slot("20261125", "09:30", "13:30", "15", "x")["rtm"] == "4"


def test_콜론_둘레_공백과_물결_모양을_지킨다():
    s = _slot("20261125", "13:00", "17:00", "15", "x")
    assert s["resbgntm"] == "13 : 00"
    assert s["restime"] == "13 : 00  ~  17 : 00 "


def test_표의_날짜_모양():
    """표의 행에는 '2026-11-25' 로 적혀 있다. 줄 번호를 날짜로 계산하지 않고 이 글자로 찾는다.

    표의 첫 행이 늘 오늘인 것은 아니다 — 당일 마감(14시)이 지나면 오늘이 빠진다
    (2026-11-11 16시에 확인: 표가 11-12 부터 시작했다).
    """
    assert _ymd_dash("20261125") == "2026-11-25"
    assert _ymd_dash("20260101") == "2026-01-01"
