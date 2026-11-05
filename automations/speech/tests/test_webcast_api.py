"""국회 인터넷의사중계 응답 파싱 — 네트워크 없이, 2026-11-05 실제 응답 조각으로."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import webcast_api as w  # noqa: E402

# live_list.asp 본문의 일부(2026-11-05 22:58). 앞뒤에 다른 채널과 자바스크립트가 섞여 온다
SAMPLE = (
    'var list=[{"xcode":"10","xcgcd":"DCM000010224390200","xname":"본회의","xstat":"0","xdesc":"방송종료","xsubj":"제439회 국회(정기회) 제02차 본회의 [00:00]"},'
    '{"xcode":"21","xcgcd":"DCM000021224390401","xname":"예결위","xbill":"9700049","xbttn":"속개","xstat":"1",'
    '"xthmb":"//thumb.webcast.go.kr/api/thumbnail/special","xsubj":"제439회 국회(정기회) 제04차 예산결산특별위원회 [00:00]",'
    '"xdesc":"속개","xsami":"1","xqvod":"1","mc":"21"}];'
)


def test_parse_live_list_picks_channel_21():
    info = w.channel_info("21", SAMPLE)
    assert info["xcgcd"] == "DCM000021224390401"
    assert info["xname"] == "예결위"


def test_channel_info_none_when_missing():
    assert w.channel_info("65", SAMPLE) is None


def test_is_live_only_when_xstat_1():
    assert w.is_live({"xstat": "1"})
    assert not w.is_live({"xstat": "0"})
    assert not w.is_live(None)


def test_caption_kind():
    assert w.caption_kind("wss://smi-dw.webcast.go.kr/10") == "stt"
    assert w.caption_kind("wss://smi-hy2.webcast.go.kr/65") == "stt"
    assert w.caption_kind("wss://smi1.webcast.go.kr/21") == "stt"
    assert w.caption_kind("wss://smiai.webcast.go.kr:8091/aistt/special") == "ai"


def test_parse_xsami():
    assert w.parse_xsami('var a={"xsami":"wss://x/y","b":1}') == "wss://x/y"
    assert w.parse_xsami("") == ""


def test_meeting_title_strips_clock():
    assert w.meeting_title({"xsubj": "제439회 국회(정기회) 제04차 예산결산특별위원회 [00:00]"}) \
        == "제439회 국회(정기회) 제04차 예산결산특별위원회"
    assert w.meeting_title({"xsubj": "제목만"}) == "제목만"


def test_parse_members():
    html = 'seat({"mno":"1","mname":"김남준","mdang":"더불어민주당"}); seat({"mname":"이춘석","mdang":"더불어민주당"});'
    assert w.parse_members(html) == [("김남준", "더불어민주당"), ("이춘석", "더불어민주당")]
    assert w.parse_members("") == []


class FlakySession:
    """처음 n 번은 연결이 끊기고 그 뒤에 200 — GitHub 서버에서 live_list 가 가끔 응답 없이 끊겼다(2026-11-06 첫 실행)."""

    def __init__(self, fail_times):
        import requests

        self.fail_times, self.calls, self.exc = fail_times, 0, requests.exceptions.ConnectionError("끊김")

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc

        class R:
            status_code, text = 200, "ok"

            def raise_for_status(self):
                pass
        return R()


def test_fetch_retries_on_connection_error(monkeypatch):
    monkeypatch.setattr(w.time, "sleep", lambda s: None)
    s = FlakySession(2)
    assert w.fetch("live_list.asp", None, session=s) == "ok"
    assert s.calls == 3


def test_fetch_gives_up_after_retries(monkeypatch):
    import requests

    monkeypatch.setattr(w.time, "sleep", lambda s: None)
    s = FlakySession(10)
    try:
        w.fetch("live_list.asp", None, session=s)
        assert False, "예외가 나야 한다"
    except requests.exceptions.ConnectionError:
        pass
    assert s.calls == 3


def test_get_headers_have_no_origin():
    """일반 GET 에는 Origin 을 붙이지 않는다(웹소켓 접속에만). 서버가 끊은 원인 후보를 하나 줄인다."""
    assert "Origin" not in w.GET_HEADERS and "User-Agent" in w.GET_HEADERS and "Referer" in w.GET_HEADERS
    assert w.HEADERS["Origin"] == "https://assembly.webcast.go.kr"
