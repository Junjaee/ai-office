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


# 다른 사람의 SNS 게시물 사진·화면은 절대 카드에 넣지 않는다 (사용자 결정 2026-09-11 — "베꼈다"는 프레임을 피한다)
SOCIAL_RE = re.compile(r"(instagram\.com|cdninstagram\.com|fbcdn\.net|facebook\.com|threads\.(net|com)|tiktok\.com|"
                       r"twitter\.com|x\.com|twimg\.com|pinterest\.|linkedin\.com|youtube\.com|youtu\.be|blog\.naver\.com)", re.I)


def is_social(url: str) -> bool:
    return bool(SOCIAL_RE.search(url or ""))


# 페이지 캡처를 허용하는 공식 도메인(제품·회사 페이지). 언론사·블로그 페이지 캡처는 하지 않는다(쿠키 배너·광고·남의 편집물)
OFFICIAL_DOMAINS = ("openai.com", "chatgpt.com", "google", "gemini.google", "anthropic.com", "claude.ai", "x.ai", "meta.ai",
                    "ai.meta.com", "microsoft.com", "apple.com", "huggingface.co", "github.com", "notion.so", "adobe.com",
                    "midjourney.com", "perplexity.ai", "mistral.ai", "deepseek.com", "runwayml.com", "elevenlabs.io",
                    "canva.com", "figma.com", "naver.com", "kakao.com", "samsung.com", "lge.co.kr", "nvidia.com", "amazon.com")


def is_korean_source(url: str, title: str = "") -> bool:
    """한국 매체·한국어 페이지인가: .kr 도메인이거나 제목에 한글이 있으면."""
    host = re.sub(r"^https?://(www\.)?", "", url or "").split("/")[0].lower()
    return host.endswith(".kr") or bool(re.search(r"[가-힣]", title or ""))


def is_official(url: str) -> bool:
    host = re.sub(r"^https?://(www\.)?", "", url or "").split("/")[0].lower()
    return any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS)


def image_candidates(main: dict, related: list[dict], *, main_url: str = "", extra_links: list[str] | None = None,
                     max_items: int = 24) -> list[dict]:
    """카드에 넣을 사진 후보 목록(번호 붙음). 공식 출처 → 관련 기사 → 공식 페이지 캡처 순. 소셜 도메인은 뺀다.
    [{id, url, alt, source_url, source_title, kind}]"""
    cands: list[dict] = []
    seen: set[str] = set()

    def add(url: str, alt: str, source_url: str, source_title: str, kind: str) -> None:
        if not url or url in seen or len(cands) >= max_items:
            return
        target = url[len("screenshot:"):] if url.startswith("screenshot:") else url
        if is_social(target) or is_social(source_url or ""):
            return
        if url.startswith("screenshot:") and not is_official(target):
            return                                   # 캡처는 공식 페이지만
        seen.add(url)
        cands.append({"id": len(cands) + 1, "url": url, "alt": (alt or "")[:80], "source_url": source_url,
                      "source_title": (source_title or "")[:60], "kind": kind})

    for im in main.get("images") or []:
        add(im["url"], im.get("alt", ""), main_url, main.get("title", "소재 원문"), "official")
    for link_art in main.get("link_articles") or []:
        for im in link_art.get("images") or []:
            add(im["url"], im.get("alt", ""), link_art["link"], link_art.get("title", "공식 링크"), "official")
    for art in related:
        if not is_korean_source(art.get("link", ""), art.get("title", "")):
            continue                                 # 외국 매체 사진(영문 화면·홍보 사진)은 쓰지 않는다 — 사용자 결정 2026-09-11
        for im in art.get("images") or []:
            add(im["url"], im.get("alt", ""), art["link"], art.get("title", ""), "related")
    for link in (main.get("links") or [])[:2]:
        add(f"screenshot:{link}", "공식 페이지 화면 캡처", link, "공식 페이지", "screenshot")
    # 기사가 출처로 든 공식 페이지(claims·sources) — 도메인당 하나, 3개까지
    hosts: set[str] = {re.sub(r"^https?://(www\.)?", "", c["url"][len("screenshot:"):]).split("/")[0]
                       for c in cands if c["kind"] == "screenshot"}
    for link in extra_links or []:
        host = re.sub(r"^https?://(www\.)?", "", link).split("/")[0]
        if not link.startswith("http") or host in hosts or is_social(link):
            continue
        hosts.add(host)
        add(f"screenshot:{link}", f"출처 페이지 화면 캡처 ({host})", link, host, "screenshot")
        if len(hosts) >= 3:
            break
    if main_url:
        add(f"screenshot:{main_url}", "소재 원문 페이지 화면 캡처", main_url, main.get("title", "소재 원문"), "screenshot")
    return cands


OPENVERSE = "https://api.openverse.org/v1/images/"


def openverse_search(query: str, *, n: int = 3, min_width: int = 640, timeout: int = 20) -> list[dict]:
    """CC 라이선스 사진 검색(무료·키 없음). [{url, alt, source_url, source_title, kind:'cc', creator, license}]
    상업적 이용이 되는 라이선스만(cc0, by, by-sa, pdm). 실패하면 빈 목록."""
    if not query.strip():
        return []
    try:
        r = requests.get(OPENVERSE, params={"q": query, "license": "cc0,by,by-sa,pdm", "page_size": 20, "mature": "false"},
                         headers={"User-Agent": UA}, timeout=timeout)
        r.raise_for_status()
        rows = r.json().get("results", [])
    except Exception:  # noqa: BLE001
        return []
    out = []
    for x in rows:
        if int(x.get("width") or 0) < min_width or not str(x.get("url", "")).startswith("http"):
            continue
        raw = str(x.get("license", "")).lower()
        lic = {"cc0": "CC0", "pdm": "Public Domain", "by": "CC BY", "by-sa": "CC BY-SA"}.get(raw, "CC " + raw.upper())
        creator = (x.get("creator") or "").strip()[:30]
        w, h = int(x.get("width") or 0), int(x.get("height") or 1)
        out.append({"url": x["url"], "alt": (x.get("title") or "")[:80], "source_url": x.get("foreign_landing_url") or x["url"],
                    "source_title": f"{creator} · {lic}" if creator else lic, "kind": "cc",
                    "creator": creator, "license": lic, "landscape": w >= h})
    out.sort(key=lambda c: not c["landscape"])          # 카드에는 가로 사진이 낫다
    return out[:n]


def as_prompt(images: list[dict]) -> str:
    return "\n".join(f"[{c['id']}] {c['kind']} · {c['alt'] or '(설명 없음)'} · 출처: {c['source_title']}" for c in images)


def research_prompt_block(related: list[dict]) -> str:
    """글쓰기 프롬프트에 붙일 관련 기사 발췌."""
    parts = []
    for a in related:
        if a.get("text"):
            parts.append(f"[관련 글] {a['title']} ({a['link']})\n{a['text'][:1200]}")
    return "\n\n".join(parts)
