"""구글 뉴스 RSS 조회. 파서는 순수 함수라 테스트에서 XML 문자열만 넣으면 된다.

키가 필요 없는 공개 RSS 를 쓴다(네이버 뉴스 API 는 별도 키가 필요하고 해외 IP 를 막을 수 있다).
"""
from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote
from xml.etree import ElementTree

import requests

KST = timezone(timedelta(hours=9))
BASE = "https://news.google.com/rss/search"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
_NOT_WORD = re.compile(r"[^0-9a-z가-힣]+")


@dataclass(frozen=True)
class Article:
    title: str        # 기사 제목 (끝의 " - 매체" 는 떼어 낸다)
    link: str         # 구글 뉴스 링크
    source: str       # 매체 이름
    published: str    # 발행 시각 ISO(KST). 못 읽으면 빈 문자열
    query: str        # 이 기사를 잡아낸 검색어
    group: str        # 검색어가 속한 묶음 (예: "의원 관련")


def search_url(query: str, days: int = 1) -> str:
    """검색어 하나의 RSS 주소. days 를 주면 그 기간 안의 기사만 받는다."""
    q = f"{query} when:{days}d" if days else query
    return f"{BASE}?q={quote(q)}&hl=ko&gl=KR&ceid=KR:ko"


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _to_kst(raw: str) -> str:
    try:
        return parsedate_to_datetime(raw).astimezone(KST).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return ""


def strip_source(title: str, source: str) -> str:
    """제목 끝의 " - 매체" 를 떼어 낸다. 기사 제목 자체에 매체가 붙어 두 번 나오는 경우가 있어 반복한다."""
    if not source:
        return title
    tail = f" - {source}"
    while title.endswith(tail) and len(title) > len(tail):
        title = title[: -len(tail)].strip()
    return title


def normalize_title(title: str) -> str:
    """중복 판정용 제목. 기호·공백·대소문자 차이를 지운다."""
    text = unicodedata.normalize("NFKC", title).lower()
    return _NOT_WORD.sub("", text)


def parse_rss(xml_text: str, query: str = "", group: str = "") -> list[Article]:
    """RSS 본문을 Article 목록으로. 제목·링크가 없는 항목은 버린다."""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise RuntimeError(f"뉴스 요청 실패: RSS 를 읽지 못했습니다 ({exc})") from exc

    out: list[Article] = []
    for item in root.iter("item"):
        title = _clean(item.findtext("title", ""))
        link = _clean(item.findtext("link", ""))
        if not title or not link:
            continue
        source = _clean(item.findtext("source", ""))
        title = strip_source(title, source)
        if not title:
            continue
        out.append(Article(title=title, link=link, source=source or "출처 미상",
                           published=_to_kst(item.findtext("pubDate", "")),
                           query=query, group=group))
    return out


class GoogleNews:
    """RSS 조회. 요청 간격과 재시도를 지킨다."""

    def __init__(self, *, delay: float = 1.0, retries: int = 3, timeout: int = 30, session=None):
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._last = 0.0

    def _wait(self) -> None:
        gap = self.delay - (time.monotonic() - self._last)
        if gap > 0:
            time.sleep(gap)
        self._last = time.monotonic()

    def fetch(self, query: str, *, group: str = "", days: int = 1) -> list[Article]:
        url = search_url(query, days)
        last: Exception | None = None
        for attempt in range(self.retries):
            self._wait()
            try:
                res = self.session.get(url, timeout=self.timeout)
                res.raise_for_status()
                return parse_rss(res.text, query=query, group=group)
            except Exception as exc:  # noqa: BLE001 - 재시도 후 한국어 문구로 바꿔 던진다
                last = exc
                if attempt < self.retries - 1:
                    time.sleep(self.delay * (attempt + 1))
        raise RuntimeError(f"뉴스 요청 실패: '{query}' 기사 목록을 받지 못했습니다 ({last})")
