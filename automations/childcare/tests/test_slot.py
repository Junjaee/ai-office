"""장전 값이 실제 화면과 글자 하나까지 같은지.

2026-11-11 에 힐스송파 화면에서 '추가' 를 눌러 실제로 찍힌 값을 그대로 기준으로 삼는다.
여기가 틀리면 서버가 조용히 거절하고, 정각 한 방을 날린다.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from childcare_site import _slot, row_index  # noqa: E402

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


def test_표에서_몇_번째_줄인지():
    today = date(2026, 11, 11)
    assert row_index("20261111", today) == 0
    assert row_index("20261114", today) == 3   # 화면에서 tm_9_3 = 2026-11-14(토)
    assert row_index("20261116", today) == 5   # 화면에서 tm_9_5 = 2026-11-16(월)
    assert row_index("20261125", today) == 14  # 오픈되는 날은 늘 마지막 줄
