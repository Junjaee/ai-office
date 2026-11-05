"""요약 호출·위원 블록 렌더 — 요약기는 가짜(고정 dict / 예외). 모양은 사용자 예시(2026-11-05)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from segmenter import Segment  # noqa: E402
from summarizer import MemberSummary, failed_summary, load_attendees, render_member, summarize  # noqa: E402


class FakeLLM:
    def __init__(self, data=None, exc=None):
        self.data, self.exc, self.calls = data, exc, []

    def json(self, *, system, user, schema):
        self.calls.append({"system": system, "user": user, "schema": schema})
        if self.exc:
            raise self.exc
        return self.data


def seg(member="이준석", party="개혁신당", seq=13, lines=("홍지선 장관님 어디 계시지요", "광역버스 노선 5개로 줄었습니다")):
    return Segment(seq, member, party, 0.0, 100.0, list(lines))


def test_summarize_passes_meeting_member_and_attendees_to_prompt():
    llm = FakeLLM({"topics": [{"title": "광역버스", "lines": ["줄었다고 지적했음"]}]})
    ms = summarize(seg(), "제439회 예산결산특별위원회", ["홍지선 국토교통부 장관", "박홍근 기획예산처 장관"], llm, topics_max=8)
    call = llm.calls[0]
    assert "[회의: 제439회 예산결산특별위원회]" in call["user"] and "[위원: 이준석]" in call["user"]
    assert "광역버스 노선 5개로 줄었습니다" in call["user"]
    assert "홍지선 국토교통부 장관, 박홍근 기획예산처 장관" in call["system"]
    assert call["schema"]["properties"]["topics"]["maxItems"] == 8
    assert ms.member == "이준석" and ms.seq == 13 and ms.topics[0]["title"] == "광역버스"
    assert ms.chars == len(seg().text()) and ms.failed is False


def test_render_member_matches_user_sample():
    ms = MemberSummary(13, "이준석", "개혁신당", [
        {"title": "광역버스 준공영제 신설 노선 축소", "lines": ["2026년 5개로 줄었다고 지적했음", "예산 확대를 요구했음"]},
        {"title": "GTX-A 운행횟수 축소 우려", "lines": ["87회까지 거론된다고 지적했음"]},
    ], chars=1000)
    assert render_member(ms) == (
        "개혁신당 이준석\n"
        "1. 광역버스 준공영제 신설 노선 축소\n"
        "◯ 2026년 5개로 줄었다고 지적했음\n"
        "◯ 예산 확대를 요구했음\n"
        "2. GTX-A 운행횟수 축소 우려\n"
        "◯ 87회까지 거론된다고 지적했음"
    )


def test_render_failed():
    ms = failed_summary(seg())
    assert ms.failed and ms.topics == []
    assert render_member(ms) == f"개혁신당 이준석\n요약 실패 — 발언 약 {len(seg().text())}자"


def test_render_no_call_flag_in_header():
    s = seg()
    s.flag = "no_call"
    ms = MemberSummary(14, "서지영", "국민의힘", [{"title": "제목", "lines": ["줄"]}], chars=10, flag="no_call")
    assert render_member(ms).splitlines()[0] == "국민의힘 서지영 (호명 못 잡음)"
    assert failed_summary(s).flag == "no_call"


def test_render_without_party():
    ms = MemberSummary(3, "김남준", "", [{"title": "제목", "lines": ["줄"]}], chars=10)
    assert render_member(ms).splitlines()[0] == "김남준"


def test_load_attendees_reads_yaml(tmp_path):
    p = tmp_path / "a.yaml"
    p.write_text("attendees:\n  - \"홍지선 국토교통부 장관\"\n  - 국무총리\n", encoding="utf-8")
    assert load_attendees(str(p)) == ["홍지선 국토교통부 장관", "국무총리"]
