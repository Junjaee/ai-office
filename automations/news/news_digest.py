"""수집한 기사를 중복 없이 정리해 하루치 마크다운으로 만든다. 전부 순수 함수다.

문장을 새로 쓰는 AI 요약은 별도 키가 필요해 지금은 넣지 않는다.
대신 (1) 같은 기사 합치기 (2) 검색어 묶음별 나누기 (3) 매체 수 세기 까지 한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from google_news import Article, normalize_title

KST = timezone(timedelta(hours=9))


def dedupe(articles: list[Article]) -> list[dict]:
    """같은 기사를 하나로 합친다. 판정 기준은 링크, 그다음 제목(기호·공백 무시).

    합쳐진 항목: {"title","link","published","sources":[매체…],"queries":[검색어…],"groups":[묶음…]}
    """
    merged: dict[str, dict] = {}
    for a in articles:
        key = normalize_title(a.title) or a.link
        item = merged.get(key)
        if item is None:
            merged[key] = {"title": a.title, "link": a.link, "published": a.published,
                           "sources": [a.source], "queries": [a.query], "groups": [a.group]}
            continue
        # 먼저 나온 기사를 대표로 두고, 매체·검색어만 더한다
        for field, value in (("sources", a.source), ("queries", a.query), ("groups", a.group)):
            if value and value not in item[field]:
                item[field].append(value)
        if a.published and (not item["published"] or a.published < item["published"]):
            item["published"] = a.published   # 가장 먼저 나온 시각을 남긴다
    return list(merged.values())


def merge_manifest(manifest: dict, items: list[dict], *, now: datetime | None = None) -> list[dict]:
    """manifest 에 없던 기사만 새로 넣고, 새 기사 목록을 돌려준다. manifest 는 그 자리에서 바뀐다."""
    now = now or datetime.now(KST)
    seen_at = now.isoformat(timespec="seconds")
    day = (now.date().isoformat())
    fresh: list[dict] = []
    for item in items:
        key = normalize_title(item["title"]) or item["link"]
        if key in manifest:
            prev = manifest[key]
            for field in ("sources", "queries", "groups"):
                for value in item[field]:
                    if value not in prev[field]:
                        prev[field].append(value)
            continue
        manifest[key] = {**item, "seen_at": seen_at, "day": day}
        fresh.append(manifest[key])
    return fresh


def prune_manifest(manifest: dict, *, keep_days: int, now: datetime | None = None) -> int:
    """오래된 기록을 지운다(파일이 끝없이 커지지 않게). 지운 개수를 돌려준다."""
    now = now or datetime.now(KST)
    limit = (now.date() - timedelta(days=keep_days)).isoformat()
    old = [k for k, v in manifest.items() if (v.get("day") or "") < limit]
    for k in old:
        del manifest[k]
    return len(old)


def _when(published: str, day: str) -> str:
    """오늘 기사면 시:분만, 어제 이전 기사면 날짜도 같이 보여 준다."""
    if len(published) < 16:
        return "--:--"
    return published[11:16] if published[:10] == day else f"{published[5:10]} {published[11:16]}"


def entries_for_day(manifest: dict, day: str) -> list[dict]:
    """그날 처음 본 기사만, 최신 순으로."""
    rows = [v for v in manifest.values() if v.get("day") == day]
    return sorted(rows, key=lambda v: (v.get("published") or "", v.get("seen_at") or ""), reverse=True)


def render_day(day: str, rows: list[dict], groups: list[str], *, updated_at: str) -> str:
    """하루치 마크다운. 실행할 때마다 그날 기록 전체로 다시 만든다(같은 결과가 나오게)."""
    out = [f"# {day} 기사 모니터링", "",
           f"> 마지막 갱신 {updated_at} · 오늘 {len(rows)}건", ""]
    for group in groups:
        picked = [r for r in rows if group in (r.get("groups") or [])]
        out.append(f"## {group} ({len(picked)}건)")
        out.append("")
        if not picked:
            out += ["_새 기사가 없습니다._", ""]
            continue
        for r in picked:
            media = ", ".join(r.get("sources") or []) or "출처 미상"
            words = ", ".join(r.get("queries") or [])
            out.append(f"- `{_when(r.get('published') or '', day)}` [{r['title']}]({r['link']}) — {media}"
                       + (f"  <sub>{words}</sub>" if words else ""))
        out.append("")
    others = [r for r in rows if not set(r.get("groups") or []) & set(groups)]
    if others:
        out += [f"## 기타 ({len(others)}건)", ""]
        out += [f"- `{_when(r.get('published') or '', day)}` [{r['title']}]({r['link']}) — "
                + (", ".join(r.get('sources') or []) or "출처 미상") for r in others]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def media_counts(rows: list[dict]) -> list[tuple[str, int]]:
    """매체별 건수, 많은 순."""
    counts: dict[str, int] = {}
    for r in rows:
        for m in r.get("sources") or []:
            counts[m] = counts.get(m, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
