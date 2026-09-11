"""소재 수집 — 주제 프로필의 출처(RSS)에서 최근 글을 모아 후보 목록을 만든다.

출처는 profiles/<이름>.yaml 의 `sources:` 에 이름으로 적고, 실제 주소는 이 파일의 SOURCES 에 둔다.
새 출처를 붙일 때는 SOURCES 에 한 줄 더하면 된다 (RSS 면 kind: rss).
"""
from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import feedparser
import requests

UA = "Mozilla/5.0 (compatible; ai-office-insta/1.0; +https://github.com/Junjaee/ai-office)"

# 이름 → 주소. 무료·공개 RSS 만.
SOURCES: dict[str, dict] = {
    "openai_news":    {"kind": "rss", "url": "https://openai.com/news/rss.xml", "label": "OpenAI"},
    "anthropic_news": {"kind": "rss", "url": "https://rsshub.bestblogs.dev/anthropic/news", "label": "Anthropic"},
    "google_ai":      {"kind": "rss", "url": "https://blog.google/technology/ai/rss/", "label": "Google AI"},
    "huggingface":    {"kind": "rss", "url": "https://huggingface.co/blog/feed.xml", "label": "Hugging Face"},
    "geeknews":       {"kind": "rss", "url": "https://news.hada.io/rss/news", "label": "GeekNews"},
    "aitimes":        {"kind": "rss", "url": "https://www.aitimes.com/rss/allArticle.xml", "label": "AI타임스"},
    "producthunt_ai": {"kind": "rss", "url": "https://www.producthunt.com/feed?category=artificial-intelligence", "label": "Product Hunt"},
    "reddit_chatgpt": {"kind": "rss", "url": "https://www.reddit.com/r/ChatGPT/top/.rss?t=day", "label": "r/ChatGPT"},
    "reddit_claude":  {"kind": "rss", "url": "https://www.reddit.com/r/ClaudeAI/top/.rss?t=day", "label": "r/ClaudeAI"},
}


@dataclass
class Candidate:
    key: str            # 중복 판정용 (정규화한 링크)
    title: str
    link: str
    source: str         # 출처 라벨
    published: datetime | None
    summary: str = ""
    signals: list[str] = field(default_factory=list)

    def age_hours(self, now: datetime) -> float:
        if not self.published:
            return 0.0
        return (now - self.published).total_seconds() / 3600


def normalize_key(link: str) -> str:
    link = re.sub(r"[?#].*$", "", (link or "").strip().lower())
    return re.sub(r"/+$", "", link)


def _entry_time(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            return datetime.fromtimestamp(time.mktime(t), tz=timezone.utc)
    return None


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def fetch_source(name: str, *, timeout: int = 30, session: requests.Session | None = None) -> list[Candidate]:
    spec = SOURCES.get(name)
    if not spec:
        raise KeyError(f"모르는 출처: {name}")
    sess = session or requests.Session()
    r = sess.get(spec["url"], headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    out: list[Candidate] = []
    for e in feed.entries:
        link = getattr(e, "link", "") or ""
        title = _strip_html(getattr(e, "title", "") or "")
        if not link or not title:
            continue
        summary = _strip_html(getattr(e, "summary", "") or getattr(e, "description", "") or "")[:600]
        out.append(Candidate(key=normalize_key(link), title=title, link=link, source=spec["label"],
                             published=_entry_time(e), summary=summary))
    return out


def collect(source_names: list[str], *, max_age_hours: float, signals: list[str], exclude_keys: set[str],
            now: datetime | None = None, timeout: int = 30, progress=print) -> tuple[list[Candidate], list[str]]:
    """출처마다 받아 나이·중복을 거르고 신호 단어를 표시한다. 한 출처 실패는 기록만 하고 계속."""
    now = now or datetime.now(timezone.utc)
    sess = requests.Session()
    found: list[Candidate] = []
    failed: list[str] = []
    seen: set[str] = set()
    for name in source_names:
        try:
            items = fetch_source(name, timeout=timeout, session=sess)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{name}: {type(exc).__name__} {str(exc)[:80]}")
            progress(f"{name} — 실패")
            continue
        kept = 0
        for c in items:
            if c.key in seen or c.key in exclude_keys:
                continue
            if c.published and c.age_hours(now) > max_age_hours:
                continue
            text = f"{c.title} {c.summary}".lower()
            c.signals = [s for s in signals if s.lower() in text]
            seen.add(c.key)
            found.append(c)
            kept += 1
        progress(f"{name} — {len(items)}건 중 {kept}건")
        time.sleep(0.5)
    # 신호 많은 것 → 최신 순
    found.sort(key=lambda c: (-len(c.signals), -(c.published.timestamp() if c.published else 0)))
    return found, failed


def cap_by_source(cands: list[Candidate], caps: dict) -> list[Candidate]:
    """출처 라벨별 후보 상한 (caps 는 SOURCES 이름 기준). 순서는 유지."""
    label_caps = {SOURCES[k]["label"]: int(n) for k, n in caps.items() if k in SOURCES}
    if not label_caps:
        return cands
    counts: dict[str, int] = {}
    out = []
    for c in cands:
        lim = label_caps.get(c.source)
        if lim is not None:
            counts[c.source] = counts.get(c.source, 0) + 1
            if counts[c.source] > lim:
                continue
        out.append(c)
    return out


def as_prompt_rows(cands: list[Candidate], limit: int) -> str:
    rows = []
    for i, c in enumerate(cands[:limit], 1):
        when = c.published.strftime("%m-%d") if c.published else "--"
        sig = f" [{', '.join(c.signals)}]" if c.signals else ""
        rows.append(f"{i}. ({c.source} {when}){sig} {c.title}\n   {c.summary[:200]}\n   {c.link}")
    return "\n".join(rows)


def _main_block(soup):
    """본문 영역 고르기: <article>/<main> 에 글이 충분하면 그것, 아니면 <p> 글자 수가 가장 많은 div/section."""
    def plen(el) -> int:
        return sum(len(x.get_text(" ", strip=True)) for x in el.find_all("p"))

    for tag in ("article", "main"):
        el = soup.find(tag)
        if el is not None and plen(el) >= 300:
            return el
    best, best_len = None, 0
    for el in soup.find_all(["article", "main", "section", "div"]):
        n = plen(el)
        # 자식에 같은 글이 들어 있으면 더 안쪽(작은) 요소를 고른다
        if n > best_len * 1.15 or (best is None and n > 0):
            best, best_len = el, n
    return best if best is not None and best_len >= 200 else (soup.body or soup)


def fetch_article(url: str, *, timeout: int = 30, max_chars: int = 3500) -> dict:
    """소재 원문을 읽어 제목·본문 텍스트·바깥 링크·이미지[{url, alt}] 를 돌려준다(글쓰기 근거·사진 후보용). 실패하면 빈 값."""
    try:
        from bs4 import BeautifulSoup

        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        for t in soup(["script", "style", "nav", "header", "footer", "noscript"]):
            t.decompose()
        main = _main_block(soup)
        text = re.sub(r"\s+", " ", main.get_text(" ")).strip()
        host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
        links = []
        for a in main.find_all("a", href=True):
            h = a["href"]
            if h.startswith("http") and host not in h and not re.search(r"(twitter|x\.com|facebook|instagram|reddit\.com/r/|login|signup)", h):
                if h not in links:
                    links.append(h)
        ogt = soup.find("meta", property="og:title")
        title = (ogt["content"] if ogt and ogt.get("content") else (soup.title.get_text() if soup.title else "")).strip()
        images: list[dict] = []
        og = soup.find("meta", property="og:image")
        if og and og.get("content", "").startswith("http"):
            images.append({"url": og["content"], "alt": "대표 이미지"})
        for im in main.find_all("img"):
            src = im.get("src") or im.get("data-src") or ""
            if not src.startswith("http") or src in [i["url"] for i in images]:
                continue
            if re.search(r"(logo|icon|avatar|badge|sprite|1x1|pixel|emoji|\.svg($|\?))", src, re.I):
                continue
            w = im.get("width")
            if w and str(w).isdigit() and int(w) < 300:
                continue
            alt = (im.get("alt") or "").strip()
            fig = im.find_parent("figure")
            cap = fig.find("figcaption").get_text(" ", strip=True) if fig and fig.find("figcaption") else ""
            images.append({"url": src, "alt": (cap or alt)[:120]})
        return {"title": title[:120], "text": text[:max_chars], "links": links[:8], "images": images[:8]}
    except Exception as exc:  # noqa: BLE001
        return {"title": "", "text": "", "links": [], "images": [], "error": f"{type(exc).__name__}: {str(exc)[:80]}"}
