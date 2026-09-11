"""주말 일정 — 날짜 계산·일정 정리·글 만들기 (순수 함수, 네트워크 없음)."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from weekend_calendar import Event, build_message, to_events, upcoming_weekend  # noqa: E402

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
