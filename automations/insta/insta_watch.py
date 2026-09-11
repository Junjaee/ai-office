"""참고 계정 감시 — 한국 AI 인스타 계정들이 최근 무엇을 올렸고 반응(좋아요·댓글)이 어땠는지 읽어 소재 후보로 만든다.

경로: Instagram Graph API 의 **Business Discovery** (다른 프로페셔널 계정의 공개 게시물). 이건 "페이스북 로그인" 방식 토큰이 필요하다:
  IG_DISCOVERY_TOKEN     페이스북 페이지에 연결된 인스타 프로페셔널 계정의 장기 사용자 토큰 (권한 instagram_basic, pages_show_list, pages_read_engagement)
  IG_DISCOVERY_USER_ID   그 인스타 계정의 Graph API 사용자 id (17841…)
둘 중 하나라도 없으면 조용히 빈 목록을 돌려준다(RSS 만으로 진행).

스크래핑은 쓰지 않는다 — 로그인 벽·계정 차단 위험이 있어 게시 계정을 걸 수 없다(사용자 결정 2026-09-11).
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

import requests

from insta_sources import UA, Candidate, normalize_key

GRAPH = "https://graph.facebook.com/v23.0"
# 후보에서 뺄 게시물: 광고·협찬, "댓글 달면 DM" 식 유도(내용이 캡션에 없음)
SKIP_RE = re.compile(r"#광고|제작지원|\(광고\)|^\s*comment\s+[“\"«']?\w+[”\"»']?\s+(and|to|below)|paid partnership", re.I | re.M)
FIELDS = "media.limit({limit}){{caption,permalink,timestamp,like_count,comments_count,media_type}}"


def discovery_env() -> tuple[str, str]:
    return os.environ.get("IG_DISCOVERY_TOKEN", "").strip(), os.environ.get("IG_DISCOVERY_USER_ID", "").strip()


def fetch_account(username: str, *, token: str, user_id: str, limit: int = 12, timeout: int = 30,
                  session: requests.Session | None = None) -> list[dict]:
    """계정 하나의 최근 게시물 [{caption, permalink, timestamp, like_count, comments_count, media_type}]."""
    sess = session or requests.Session()
    fields = f"business_discovery.username({username}){{{FIELDS.format(limit=limit)}}}"
    r = sess.get(f"{GRAPH}/{user_id}", params={"fields": fields, "access_token": token},
                 headers={"User-Agent": UA}, timeout=timeout)
    if not r.ok:
        raise RuntimeError(f"{username}: HTTP {r.status_code} {r.text[:120]}")
    data = r.json().get("business_discovery", {}).get("media", {}).get("data", [])
    return [d for d in data if d.get("caption")]


def first_line(caption: str) -> str:
    """캡션 첫 줄 = 그 게시물의 제목 역할 (이모지·해시태그 제거)."""
    line = (caption or "").strip().split("\n")[0]
    line = re.sub(r"#\S+", "", line)
    line = re.sub(r"[\U0001F300-\U0001FAFF☀-➿⭐✅️]", "", line)
    return re.sub(r"\s+", " ", line).strip(" .·-")[:80]


def to_candidate(username: str, post: dict, flag: str = "🇰🇷") -> Candidate:
    caption = post.get("caption", "")
    likes = int(post.get("like_count") or 0)
    comments = int(post.get("comments_count") or 0)
    try:
        published = datetime.fromisoformat(str(post.get("timestamp", "")).replace("+0000", "+00:00"))
    except ValueError:
        published = None
    title = first_line(caption) or f"@{username} 게시물"
    body = re.sub(r"\s+", " ", caption)[:600]
    return Candidate(key=normalize_key(post.get("permalink", "")), title=title, link=post.get("permalink", ""),
                     source=f"IG {flag} @{username} · 좋아요 {_k(likes)} · 댓글 {_k(comments)}", published=published, summary=body,
                     signals=[f"likes:{likes}"])


def _k(n: int) -> str:
    return f"{n / 10000:.1f}만" if n >= 10000 else (f"{n / 1000:.1f}천" if n >= 1000 else str(n))


def likes_of(c: Candidate) -> int:
    for s in c.signals:
        if s.startswith("likes:"):
            return int(s[6:])
    return 0


def collect_watch(accounts: list[str], *, max_age_hours: float = 240, exclude_keys: set[str] | None = None,
                  min_likes: int = 0, now: datetime | None = None, flag: str = "🇰🇷", cap: int = 0,
                  per_account: int = 0, progress=print) -> tuple[list[Candidate], list[str]]:
    """참고 계정들의 최근 게시물 → 후보(좋아요 많은 순, 계정당 per_account 개·전체 cap 개까지).
    flag 는 출처 라벨의 나라 표시(🇰🇷 한국 참고 계정 / 🇺🇸 미국 원출처). 광고·"댓글 달면 DM" 게시물은 뺀다. 토큰이 없으면 빈 목록 + 안내 한 줄."""
    token, user_id = discovery_env()
    if not token or not user_id or not accounts:
        if accounts:
            progress("참고 계정 건너뜀 — IG_DISCOVERY_TOKEN / IG_DISCOVERY_USER_ID 없음")
        return [], []
    now = now or datetime.now(timezone.utc)
    exclude_keys = exclude_keys or set()
    sess = requests.Session()
    found: list[Candidate] = []
    failed: list[str] = []
    for acct in accounts:
        try:
            posts = fetch_account(acct, token=token, user_id=user_id, session=sess)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"@{acct}: {type(exc).__name__} {str(exc)[:80]}")
            progress(f"@{acct} — 실패")
            continue
        mine: list[Candidate] = []
        for p in posts:
            if SKIP_RE.search(p.get("caption") or ""):
                continue
            c = to_candidate(acct, p, flag)
            if not c.key or c.key in exclude_keys:
                continue
            if c.published and c.age_hours(now) > max_age_hours:
                continue
            if likes_of(c) < min_likes:
                continue
            mine.append(c)
        mine.sort(key=lambda c: (-likes_of(c), -(c.published.timestamp() if c.published else 0)))
        if per_account > 0:
            mine = mine[:per_account]
        found.extend(mine)
        progress(f"@{acct} — 최근 {len(posts)}건 중 {len(mine)}건")
    found.sort(key=lambda c: (-likes_of(c), -(c.published.timestamp() if c.published else 0)))
    if cap > 0:
        found = found[:cap]
    return found, failed
