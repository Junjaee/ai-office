"""질의순서 표 읽기 — HWP→HTML 변환 결과(xhtml) 파싱과 지메일 첨부 고르기. 네트워크·실물 HWP 없음."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from order_hwp import fetch_question_order, find_order_attachment, parse_order_html  # noqa: E402


def row(*cells):
    return "<tr>" + "".join(f"<td><p>{c}</p></td>" for c in cells) + "</tr>"


def test_parse_two_column_row():
    html = "<html><body><table>" + row("순번", "질의위원", "", "비고", "순번", "질의위원", "", "비고") \
        + row("1", "김남준", "위원", "더불어민주당", "12", "이춘석", "위원", "더불어민주당") + "</table></body></html>"
    assert parse_order_html(html) == [(1, "김남준", "더불어민주당"), (12, "이춘석", "더불어민주당")]


def test_parse_single_column_rows():
    html = ("<html><body><p>&lt;종합정책질의&gt;-2일차 2026년 11월 5일(목)</p><table>"
            + row("순번", "위원명", "교섭단체", "지역구", "비고")
            + row("12", "권한영", "국민의힘", "부산 서구동구", "")
            + row("13", "이준석", "개혁신당", "경기 화성 을", "")
            + row("14", "서지영", "국민의힘", "부산 동래구", "")
            + "</table></body></html>")
    assert parse_order_html(html) == [(12, "권한영", "국민의힘"), (13, "이준석", "개혁신당"), (14, "서지영", "국민의힘")]


def test_parse_ignores_non_name_cells():
    html = "<table>" + row("1", "오전 10시", "비고") + row("2", "홍길동", "무소속") + "</table>"
    assert parse_order_html(html) == [(2, "홍길동", "무소속")]


class FakeService:
    """search_messages/message_meta/download_attachment 가 쓰는 최소 Gmail 흉내."""

    def __init__(self, messages):
        self.store = messages   # id → {"ts": int, "parts": [(name, attachmentId)]}

    def users(self):
        return self

    def messages(self):  # noqa: D401 - googleapiclient 흉내
        return self

    def list(self, userId, q, maxResults):
        ids = sorted(self.store, key=lambda i: -self.store[i]["ts"])
        return _Exec({"messages": [{"id": i} for i in ids]})

    def get(self, userId, id, format):
        m = self.store[id]
        parts = [{"filename": n, "body": {"attachmentId": a, "size": 10}} for n, a in m["parts"]]
        return _Exec({"id": id, "threadId": id, "internalDate": str(m["ts"]),
                      "payload": {"headers": [{"name": "Subject", "value": "질의순서"}, {"name": "From", "value": "fec"},
                                              {"name": "Date", "value": "Wed, 05 Nov 2026 09:00:00 +0900"}],
                                  "parts": parts}})


class _Exec:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return self.data


def test_find_order_attachment_picks_latest_with_keyword():
    svc = FakeService({
        "old": {"ts": 1000, "parts": [("질의순서(261103).hwp", "att-old")]},
        "new": {"ts": 2000, "parts": [("회의자료.pdf", "att-x"), ("2027_예산안_질의순서(전체)_261105.hwp", "att-new")]},
        "none": {"ts": 3000, "parts": [("안건.hwp", "att-y")]},
    })
    assert find_order_attachment(svc, "from:budget@assembly.go.kr", 3) == ("new", "att-new")


def test_find_order_attachment_none_when_no_match():
    svc = FakeService({"a": {"ts": 1, "parts": [("안건.hwp", "x")]}})
    assert find_order_attachment(svc, "from:x", 3) is None


def test_fetch_returns_none_when_no_mail(monkeypatch):
    import order_hwp

    monkeypatch.setattr(order_hwp, "gmail_service", lambda: FakeService({}))
    assert fetch_question_order("from:x", 3) is None


def test_hwp_to_xhtml_gives_pyhwp_a_file_path(monkeypatch, tmp_path):
    """pyhwp 의 Hwp5File 은 BytesIO 를 못 받는다(실물 파일로 확인 2026-11-05) — 임시 파일 경로를 줘야 한다."""
    import order_hwp

    seen = {}

    class FakeHwp5File:
        def __init__(self, src):
            seen["src"] = src

    class FakeTransform:
        def transform_hwp5_to_dir(self, hwp, outdir):
            Path(outdir, "index.xhtml").write_text("<table><tr><td>1</td><td>홍길동</td></tr></table>", encoding="utf-8")

    monkeypatch.setattr(order_hwp, "Hwp5File", FakeHwp5File)
    monkeypatch.setattr(order_hwp, "HTMLTransform", FakeTransform)
    assert "홍길동" in order_hwp.hwp_to_xhtml(b"HWP Document File")
    assert isinstance(seen["src"], str) and seen["src"].endswith(".hwp")
