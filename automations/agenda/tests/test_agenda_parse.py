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


# ── 표 머리글이 끼고 연도가 없는 양식 (2026-11-27 제12차) ──────────────────

TABLE = ("제439회국회(정기회) 의 사 일 정(안) 제12차 재정경제기획위원회 "
         "일 시 안 건 명 비 고 11. 30.(월) 14:00 1. 국세청장후보자 인사청문요청안")


def test_parse_header_reads_table_form_with_folder_year():
    m = parse_header(TABLE, "20261130")
    assert (m.n, m.body) == (12, "재정경제기획위원회")
    assert m.start == datetime(2026, 11, 30, 14, 0, tzinfo=KST)


def test_parse_header_needs_folder_date_when_year_missing():
    assert parse_header(TABLE) is None                 # 연도를 구할 데가 없다
    assert parse_header(TABLE, "2026") is None         # 8자리가 아니다
    assert parse_header(TABLE, "20261201") is None     # 폴더가 말하는 날과 다르다 — 넣지 않는다


def test_parse_header_prefers_year_in_text():
    """본문에 연도가 있으면 폴더 날짜는 보지 않는다(폴더 이름이 잘못돼도 본문이 이긴다)."""
    m = parse_header("제11차 재정경제기획위원회 2026. 11. 26.(목) 10:00", "20260101")
    assert m.start == datetime(2026, 11, 26, 10, 0, tzinfo=KST)


# ── 장소·안건을 일정에 담기 (사용자 결정 2026-11-27) ──────────────────────

BODY = ("捤獥 汤捯 제439회국회(정기회) 의 사 일 정(안) 󰠲󰠲󰠲 제12차 재정경제기획위원회 氠瑢 "
        "일 시 안 건 명 비 고 11. 30.(월) 14:00 "
        "1. (ZZ22175) 국세청장후보자(안덕수) 인사청문요청안 "
        "2. 국세청장후보자(안덕수) 인사청문경과보고서 채택의 건 "
        "3. 조세소위원회 통과 법률안 재경위 전체회의실 (본관 430호) "
        "※ 상세 안건은 확정되는 대로 추후 공지해 드리도록 하겠습니다.")


def test_room_of_finds_place():
    from agenda_parse import room_of
    assert room_of(BODY) == "본관 430호"
    assert room_of("제12차 재정경제기획위원회 14:00") == ""      # 없으면 빈 칸


def test_clean_body_drops_junk_and_breaks_lines():
    from agenda_parse import clean_body
    lines = clean_body(BODY).split("\n")
    assert "捤獥" not in lines[0] and "󰠲" not in lines[0]      # 한글 변환 찌꺼기는 버린다
    assert lines[2].startswith("1. (ZZ22175)")
    assert lines[4] == "3. 조세소위원회 통과 법률안"            # 비고 칸이 안건에 들러붙지 않는다
    assert lines[5] == "재경위 전체회의실 (본관 430호)"
    assert lines[6].startswith("※")


def test_clean_body_leaves_unknown_shape_alone():
    """끊을 자리가 안 보이면 그냥 둔다 — 억지로 쪼개 엉뚱한 데를 자르지 않는다."""
    from agenda_parse import clean_body
    assert clean_body("회의 일정 안내드립니다") == "회의 일정 안내드립니다"


def test_build_event_carries_room_and_agenda():
    from agenda_parse import build_event
    m = parse_header(BODY, "20261130")
    ev = build_event("재경위", m, "18:00", BODY)
    assert ev["summary"] == "[재경위] 제12차 전체회의 (본관 430호)"
    assert ev["location"] == "본관 430호"
    assert "국세청장후보자(안덕수) 인사청문요청안" in ev["description"]
    assert "drive.google.com" not in ev["description"]        # 회의 폴더 링크는 넣지 않는다


def test_build_event_without_room():
    from agenda_parse import build_event
    m = parse_header(HEAD)
    ev = build_event("재경위", m, "18:00", HEAD)
    assert ev["summary"] == "[재경위] 제11차 전체회의"          # 장소를 못 찾으면 괄호 없이
    assert ev["location"] == ""


def test_agenda_text_keeps_only_items():
    from agenda_parse import agenda_text
    lines = agenda_text(BODY).split("\n")
    assert lines == [
        "1. (ZZ22175) 국세청장후보자(안덕수) 인사청문요청안",
        "2. 국세청장후보자(안덕수) 인사청문경과보고서 채택의 건",
        "3. 조세소위원회 통과 법률안",
        "※ 상세 안건은 확정되는 대로 추후 공지해 드리도록 하겠습니다.",
    ]
    assert "일 시 안 건 명 비 고" not in agenda_text(BODY)   # 표 머리글은 뺀다
    assert "11. 30.(월)" not in agenda_text(BODY)            # 날짜는 안건이 아니다


def test_agenda_text_falls_back_to_whole_body():
    """안건 줄을 못 찾으면 본문 전체 — 양식이 다른 위원회에서 설명이 비지 않게."""
    from agenda_parse import agenda_text
    assert agenda_text("제3차 전체회의 안내드립니다") == "제3차 전체회의 안내드립니다"
