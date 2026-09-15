"""hslib 핵심 로직 단위 테스트(외부 의존·픽스처 없이 자체 완결)."""
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hslib import filter as f  # noqa: E402
from hslib import state  # noqa: E402
from hslib.archive import sanitize  # noqa: E402
from hslib.download import build_download_url  # noqa: E402
from hslib.extract import extract_hwpx  # noqa: E402
from hslib.adapters import get_adapter  # noqa: E402
from hslib.adapters.gosi import parse_list as gosi_parse  # noqa: E402

FILT = {"include_keywords": ["동탄", "청계동", "장지동", "송동"],
        "exclude_dong": ["반송동", "석우동"], "star_keywords": ["청계동", "장지동"],
        "citywide_markers": ["화성시 전역"]}


def test_filter_star_and_include():
    r = f.match("청계동 542 도로구간 변경", "", FILT)
    assert r.included and r.is_star


def test_filter_substring_false_positive_excluded():
    # '송동' 이 '반송동' 안 substring 이지만 매칭되면 안 됨
    assert not f.match("반석산 정자 공사", "공사위치: 반송동 108", FILT).included


def test_filter_citywide_tagged():
    r = f.match("화성시 전역 주소정비", "", FILT)
    assert r.included and r.is_citywide


def test_state_is_new_numeric_and_lexicographic():
    assert state.is_new({"gosi": "100"}, "gosi", "101") is True
    assert state.is_new({"gosi": "100"}, "gosi", "100") is False
    assert state.is_new({"gnews": "46600"}, "gnews", "46700") is True


def test_sanitize_no_trailing_space():
    assert not sanitize("실시계획(변경) ").endswith(" ")
    assert sanitize("도로:구간/변경*고시?") == "도로_구간_변경_고시"


def test_build_download_url_preserves_slash():
    url = build_download_url("https://x/FileDown.jsp", "고시문.hwpx", "sys_1.hwpx", "/ntishome/a/b")
    assert "/ntishome/a/b" in url and "user_file_nm=" in url


def test_extract_hwpx_namespaced(tmp_path):
    p = tmp_path / "s.hwpx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Contents/section0.xml", "<hml><hp:p><hp:run><hp:t>청계동 도로</hp:t></hp:run></hp:p></hml>")
    assert "청계동 도로" in extract_hwpx(str(p))


def test_gosi_list_parse():
    html = ('<table><tbody><tr>'
            '<td>화성시 고시 제2026-1호</td>'
            '<td class="ta_lft"><a href="javascript:opGosiView(\'147984\');">청계동 도로</a></td>'
            '<td>토지정보과</td><td>2026-07-08</td><td></td></tr></tbody></table>')
    rows = gosi_parse(html)
    assert rows[0]["post_id"] == "147984" and rows[0]["dept"] == "토지정보과"


def test_registry():
    from hslib.adapters.gosi import GosiAdapter
    from hslib.adapters.bbs import BbsAdapter
    from hslib.adapters.gnews import GnewsAdapter
    assert isinstance(get_adapter("gosi"), GosiAdapter)
    assert isinstance(get_adapter("bbs"), BbsAdapter)
    assert isinstance(get_adapter("gnews"), GnewsAdapter)
