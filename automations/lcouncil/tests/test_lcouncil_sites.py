"""어댑터·저장소 규칙 테스트. 사이트에 접속하지 않고 가짜 Http 로 응답을 흘려 넣는다."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lcouncil_sites import Doc, EjournalSite, RecordSite, html_text  # noqa: E402
from lcouncil_store import LocalStore, relative_path  # noqa: E402


class FakeHttp:
    """url(+params) → 응답 본문. json() 은 문자열을 json 으로 푼다."""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def _key(self, url, params):
        return url + ("?" + "&".join(f"{k}={v}" for k, v in sorted(params.items())) if params else "")

    def get(self, url, params=None):
        self.calls.append(self._key(url, params))
        body = self.table[self._key(url, params)]

        class R:
            text = body
        return R()

    def json(self, url, params=None):
        return json.loads(self.get(url, params).text)


def test_ejournal_lists_docs_and_marks_temp():
    base = "https://x"
    http = FakeHttp({
        f"{base}/assem/search/simple/session.do": 'jobj.csNum = "12"; jobj.csNum = "11";',
        f"{base}/assem/search/simple/LoadingSession_Year.json?searchCsDaesoo=12&searchCtGroup=B":
            json.dumps([{"csNum": 410, "csTypeNm": "정례회"}]),
        f"{base}/assem/search/simple/LoadingList.json?searchCsSession=410&searchCtGroup=B":
            json.dumps([{"cdUid": 7250, "ctNm": "본회의", "cdChasoo": "3", "cdDate": "2024.06.07", "cdImsi": "N"},
                        {"cdUid": 7251, "ctNm": "본회의", "cdChasoo": "4", "cdDate": "2024.06.19", "cdImsi": "Y"}]),
        **{f"{base}/assem/search/simple/LoadingSession_Year.json?searchCsDaesoo=12&searchCtGroup={g}": "[]"
           for g in "STYK"},
    })
    site = EjournalSite(base, http)
    assert site.terms() == [12, 11]
    docs = list(site.iter_docs(12))
    assert [d.id for d in docs] == ["7250", "7251"]
    assert docs[0].date == "2024-06-07" and docs[0].order == "제3차" and docs[0].temp is False
    assert docs[1].temp is True
    assert docs[0].url.endswith("viewer.do?cdUid=7250")


def test_record_site_parses_tree():
    base = "https://s"
    http = FakeHttp({
        f"{base}/kr/assembly/session.do": '{"mode":"session","folder":"true","th":11,"lazy":"true"}, {"mode":"session","th":10}',
        f"{base}/record/sessionList.do?councilId=SEOUL&th=11":
            json.dumps([{"session": 336, "title": "제336회[정례회](2026.06.10 ~ 2026.06.24)"}]),
        f"{base}/record/committeeList.do?councilId=SEOUL&session=336&th=11":
            json.dumps([{"code": "A011", "title": "본회의"}]),
        f"{base}/record/orderList.do?code=A011&councilId=SEOUL&session=336&th=11":
            json.dumps([{"title": "<a href='/record/recordView.do?key=abc' target='_blank'>제1차(2026.06.11 목요일)</a>"},
                        {"title": "회의록 없음"}]),
    })
    site = RecordSite(base, http, "SEOUL")
    assert site.terms() == [11, 10]
    docs = list(site.iter_docs(11))
    assert len(docs) == 1
    d = docs[0]
    assert d.id == "abc" and d.session == 336 and d.session_type == "정례회"
    assert d.committee == "본회의" and d.order == "제1차" and d.date == "2026-06-11"
    assert d.url == f"{base}/record/recordView.do?key=abc"


def test_html_text_keeps_only_selected_box():
    html = "<html><body><div id='nav'>메뉴</div><div id='canvas'><p>○의장 홍길동</p><script>x()</script><p>개의를 선포합니다.</p></div></body></html>"
    t = html_text(html, "#canvas")
    assert "메뉴" not in t and "x()" not in t
    assert t.startswith("○의장 홍길동") and "개의를 선포합니다." in t


def test_local_store_new_then_replace_temp(tmp_path):
    doc = Doc(id="1", th=12, session=410, session_type="정례회", committee="본회의", order="제3차",
              date="2024-06-07", title="제410회 본회의 제3차", url="u", temp=True)
    store = LocalStore(tmp_path, "전북특별자치도의회")
    assert store.needs_fetch(doc) == "new"
    path, size = store.save_text(doc, "본문" * 10)
    store.record(doc, path, size)
    store.save_manifest()
    assert relative_path(doc) == ["제12대", "제410회", "본회의_제3차_2024-06-07.txt"]
    assert (tmp_path / "전북특별자치도의회" / "제12대" / "제410회" / "본회의_제3차_2024-06-07.txt").exists()
    # 같은 임시회의록은 건너뛰고, 확정본으로 바뀌면 교체
    assert store.needs_fetch(doc) is None
    final = Doc(**{**doc.__dict__, "temp": False})
    assert store.needs_fetch(final) == "replaced"
    # 다시 열어도 manifest 가 살아 있다
    again = LocalStore(tmp_path, "전북특별자치도의회")
    assert again.total_ok() == 1
