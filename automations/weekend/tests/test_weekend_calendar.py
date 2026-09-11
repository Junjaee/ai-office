"""주말 일정 — 날짜 계산·일정 정리·글 만들기 (순수 함수, 네트워크 없음)."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from weekend_calendar import Event, build_message, describe, to_events, upcoming_weekend  # noqa: E402

SAT, SUN = date(2026, 9, 12), date(2026, 9, 13)


def test_upcoming_weekend():
    assert upcoming_weekend(date(2026, 9, 10)) == (SAT, SUN)                # 목요일 → 이번 주 토·일
    assert upcoming_weekend(SAT) == (SAT, SUN)                              # 토요일이면 오늘부터
    assert upcoming_weekend(SUN) == (date(2026, 9, 19), date(2026, 9, 20))  # 일요일이면 다음 주


def item(title, start, end, loc=None, status="confirmed"):
    d = {"summary": title, "start": start, "end": end, "status": status}
    if loc:
        d["location"] = loc
    return d


def test_to_events_timed_all_day_overnight_utc_and_cancelled():
    items = [
        item("국회 행사", {"dateTime": "2026-09-12T10:00:00+09:00"}, {"dateTime": "2026-09-12T12:00:00+09:00"}, "여의도"),
        item("지역 방문", {"date": "2026-09-12"}, {"date": "2026-09-14"}),  # 토·일 이틀 종일 (끝 날짜는 포함 안 됨)
        item("밤 일정", {"dateTime": "2026-09-12T22:00:00+09:00"}, {"dateTime": "2026-09-13T01:00:00+09:00"}),
        item("UTC 로 온 일정", {"dateTime": "2026-09-13T05:00:00Z"}, {"dateTime": "2026-09-13T06:30:00Z"}),  # KST 14:00~15:30
        item("취소됨", {"dateTime": "2026-09-13T09:00:00+09:00"}, {"dateTime": "2026-09-13T10:00:00+09:00"}, status="cancelled"),
    ]
    ev = to_events(items, (SAT, SUN))
    assert [(e.day, e.start, e.end, e.title) for e in ev] == [
        (SAT, "종일", "", "지역 방문"),
        (SAT, "10:00", "12:00", "국회 행사"),
        (SAT, "22:00", "~", "밤 일정"),
        (SUN, "종일", "", "지역 방문"),
        (SUN, "~", "01:00", "밤 일정"),
        (SUN, "14:00", "15:30", "UTC 로 온 일정"),
    ]
    assert ev[1].location == "여의도"


def test_untitled_event_gets_placeholder():
    ev = to_events([item("", {"date": "2026-09-12"}, {"date": "2026-09-13"})], (SAT, SUN))
    assert ev[0].title == "(제목 없음)"


def test_build_message_groups_by_day_and_marks_empty_day():
    ev = [
        Event(SAT, "종일", "", "지역 방문", ""),
        Event(SAT, "10:00", "12:00", "국회 행사", "여의도"),
        Event(SAT, "22:00", "~", "밤 일정", ""),
    ]
    assert build_message("530호 일정", (SAT, SUN), ev).splitlines() == [
        "📅 530호 일정 · 주말 일정 (9/12 토 ~ 9/13 일)",
        "",
        "■ 9월 12일 (토)",
        "· 종일  지역 방문",
        "· 10:00~12:00  국회 행사 @ 여의도",
        "· 22:00~  밤 일정",
        "",
        "■ 9월 13일 (일)",
        "· 일정 없음",
    ]


def test_build_message_is_cut_to_telegram_limit():
    ev = [Event(SAT, "10:00", "11:00", "긴 제목 " * 30, "") for _ in range(40)]
    text = build_message("530호 일정", (SAT, SUN), ev)
    assert len(text) <= 4096
    assert text.endswith("… 너무 길어 일부만 보냈어요")


# ── 받는 분에게는 종류만 (사용자 결정 2026-09-11: 누구와 무엇을 하는지 빼고, 동탄 관련은 그대로) ──

def test_masked_message_shows_only_kind_except_dongtan():
    ev = [
        Event(SAT, "09:00", "10:00", "화성특례시 호남향우회 한마음 대축제", "화성시민대학"),
        Event(SAT, "16:00", "17:00", "동탄맨 콘텐츠 촬영", ""),
        Event(SAT, "19:00", "21:00", "홍길동 대표 만찬", "여의도 식당"),
        Event(SUN, "종일", "", "개인 용무", ""),
        Event(SUN, "09:30", "10:30", "박창훈 회장 청계산 등산", ""),
        Event(SUN, "12:00", "13:00", "주민 간담회", "동탄복합문화센터"),
        Event(SUN, "15:00", "16:00", "김철수 미팅", ""),
    ]
    text = build_message("530호 일정", (SAT, SUN), ev, reveal_keywords=["동탄"])
    assert text.splitlines()[2:] == [
        "■ 9월 12일 (토)",
        "· 09:00~10:00  행사 일정",
        "· 16:00~17:00  동탄맨 콘텐츠 촬영",
        "· 19:00~21:00  저녁 식사 일정",
        "",
        "■ 9월 13일 (일)",
        "· 종일  기타 일정",
        "· 09:30~10:30  등산 일정",
        "· 12:00~13:00  주민 간담회 @ 동탄복합문화센터",
        "· 15:00~16:00  회의 일정",
    ]
    for hidden in ("박창훈", "홍길동", "김철수", "호남향우회", "화성시민대학", "여의도"):
        assert hidden not in text


def test_describe_meal_by_time_unknown_and_reveal():
    assert describe(Event(SAT, "12:00", "13:00", "OOO 의원 오찬", ""), ["동탄"]) == "점심 식사 일정"
    assert describe(Event(SAT, "07:30", "08:30", "조찬 모임", ""), ["동탄"]) == "아침 식사 일정"
    assert describe(Event(SAT, "종일", "", "가족 식사", ""), ["동탄"]) == "식사 일정"
    assert describe(Event(SAT, "10:00", "11:00", "비밀 약속", "서울"), ["동탄"]) == "기타 일정"
    assert describe(Event(SAT, "10:00", "11:00", "동탄 비밀 약속", "장소"), ["동탄"]) == "동탄 비밀 약속 @ 장소"
    assert describe(Event(SAT, "10:00", "11:00", "비밀 약속", "서울"), None) == "비밀 약속 @ 서울"   # 가리지 않음
    assert describe(Event(SAT, "10:00", "11:00", "비밀 약속", "서울"), []) == "기타 일정"            # 빈 목록 = 전부 가림
