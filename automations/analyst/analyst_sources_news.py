"""기사 제목 — 구글 뉴스 RSS(키 불필요)에서 회사 이름으로 최근 제목을 받는다. 표준 라이브러리만 쓴다.

매일 실행(공개 Actions 로그) 안에서 불리므로 아무것도 출력하지 않는다. 실패는 예외로 올린다.
검색어에는 회사 이름 + " stock"(국내는 " 주식") 외에는 아무것도 넣지 않는다(종목 기호·내용 금지).
"""
from __future__ import annotations

from datetime import date as _date, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote
from xml.etree import ElementTree

import requests

TIMEOUT = 30
BASE = "https://news.google.com/rss/search"
USER_AGENT = "Mozilla/5.0 (compatible; ai-office-analyst)"


def _parse(xml_text: str) -> list[dict]:
    out = []
    for it in ElementTree.fromstring(xml_text).iter("item"):
        title = " ".join((it.findtext("title") or "").split())
        url = (it.findtext("link") or "").strip()
        source = " ".join((it.findtext("source") or "").split())
        try:
            day = parsedate_to_datetime(it.findtext("pubDate") or "").date().isoformat()
        except (TypeError, ValueError):
            continue
        tail = f" - {source}"
        if source and title.endswith(tail) and len(title) > len(tail):
            title = title[: -len(tail)].strip()
        if title and url.startswith("https://"):
            out.append({"title": title, "source": source, "date": day, "url": url})
    return out


EDITION = {"us": ("stock", "hl=en-US&gl=US&ceid=US:en"), "kr": ("주식", "hl=ko&gl=KR&ceid=KR:ko")}


def fetch_titles(name: str, as_of: str, http=requests, days: int = 14, limit: int = 8, locale: str = "us") -> list[dict]:
    """[{title, source, date, url}] — 최근 것부터, 같은 제목은 하나, as_of - days 이후만, https 링크만. locale: us(영문) | kr(한국어, `<이름> 주식`)."""
    word, edition = EDITION[locale]
    url = f"{BASE}?q={quote(name + ' ' + word, safe='')}&{edition}"
    r = http.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    r.raise_for_status()
    cutoff = (_date.fromisoformat(as_of) - timedelta(days=days)).isoformat()
    seen, out = set(), []
    for a in sorted(_parse(r.text), key=lambda a: a["date"], reverse=True):   # 안정 정렬 — 같은 날은 RSS 순서
        if a["date"] < cutoff or a["title"] in seen:
            continue
        seen.add(a["title"])
        out.append(a)
    return out[:limit]
