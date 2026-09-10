from open_api import OpenApi, parent_committee, rows_to_entries

ROWS = [
    {"CONFER_NUM": 57239, "TITLE": "제22대 제439회 제1차 정무위원회 (2026년 09월 03일)", "CLASS_NAME": "상임위원회",
     "DAE_NUM": 22, "COMM_NAME": "정무위원회", "CONF_DATE": "2026-09-03",
     "PDF_LINK_URL": "https://record.assembly.go.kr/assembly/viewer/minutes/download/pdf.do?id=57239", "CONF_ID": "N054437"},
    {"CONFER_NUM": 57239, "TITLE": "제22대 제439회 제1차 정무위원회 (2026년 09월 03일)", "CLASS_NAME": "상임위원회",
     "DAE_NUM": 22, "COMM_NAME": "정무위원회", "CONF_DATE": "2026-09-03",
     "PDF_LINK_URL": "https://record.assembly.go.kr/assembly/viewer/minutes/download/pdf.do?id=57239", "CONF_ID": "N054437"},
    {"CONFER_NUM": "57238", "TITLE": "제22대 제439회 제3차 예산결산특별위원회 결산심사소위원회 (2026년 09월 04일)",
     "CLASS_NAME": "예산결산특별위원회", "DAE_NUM": 22, "COMM_NAME": "예산결산특별위원회 결산심사소위원회",
     "CONF_DATE": "2026-09-04", "PDF_LINK_URL": "https://record.assembly.go.kr/assembly/viewer/minutes/download/pdf.do?id=57238"},
    {"CONFER_NUM": "57227", "TITLE": "제22대 제439회 제2차 국회본회의 (2026년 09월 03일)", "CLASS_NAME": "국회본회의",
     "DAE_NUM": "22", "CONF_DATE": "2026-09-03", "PDF_LINK_URL": None},
    {"CONFER_NUM": "1", "TITLE": "알 수 없는 종류", "CLASS_NAME": "국정감사", "COMM_NAME": "x", "PDF_LINK_URL": "u"},
]


def test_parent_committee_strips_subcommittee():
    assert parent_committee("국방위원회 예산결산심사소위원회") == "국방위원회"
    assert parent_committee("정무위원회") == "정무위원회"
    assert parent_committee("") == ""


def test_rows_to_entries_dedups_and_maps_fields():
    entries = rows_to_entries(ROWS, th=22)
    assert [e.id for e in entries] == [57239, 57238, 57227]      # 중복 제거, 미지원 종류 제외
    a, b, c = entries
    assert (a.cls, a.committee, a.sess, a.has_pdf, a.temp) == (2, "정무위원회", "439", True, None)
    assert (b.cls, b.committee) == (4, "예산결산특별위원회")
    assert (c.cls, c.committee, c.has_pdf) == (1, "국회본회의", False)


def test_entries_queries_both_apis(monkeypatch):
    api = OpenApi(key="k")
    calls = []

    def fake_rows(name, **params):
        calls.append((name, params))
        return [ROWS[0]] if name == "ncwgseseafwbuheph" else [ROWS[3]]

    monkeypatch.setattr(api, "rows", fake_rows)
    entries = api.entries(22, "2026-09")
    assert {e.id for e in entries} == {57239, 57227}
    assert all(p == {"DAE_NUM": 22, "CONF_DATE": "2026-09"} for _, p in calls)
    assert {n for n, _ in calls} == {"nzbyfwhwaoanttzje", "ncwgseseafwbuheph"}
