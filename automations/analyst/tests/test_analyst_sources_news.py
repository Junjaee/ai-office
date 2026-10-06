"""analyst_sources_news — 구글 뉴스 RSS 에서 기사 제목 받기(가짜 http)."""
import sys
import types
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analyst_sources_news import fetch_titles  # noqa: E402


def item(title, source, pub, link):
    return (f"<item><title>{title}</title><link>{link}</link><pubDate>{pub}</pubDate>"
            f"<source url=\"https://s.example\">{source}</source></item>")


RSS = ("<?xml version=\"1.0\"?><rss><channel>"
       + item("Oracle wins big deal - Reuters", "Reuters", "Fri, 03 Oct 2025 14:00:00 GMT", "https://n.example/1")
       + item("Oracle &amp; AI demand", "Bloomberg", "Thu, 02 Oct 2025 09:30:00 GMT", "https://n.example/2")
       + item("Oracle wins big deal - Reuters", "Reuters", "Fri, 03 Oct 2025 15:00:00 GMT", "https://n.example/3")   # 같은 제목
       + item("Old news", "AP", "Mon, 15 Sep 2025 09:00:00 GMT", "https://n.example/4")                          # 15일 지남
       + item("Insecure link", "AP", "Fri, 03 Oct 2025 10:00:00 GMT", "http://n.example/5")                       # http
       + "</channel></rss>")


def _raise(status):
    raise RuntimeError(f"HTTP {status}")


class Http:
    def __init__(self, status=200, text=RSS):
        self.status, self.text, self.calls = status, text, []

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append((url, params))
        return types.SimpleNamespace(status_code=self.status, text=self.text,
                                     raise_for_status=lambda: _raise(self.status) if self.status >= 400 else None)


def test_filters_dedups_orders_and_strips_source():
    out = fetch_titles("Oracle Corp", "2025-10-03", http=Http())
    assert out == [
        {"title": "Oracle wins big deal", "source": "Reuters", "date": "2025-10-03", "url": "https://n.example/1"},
        {"title": "Oracle & AI demand", "source": "Bloomberg", "date": "2025-10-02", "url": "https://n.example/2"},
    ]


def test_limit_and_days():
    assert len(fetch_titles("Oracle Corp", "2025-10-03", http=Http(), limit=1)) == 1
    assert len(fetch_titles("Oracle Corp", "2025-10-03", http=Http(), days=30)) == 3   # 15일 지난 것도 들어온다


def test_query_is_company_name_plus_stock_only():
    http = Http()
    fetch_titles("Johnson & Johnson", "2025-10-03", http=http)
    url, params = http.calls[0]
    assert parse_qs(urlparse(url).query)["q"] == ["Johnson & Johnson stock"]   # & 가 따로 갈라지지 않게 인코딩됐다


def test_http_error_raises():
    with pytest.raises(RuntimeError):
        fetch_titles("Oracle Corp", "2025-10-03", http=Http(status=500, text=""))


def test_bad_xml_raises():
    with pytest.raises(Exception):
        fetch_titles("Oracle Corp", "2025-10-03", http=Http(text="<rss"))


def test_prints_nothing(capsys):
    fetch_titles("Oracle Corp", "2025-10-03", http=Http())
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_kr_locale_uses_korean_edition_and_name_plus_stock_word():
    http = Http()
    fetch_titles("삼성전자", "2025-10-03", http=http, locale="kr")
    url, _ = http.calls[0]
    q = urlparse(url).query
    assert parse_qs(q)["q"] == ["삼성전자 주식"] and "hl=ko" in q and "gl=KR" in q and "ceid=KR:ko" in q
    http = Http(); fetch_titles("Oracle", "2025-10-03", http=http)
    assert "hl=en-US" in http.calls[0][0]   # 기본은 미국 그대로
