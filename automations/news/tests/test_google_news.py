"""RSS 파싱과 제목 정리 — 네트워크 없이 XML 문자열로만 확인한다."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from google_news import normalize_title, parse_rss, search_url, strip_source  # noqa: E402

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title>천하람 "강신철 사퇴하라" - 머니투데이 - 머니투데이</title>
  <link>https://news.google.com/rss/articles/AAA</link>
  <pubDate>Wed, 09 Sep 2026 23:10:00 GMT</pubDate>
  <source url="https://mt.co.kr">머니투데이</source>
</item>
<item>
  <title>재경위 국정감사 일정 확정 - 연합뉴스</title>
  <link>https://news.google.com/rss/articles/BBB</link>
  <pubDate>Thu, 10 Sep 2026 01:00:00 GMT</pubDate>
  <source url="https://yna.co.kr">연합뉴스</source>
</item>
<item>
  <title>링크가 없는 항목</title>
  <link></link>
</item>
</channel></rss>
"""


def test_parse_rss_reads_title_source_and_kst_time():
    items = parse_rss(RSS, query="이준석", group="의원 관련")
    assert len(items) == 2                      # 링크 없는 항목은 버린다
    first = items[0]
    assert first.title == '천하람 "강신철 사퇴하라"'   # 매체가 두 번 붙어도 모두 떼어 낸다
    assert first.source == "머니투데이"
    assert first.published == "2026-09-10T08:10:00+09:00"   # GMT → KST
    assert (first.query, first.group) == ("이준석", "의원 관련")


def test_parse_rss_broken_xml_raises_news_error():
    with pytest.raises(RuntimeError, match="뉴스 요청 실패"):
        parse_rss("<rss><channel><item>")


def test_search_url_has_korean_locale_and_period():
    url = search_url("이준석 의원", days=2)
    assert "hl=ko&gl=KR&ceid=KR:ko" in url
    assert "when%3A2d" in url


@pytest.mark.parametrize("title,source,expected", [
    ("제목 - 연합뉴스", "연합뉴스", "제목"),
    ("제목 - 연합뉴스 - 연합뉴스", "연합뉴스", "제목"),
    ("연합뉴스", "연합뉴스", "연합뉴스"),          # 제목이 통째로 매체면 그대로 둔다
    ("제목", "", "제목"),
])
def test_strip_source(title, source, expected):
    assert strip_source(title, source) == expected


def test_normalize_title_ignores_marks_and_spaces():
    assert normalize_title('천하람 "강신철" 사퇴') == normalize_title("천하람 강신철 사퇴")
    assert normalize_title("A B") != normalize_title("A C")
