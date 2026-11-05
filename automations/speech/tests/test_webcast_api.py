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
