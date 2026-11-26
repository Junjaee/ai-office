import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agenda_parse import KST, build_event, decide, event_id, folder_date, is_sub, parse_header  # noqa: E402

HEAD = "제11차 재정경제기획위원회 2026. 11. 26.(목) 10:00 의 사 일 정"


def test_parse_header_reads_number_body_and_time():
    m = parse_header(HEAD)
    assert (m.n, m.body, m.start) == (11, "재정경제기획위원회", datetime(2026, 11, 26, 10, 0, tzinfo=KST))


def test_parse_header_gives_none_when_unreadable():
    assert parse_header("의사일정 안내") is None
    assert parse_header("제1차 재정경제기획위원회 2026. 13. 40.(목) 10:00") is None   # 없는 날짜
    assert parse_header("") is None


def test_subcommittee_is_skipped():
    assert is_sub(parse_header("제3차 경제재정소위원회 2026. 11. 27.(금) 14:00"))
    assert not is_sub(parse_header(HEAD))


def test_event_has_title_time_and_stable_id():
    m = parse_header(HEAD)
    e = build_event("재경위", m, "18:00")
    assert e["summary"] == "[재경위] 제11차 전체회의"
    assert e["start"]["dateTime"] == "2026-11-26T10:00:00+09:00"
    assert e["end"]["dateTime"] == "2026-11-26T18:00:00+09:00"
    assert e["id"] == event_id("재경위", m) and set(e["id"]) <= set("0123456789abcdefghijklmnopqrstuv")
    late = parse_header("제12차 재정경제기획위원회 2026. 11. 26.(목) 19:30")
    assert build_event("재경위", late, "18:00")["end"]["dateTime"] == "2026-11-26T21:30:00+09:00"


def test_decide_add_same_move_manual():
    m = parse_header(HEAD)
    at = lambda hhmm: {"dateTime": f"2026-11-26T{hhmm}:00+09:00"}  # noqa: E731
    assert decide("재경위", m, []) == "add"
    assert decide("재경위", m, [{"id": event_id("재경위", m), "start": at("10:00")}]) == "same"
    assert decide("재경위", m, [{"id": event_id("재경위", m), "start": at("14:00")}]) == "move"
    assert decide("재경위", m, [{"id": "x", "summary": "재경위 전체회의", "start": at("10:00")}]) == "manual"
    assert decide("재경위", m, [{"id": "x", "summary": "점심 약속", "start": at("10:00")}]) == "add"
    hearing = [{"id": "x", "summary": "[인사청문회] 후보자", "start": at("10:00")}]
    assert decide("재경위", m, hearing) == "add"
    assert decide("재경위", m, hearing, ("인사청문회",)) == "manual"
    assert decide("재경위", m, [{"id": "x", "summary": "재경위 준비", "start": {"date": "2026-11-26"}}]) == "add"


def test_folder_date():
    assert folder_date("20261126_전체위") == "20261126"
    assert folder_date("인사청문_홍길동") is None
