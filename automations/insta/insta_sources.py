"""소재 수집 — 주제 프로필의 출처(RSS)에서 최근 글을 모아 후보 목록을 만든다.

출처는 profiles/<이름>.yaml 의 `sources:` 에 이름으로 적고, 실제 주소는 이 파일의 SOURCES 에 둔다.
새 출처를 붙일 때는 SOURCES 에 한 줄 더하면 된다 (RSS 면 kind: rss).
"""
from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import feedparser
import requests

UA = "Mozilla/5.0 (compatible; ai-office-insta/1.0; +https://github.com/Junjaee/ai-office)"

# 이름 → 주소. 무료·공개 RSS 만.
SOURCES: dict[str, dict] = {
    "openai_news":    {"kind": "rss", "url": "https://openai.com/news/rss.xml", "label": "OpenAI"},
    "anthropic_news": {"kind": "rss", "url": "https://rsshub.bestblogs.dev/anthropic/news", "label": "Anthropic"},
    "google_ai":      {"kind": "rss", "url": "https://blog.google/technology/ai/rss/", "label": "Google AI"},
    "deepmind":       {"kind": "rss", "url": "https://deepmind.google/blog/rss.xml", "label": "Google DeepMind"},
    "rundown":        {"kind": "rss", "url": "https://www.therundown.ai/feed", "label": "The Rundown"},          # 매일 19:00 KST 미국 AI 소식 요약
    "testingcatalog": {"kind": "rss", "url": "https://www.testingcatalog.com/rss/", "label": "TestingCatalog"},   # 신기능·유출 (가장 빠른 축)
    "techcrunch_ai":  {"kind": "rss", "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "label": "TechCrunch"},
    # 육아(parent) · 혜택(benefit) 계정용 — 빙 뉴스 검색 RSS(한국어) + 육아 전문지
    "bing_parent_support":   {"kind": "rss", "url": "https://www.bing.com/news/search?q=%EC%9C%A1%EC%95%84+%EC%A7%80%EC%9B%90%EA%B8%88&format=rss&setlang=ko&cc=KR&qft=sortbydate%3d%221%22", "label": "뉴스 · 육아 지원금"},
    "bing_parent_allowance": {"kind": "rss", "url": "https://www.bing.com/news/search?q=%EB%B6%80%EB%AA%A8%EA%B8%89%EC%97%AC+%EC%95%84%EB%8F%99%EC%88%98%EB%8B%B9&format=rss&setlang=ko&cc=KR&qft=sortbydate%3d%221%22", "label": "뉴스 · 부모급여"},
    "bing_parent_tips":      {"kind": "rss", "url": "https://www.bing.com/news/search?q=%EC%9C%A1%EC%95%84+%EA%BF%80%ED%8C%81&format=rss&setlang=ko&cc=KR&qft=sortbydate%3d%221%22", "label": "뉴스 · 육아 꿀팁"},
    "bing_parent_health":    {"kind": "rss", "url": "https://www.bing.com/news/search?q=%EC%98%81%EC%9C%A0%EC%95%84+%EA%B1%B4%EA%B0%95+%EC%98%88%EB%B0%A9%EC%A0%91%EC%A2%85&format=rss&setlang=ko&cc=KR&qft=sortbydate%3d%221%22", "label": "뉴스 · 영유아 건강"},
    "babynews":              {"kind": "rss", "url": "https://www.ibabynews.com/rss/allArticle.xml", "label": "베이비뉴스"},
    "yna_society":           {"kind": "rss", "url": "https://www.yna.co.kr/rss/society.xml", "label": "연합뉴스 사회"},
    "yna_economy":           {"kind": "rss", "url": "https://www.yna.co.kr/rss/economy.xml", "label": "연합뉴스 경제"},
    # 정책·정치(aitips 계정, 2026-09-16 컨셉 전환) — 국회 의안 API + 정치·정책 뉴스
    "assembly_bills": {"kind": "bills", "url": "https://open.assembly.go.kr/portal/openapi/nzmimeepazxkubdpn",
                       "api": "nzmimeepazxkubdpn", "age": 22, "size": 80, "label": "국회 의안"},
    "yna_politics":   {"kind": "rss", "url": "https://www.yna.co.kr/rss/politics.xml", "label": "연합뉴스 정치"},
    "gnews_law":      {"kind": "rss", "url": "https://news.google.com/rss/search?q=%22%EB%82%B4%EB%85%84%EB%B6%80%ED%84%B0%22+OR+%22%EB%8B%A4%EC%9D%8C+%EB%8B%AC%EB%B6%80%ED%84%B0%22+%EC%A0%9C%EB%8F%84+when:3d&hl=ko&gl=KR&ceid=KR:ko", "label": "구글뉴스 제도"},
    "gnews_assembly": {"kind": "rss", "url": "https://news.google.com/rss/search?q=%22%EA%B5%AD%ED%9A%8C+%EB%B3%B8%ED%9A%8C%EC%9D%98%22+when:3d&hl=ko&gl=KR&ceid=KR:ko", "label": "구글뉴스 국회"},
    "gnews_cabinet":  {"kind": "rss", "url": "https://news.google.com/rss/search?q=%22%EA%B5%AD%EB%AC%B4%ED%9A%8C%EC%9D%98%22+%EC%9D%98%EA%B2%B0+when:3d&hl=ko&gl=KR&ceid=KR:ko", "label": "구글뉴스 국무회의"},
    "gnews_notice":   {"kind": "rss", "url": "https://news.google.com/rss/search?q=%EC%9E%85%EB%B2%95%EC%98%88%EA%B3%A0+OR+%22%EC%8B%9C%ED%96%89%EB%A0%B9+%EA%B0%9C%EC%A0%95%22+when:3d&hl=ko&gl=KR&ceid=KR:ko", "label": "구글뉴스 입법예고"},
    "gnews_budget":   {"kind": "rss", "url": "https://news.google.com/rss/search?q=%22%EC%A0%95%EB%B6%80+%EC%98%88%EC%82%B0%EC%95%88%22+OR+%22%EC%84%B8%EB%B2%95+%EA%B0%9C%EC%A0%95%22+when:3d&hl=ko&gl=KR&ceid=KR:ko", "label": "구글뉴스 예산·세금"},
    "bing_benefit_apply":    {"kind": "rss", "url": "https://www.bing.com/news/search?q=%EC%A7%80%EC%9B%90%EA%B8%88+%EC%8B%A0%EC%B2%AD&format=rss&setlang=ko&cc=KR&qft=sortbydate%3d%221%22", "label": "뉴스 · 지원금 신청"},
    "bing_benefit_youth":    {"kind": "rss", "url": "https://www.bing.com/news/search?q=%EC%B2%AD%EB%85%84+%EC%A7%80%EC%9B%90+%EC%8B%A0%EC%B2%AD&format=rss&setlang=ko&cc=KR&qft=sortbydate%3d%221%22", "label": "뉴스 · 청년 지원"},
    "bing_benefit_refund":   {"kind": "rss", "url": "https://www.bing.com/news/search?q=%ED%99%98%EA%B8%89+%EC%8B%A0%EC%B2%AD+%EB%B0%A9%EB%B2%95&format=rss&setlang=ko&cc=KR&qft=sortbydate%3d%221%22", "label": "뉴스 · 환급"},
    "bing_benefit_gov":      {"kind": "rss", "url": "https://www.bing.com/news/search?q=%EC%A0%95%EB%B6%80+%ED%98%9C%ED%83%9D+%EB%8B%AC%EB%9D%BC%EC%A7%80%EB%8A%94&format=rss&setlang=ko&cc=KR&qft=sortbydate%3d%221%22", "label": "뉴스 · 달라지는 제도"},
    "bing_benefit_card":     {"kind": "rss", "url": "https://www.bing.com/news/search?q=%ED%86%B5%EC%8B%A0%EB%B9%84+%ED%95%A0%EC%9D%B8+%ED%98%9C%ED%83%9D&format=rss&setlang=ko&cc=KR&qft=sortbydate%3d%221%22", "label": "뉴스 · 할인 혜택"},
    # 회사 공식 유튜브 채널(Atom) — 발표·데모 영상. 영상은 릴스로 만든다(insta_video)
    "yt_openai":      {"kind": "rss", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCXZCJLdBC09xxGZ6gcdrc6A", "label": "OpenAI 유튜브"},
    "yt_anthropic":   {"kind": "rss", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCrDwWp7EBBv4NwvScIpBDOA", "label": "Anthropic 유튜브"},
    "yt_deepmind":    {"kind": "rss", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCP7jMXSY2xbc3KCAE0MHQ-A", "label": "DeepMind 유튜브"},
    "yt_gemini":      {"kind": "rss", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCNW6J6bFBIAmvbrnE0rCPnA", "label": "Gemini 유튜브"},
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


def _youtube_descriptions(xml: bytes) -> dict[str, str]:
    """유튜브 채널 Atom 의 <media:description> 은 feedparser 가 버리므로 직접 꺼낸다: {videoId: 설명}."""
    text = xml.decode("utf-8", "ignore")
    out: dict[str, str] = {}
    for m in re.finditer(r"<yt:videoId>([\w-]{11})</yt:videoId>.*?<media:description>(.*?)</media:description>", text, re.S):
        out[m.group(1)] = html.unescape(m.group(2)).strip()
    return out


def _day(text: str) -> datetime | None:
    """'2026-09-15' → 그날 09:00 KST (UTC 기준으로 보관)."""
    t = str(text or "").strip()[:10]
    if not re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", t):
        return None
    y, m, d = (int(x) for x in t.split("-"))
    return datetime(y, m, d, 0, 0, tzinfo=timezone(timedelta(hours=9))).astimezone(timezone.utc)


def _fetch_bills(spec: dict, *, timeout: int = 30, session=None) -> list["Candidate"]:
    """열린국회정보 의안 목록 API → 후보 (2026-09-16 정책 계정용).
    환경변수 OPEN_API_KEY 가 있어야 하고, 브라우저 User-Agent 가 없으면 400 을 돌려준다."""
    import os

    key = os.environ.get("OPEN_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPEN_API_KEY 가 없습니다 (국회 의안 API)")
    sess = session or requests.Session()
    params = {"KEY": key, "Type": "json", "pIndex": 1, "pSize": int(spec.get("size", 80)), "AGE": int(spec.get("age", 22))}
    r = sess.get(spec["url"], params=params, headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    blocks = data.get(spec.get("api", "")) or []
    rows = next((b["row"] for b in blocks if isinstance(b, dict) and "row" in b), [])
    out: list[Candidate] = []
    for row in rows:
        title = str(row.get("BILL_NAME") or "").strip()
        link = str(row.get("DETAIL_LINK") or "").strip()
        if not title or not link:
            continue
        result = str(row.get("PROC_RESULT") or "").strip()
        when = _day(row.get("PROC_DT") or row.get("PROPOSE_DT") or "")
        bits = [str(row.get("PROPOSER") or "").strip(), str(row.get("COMMITTEE") or "").strip(), ("처리: " + result) if result else "심사 중"]
        bill_id = str(row.get("BILL_ID") or row.get("BILL_NO") or "").strip()
        # 의안 링크는 주소가 같고 물음표 뒤 번호만 달라서(normalize_key 가 잘라낸다) 의안 번호를 열쇠로 쓴다
        out.append(Candidate(key=f"bill:{bill_id}" if bill_id else normalize_key(link), title=title, link=link,
                             source=spec["label"], published=when, summary=" · ".join(x for x in bits if x)))
    return out


def fetch_source(name: str, *, timeout: int = 30, session: requests.Session | None = None) -> list[Candidate]:
    spec = SOURCES.get(name)
    if not spec:
        raise KeyError(f"모르는 출처: {name}")
    sess = session or requests.Session()
    if spec.get("kind") == "bills":                       # 국회 의안 API (RSS 가 아님)
        return _fetch_bills(spec, timeout=timeout, session=sess)
    r = sess.get(spec["url"], headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    yt_desc = _youtube_descriptions(r.content) if "youtube.com/feeds" in spec["url"] else {}
    out: list[Candidate] = []
    for e in feed.entries:
        link = getattr(e, "link", "") or ""
        title = _strip_html(getattr(e, "title", "") or "")
        if not link or not title:
            continue
        summary = _strip_html(getattr(e, "summary", "") or getattr(e, "description", "") or yt_desc.get(getattr(e, "yt_videoid", ""), ""))[:600]
        out.append(Candidate(key=normalize_key(link), title=title, link=link, source=spec["label"],
                             published=_entry_time(e), summary=summary))
    return out


def collect(source_names: list[str], *, max_age_hours: float, signals: list[str], exclude_keys: set[str],
            now: datetime | None = None, timeout: int = 30, progress=print,
            signal_required: list[str] | None = None, exclude_words: list[str] | None = None) -> tuple[list[Candidate], list[str]]:
    """출처마다 받아 나이·중복을 거르고 신호 단어를 표시한다. 한 출처 실패는 기록만 하고 계속.
    signal_required 에 든 출처(연합뉴스처럼 넓은 피드)는 신호 단어가 하나라도 있어야 남기고, exclude_words 가 제목에 있으면 버린다."""
    need = set(signal_required or [])
    bad = [w.lower() for w in (exclude_words or []) if w]
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
            if name in need and not c.signals:
                continue
            if bad and any(w in c.title.lower() for w in bad):
                continue
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
        if "video" in c.signals or "youtube.com" in c.link or "/status/" in c.link:
            sig = " [🎬영상]" + sig
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
