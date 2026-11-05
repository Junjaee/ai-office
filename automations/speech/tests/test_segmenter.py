"""호명 판정·구간 자르기 — 설계 5절, 2026-11-05 예결위 실측 문장 그대로."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from captions import Caption  # noqa: E402
from segmenter import Segment, Segmenter, detect_call, detect_close  # noqa: E402

R = {"권한영": (12, "국민의힘"), "이준석": (13, "개혁신당"), "서지영": (14, "국민의힘")}
NAMES = set(R)
T0 = 1_762_000_000.0  # 임의의 기준 시각(epoch)


def feed_all(seg: Segmenter, items: list[tuple[float, str]]) -> list[tuple]:
    out: list[tuple] = []
    for dt, text in items:
        out.extend(seg.feed(Caption(T0 + dt, text)))
    return out


def test_call_split_over_two_lines():
    s = Segmenter(R, "이준석")
    ev = feed_all(s, [
        (0, "권한영 위원님 수고하셨습니다 다음은 경기 화성을의"),
        (3, "개혁신당 이준석 위원님 질의하여 주십시오"),
        (10, "홍지선 장관님 어디 계시지요"),
    ])
    assert ("special_call", "이준석") in ev
    assert s.current is not None and s.current.member == "이준석" and s.current.seq == 13
    assert s.current.party == "개혁신당"
    assert s.current.lines == ["홍지선 장관님 어디 계시지요"]


def test_colleague_mention_is_not_call():
    assert detect_call("존경하는 이준석 위원님 말씀처럼 저도 그렇게 봅니다", NAMES, "이준석") is None


def test_name_not_in_roster_ignored():
    assert detect_call("김철수 위원님 질의하여 주십시오", NAMES, "이준석") is None


def test_special_called_even_if_not_in_roster():
    assert detect_call("이준석 위원님 질의해 주시기 바랍니다", {"권한영"}, "이준석") == "이준석"


def test_call_variants():
    assert detect_call("다음은 서지영 위원님 질의하겠습니다", NAMES, "이준석") == "서지영"
    assert detect_call("권한영 위원 질의하십시오", NAMES, "이준석") == "권한영"


def test_done_closes_without_opening():
    s = Segmenter(R, "이준석")
    ev = feed_all(s, [
        (0, "서지영 위원님 질의하여 주십시오"),
        (5, "장관님 한 가지 묻겠습니다"),
        (60, "서지영 위원님 수고하셨습니다 홍재선 장관님"),
        (70, "장관 답변 이어서 말씀드리면"),      # 호명 없는 사회자·장관 말 — 어디에도 안 붙는다
    ])
    closed = [e[1] for e in ev if e[0] == "close"]
    assert len(closed) == 1 and closed[0].member == "서지영" and closed[0].lines == ["장관님 한 가지 묻겠습니다"]
    assert closed[0].ended_at == T0 + 60
    assert s.current is None


def test_second_call_same_member_new_seq():
    s = Segmenter(R, "이준석")
    ev = feed_all(s, [
        (0, "서지영 위원님 질의하여 주십시오"),
        (100, "서지영 위원님 수고하셨습니다"),
        (200, "보충질의 서지영 위원님 질의하여 주십시오"),
    ])
    closed = [e[1] for e in ev if e[0] == "close"]
    assert closed[0].seq == 14
    assert s.current is not None and s.current.seq == 15


def test_25min_rule_flags_no_call():
    s = Segmenter(R, "이준석", max_minutes=25)
    ev = feed_all(s, [
        (0, "권한영 위원님 질의하여 주십시오"),
        (60, "질의 내용"),
        (26 * 60, "아직도 이어지는 말"),
    ])
    closed = [e[1] for e in ev if e[0] == "close"]
    assert len(closed) == 1 and closed[0].flag == "no_call" and closed[0].lines == ["질의 내용"]
    assert s.current is None


def test_recess_and_adjourn():
    assert detect_close("잠시 정회를 선포합니다") == "recess"
    assert detect_close("이상으로 오늘 회의를 마치겠습니다 산회를 선포합니다") == "adjourn"
    assert detect_close("이준석 위원님 수고하셨습니다") == "done"
    assert detect_close("그냥 평범한 질의 문장") is None
    s = Segmenter(R, "이준석")
    ev = feed_all(s, [(0, "권한영 위원님 질의하여 주십시오"), (30, "한 줄"), (40, "산회를 선포합니다")])
    assert [e[0] for e in ev] == ["close", "adjourn"]


def test_lines_before_first_call_dropped():
    s = Segmenter(R, "이준석")
    ev = feed_all(s, [(0, "회의를 시작하겠습니다"), (5, "안건을 상정합니다"), (10, "권한영 위원님 질의하여 주십시오")])
    assert ev == []
    assert s.current is not None and s.current.lines == []


def test_roster_without_seq_counts_from_one():
    s = Segmenter({"김남준": (0, "더불어민주당"), "이춘석": (0, "더불어민주당")}, "이준석")
    feed_all(s, [(0, "김남준 위원님 질의하여 주십시오")])
    assert s.current.seq == 1
    feed_all(s, [(100, "이춘석 위원님 질의하여 주십시오")])
    assert s.current.seq == 2


def test_restore_continues_open_segment():
    s = Segmenter(R, "이준석")
    s.restore(Segment(14, "서지영", "국민의힘", T0, None, ["이전 줄"]), {12, 13, 14})
    feed_all(s, [(10, "이어지는 줄")])
    assert s.current.lines == ["이전 줄", "이어지는 줄"]
    feed_all(s, [(20, "권한영 위원님 질의하여 주십시오")])
    assert s.current.seq == 15     # 12·13·14 는 이미 썼으니 그 뒤


def test_empty_roster_accepts_any_name():
    """질의순서도 의석 명단도 못 받은 날 — 이름을 가릴 수 없으니 호명 문장이면 받는다."""
    assert detect_call("김철수 위원님 질의하여 주십시오", set(), "이준석") == "김철수"


def test_close_words_inside_speech_are_not_close():
    """'산회'·'휴식' 한 단어는 발언 속에도 나온다 — 선포·하겠 같은 사회자 어미가 있어야 닫는다."""
    assert detect_close("산회 이후에 다시 논의하겠습니다") is None
    assert detect_close("주민들이 휴식 공간이 없다고 합니다") is None
    assert detect_close("휴식과 합계를 위해 잠시 정회하였다가 10시 40분에 속개하겠습니다") == "recess"
    assert detect_close("그러면 오늘 회의는 이것으로 마치겠습니다 산회를 선포합니다") == "adjourn"


def test_done_and_next_call_in_one_line():
    """사회자가 한 호흡에 "수고하셨습니다 … 다음은 ○○ 위원님 질의하여 주십시오" — 닫고 바로 새 구간을 열어야 한다(검토 1)."""
    s = Segmenter(R, "이준석")
    feed_all(s, [(0, "권한영 위원님 질의하여 주십시오"), (10, "질의 한 줄")])
    ev = feed_all(s, [(20, "권한영 위원님 수고하셨습니다 다음은 개혁신당 이준석 위원님 질의하여 주십시오")])
    assert [e[0] for e in ev] == ["close", "special_call"]
    assert ev[0][1].member == "권한영" and ev[0][1].lines == ["질의 한 줄"]
    assert s.current is not None and s.current.member == "이준석" and s.current.seq == 13
