"""조사 — 소재와 같은 주제를 다룬 기사·블로그 글을 찾아 본문과 사진을 모은다 (글쓰기 근거 + 카드 이미지 후보).

- 검색: Bing 뉴스 RSS (무료, 키 없음, 원문 주소 그대로). 구글 뉴스 RSS 는 링크가 암호화돼 원문을 못 열어 쓰지 않는다.
- '조회수 높은 글' 은 공개 지표가 없어 고를 수 없다. 대신 검색 상위(관련도) + 공식 출처를 앞에 둔다.
- 사진은 (1) 소재 원문·공식 링크의 이미지 (2) 관련 기사의 대표 이미지(og:image)·본문 이미지 (3) 공식 페이지 캡처 순으로 후보를 만든다.
  후보마다 어디서 왔는지(source_url)를 남겨 카드에 '사진: 출처' 를 찍는다.
"""
from __future__ import annotations

import re
import time
import urllib.parse
from html import unescape

import requests

from insta_sources import UA, fetch_article

BING_NEWS = "https://www.bing.com/news/search?q={q}&format=rss&setlang={lang}"


def search_news(query: str, *, lang: str = "ko-kr", limit: int = 8, timeout: int = 20) -> list[dict]:
    """Bing 뉴스 RSS 검색 → [{title, link, source, published, image}]. 실패하면 빈 목록."""
    import feedparser

    url = BING_NEWS.format(q=urllib.parse.quote(query), lang=lang)
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
        r.raise_for_status()
    except Exception:  # noqa: BLE001
        return []
    feed = feedparser.parse(r.text)
    rows = []
    for e in feed.entries[:limit]:
        link = _unwrap_bing(str(e.get("link", "") or ""))
        if not link.startswith("http"):
            continue
        image = ""
        # Bing 은 <News:Image> 로 대표 이미지를 주기도 한다
        for k in ("news_image", "image"):
            v = e.get(k)
            if isinstance(v, str) and v.startswith("http"):
                image = v
            elif isinstance(v, dict) and str(v.get("href", "")).startswith("http"):
                image = v["href"]
        src = e.get("source")
        rows.append({"title": unescape(str(e.get("title", "") or "")).strip(), "link": link,
                     "source": str(src.get("title", "")) if isinstance(src, dict) else "",
                     "published": str(e.get("published", "") or ""), "image": image})
    return rows


def _unwrap_bing(link: str) -> str:
    """bing.com/news/apiclick... 형태면 안의 url= 값을 꺼낸다."""
    if "bing.com" in link and "url=" in link:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
        if q.get("url"):
            return q["url"][0]
    return link


def related_articles(queries: list[str], *, exclude: set[str] | None = None, max_articles: int = 6,
                     progress=print) -> list[dict]:
    """검색어들로 관련 기사를 찾아 본문·이미지까지 읽는다. [{title, link, source, text, images:[{url, alt}], error?}]"""
    exclude = set(exclude or ())
    seen: set[str] = set()
    picked: list[dict] = []
    for q in queries:
        lang = "en-us" if re.fullmatch(r"[\x00-\x7f]+", q) else "ko-kr"
        rows = search_news(q, lang=lang)
        progress(f"검색 '{q}' → {len(rows)}건")
        for row in rows:
            key = re.sub(r"[#?].*$", "", row["link"]).rstrip("/")
            if key in seen or key in exclude:
                continue
            seen.add(key)
            picked.append(row)
            if len(picked) >= max_articles:
                break
        if len(picked) >= max_articles:
            break
        time.sleep(0.5)
    out = []
    for row in picked:
        art = fetch_article(row["link"], max_chars=1800)
        images = list(art.get("images") or [])
        if row.get("image") and row["image"] not in [i["url"] for i in images]:
            images.insert(0, {"url": row["image"], "alt": row["title"]})
        out.append({**row, "text": art.get("text", ""), "images": images[:6], "error": art.get("error", "")})
        progress(f"읽음 {row['title'][:40]} — 본문 {len(art.get('text', ''))}자, 사진 {len(images)}장")
        time.sleep(0.5)
    return out


def image_candidates(main: dict, related: list[dict], *, main_url: str = "", max_items: int = 24) -> list[dict]:
    """카드에 넣을 사진 후보 목록(번호 붙음). 공식 출처 → 관련 기사 → 공식 페이지 캡처 순.
    [{id, url, alt, source_url, source_title, kind}]"""
    cands: list[dict] = []
    seen: set[str] = set()

    def add(url: str, alt: str, source_url: str, source_title: str, kind: str) -> None:
        if not url or url in seen or len(cands) >= max_items:
            return
        seen.add(url)
        cands.append({"id": len(cands) + 1, "url": url, "alt": (alt or "")[:80], "source_url": source_url,
                      "source_title": (source_title or "")[:60], "kind": kind})

    for im in main.get("images") or []:
        add(im["url"], im.get("alt", ""), main_url, main.get("title", "소재 원문"), "official")
    for link_art in main.get("link_articles") or []:
        for im in link_art.get("images") or []:
            add(im["url"], im.get("alt", ""), link_art["link"], link_art.get("title", "공식 링크"), "official")
    for art in related:
        for im in art.get("images") or []:
            add(im["url"], im.get("alt", ""), art["link"], art.get("title", ""), "related")
    for link in (main.get("links") or [])[:2]:
        add(f"screenshot:{link}", "공식 페이지 화면 캡처", link, "공식 페이지", "screenshot")
    if main_url:
        add(f"screenshot:{main_url}", "소재 원문 페이지 화면 캡처", main_url, main.get("title", "소재 원문"), "screenshot")
    return cands


def as_prompt(images: list[dict]) -> str:
    return "\n".join(f"[{c['id']}] {c['kind']} · {c['alt'] or '(설명 없음)'} · 출처: {c['source_title']}" for c in images)


def research_prompt_block(related: list[dict]) -> str:
    """글쓰기 프롬프트에 붙일 관련 기사 발췌."""
    parts = []
    for a in related:
        if a.get("text"):
            parts.append(f"[관련 글] {a['title']} ({a['link']})\n{a['text'][:1200]}")
    return "\n\n".join(parts)
