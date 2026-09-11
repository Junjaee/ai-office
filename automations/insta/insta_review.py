"""주제 검토 파일 — 매일 뽑은 후보와 사용자가 고른 예약(큐)을 한 파일에 둔다. 표준 라이브러리만 쓴다(예약 확인 단계가 의존성 설치 없이 부른다).

파일: public/review/<사무실>/<자동화>.json  (대시보드 /api/review 가 읽는다)
{
  "date": "2026-09-12", "generated_at": "...", "count": 10,
  "candidates": [{"id", "key", "title", "link", "source", "published", "summary", "reason", "angle"}],
  "queue":      [{"id", "key", "title", "link", "source", "summary", "angle", "due", "status", "added_at", "permalink", "error"}]
}
status: queued(예약) → making(만드는 중) → done(게시됨) | failed(실패)

예약 간격(사용자 결정 2026-09-11): 고른 개수 N → 24÷N 시간 간격. 첫 개는 바로, 나머지는 정각으로 올림.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
ACTIVE = ("queued", "making")


def short_id(key: str) -> str:
    """후보를 가리키는 짧은 id (대시보드 → 워크플로 입력값으로 오간다)."""
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]


def review_path(repo: Path | str, workspace: str, automation_id: str) -> Path:
    return Path(repo) / "public" / "review" / workspace / f"{automation_id}.json"


def load(path: Path) -> dict:
    if not path.exists():
        return {"date": "", "generated_at": "", "count": 0, "candidates": [], "queue": []}
    d = json.loads(path.read_text(encoding="utf-8"))
    d.setdefault("candidates", []); d.setdefault("queue", [])
    return d


def save(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def active_keys(data: dict) -> set[str]:
    """예약·진행 중인 소재 키 (후보 수집에서 제외)."""
    return {q["key"] for q in data.get("queue", []) if q.get("status") in ACTIVE}


def set_candidates(data: dict, rows: list[dict], *, now: datetime) -> dict:
    """오늘 후보로 바꾼다. 큐는 아직 안 끝난 것만 남기고, 끝난 것은 2일 지나면 지운다."""
    cands = []
    for r in rows:
        c = dict(r)
        c["id"] = short_id(c["key"])
        cands.append(c)
    keep = []
    for q in data.get("queue", []):
        if q.get("status") in ACTIVE:
            keep.append(q)
        else:
            when = _parse(q.get("finished_at") or q.get("added_at"))
            if when and now - when < timedelta(days=2):
                keep.append(q)
    return {**data, "date": now.astimezone(KST).strftime("%Y-%m-%d"), "generated_at": now.isoformat(timespec="seconds"),
            "count": len(cands), "candidates": cands, "queue": keep}


def schedule_times(n: int, now: datetime) -> list[datetime]:
    """N개를 24÷N 시간 간격으로. 첫 개는 지금, 나머지는 다음 정각으로 올림."""
    if n <= 0:
        return []
    step = 24.0 / n
    out = [now]
    for i in range(1, n):
        t = now + timedelta(hours=step * i)
        t = t.replace(minute=0, second=0, microsecond=0)
        if t < now + timedelta(hours=step * i):
            t += timedelta(hours=1)
        out.append(t)
    return out


def enqueue(data: dict, pick_ids: list[str], *, now: datetime) -> tuple[dict, list[dict]]:
    """고른 후보 id 들을 예약에 넣는다. 이미 예약·진행 중이거나 없는 id 는 건너뛴다. (파일, 새로 넣은 항목) 반환."""
    by_id = {c["id"]: c for c in data.get("candidates", [])}
    busy = active_keys(data)
    chosen = []
    seen: set[str] = set()
    for pid in pick_ids:
        c = by_id.get(pid)
        if not c or c["key"] in busy or c["key"] in seen:
            continue
        seen.add(c["key"])
        chosen.append(c)
    times = schedule_times(len(chosen), now)
    added = []
    for c, t in zip(chosen, times):
        item = {"id": c["id"], "key": c["key"], "title": c["title"], "link": c["link"], "source": c.get("source", ""),
                "summary": c.get("summary", ""), "angle": c.get("angle", ""), "due": t.isoformat(timespec="seconds"),
                "status": "queued", "added_at": now.isoformat(timespec="seconds")}
        added.append(item)
    data = {**data, "queue": list(data.get("queue", [])) + added,
            "interval_hours": round(24.0 / len(chosen), 2) if chosen else data.get("interval_hours")}
    return data, added


def due_items(data: dict, now: datetime) -> list[dict]:
    out = []
    for q in data.get("queue", []):
        t = _parse(q.get("due"))
        if q.get("status") == "queued" and t and t <= now:
            out.append(q)
    out.sort(key=lambda q: q["due"])
    return out


def mark(data: dict, item_id: str, status: str, *, now: datetime, **extra) -> dict:
    queue = []
    for q in data.get("queue", []):
        if q.get("id") == item_id and q.get("status") in ACTIVE:
            q = {**q, "status": status, **extra}
            if status in ("done", "failed"):
                q["finished_at"] = now.isoformat(timespec="seconds")
        queue.append(q)
    return {**data, "queue": queue}


def _parse(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        t = datetime.fromisoformat(s)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def has_due(path: Path, now: datetime | None = None) -> bool:
    """예약 확인용: 지금 만들 것이 있는가 (의존성 설치 전에 부른다)."""
    return bool(due_items(load(path), now or datetime.now(timezone.utc)))


def summarize(data: dict) -> str:
    q = data.get("queue", [])
    n_wait = sum(1 for x in q if x.get("status") == "queued")
    n_done = sum(1 for x in q if x.get("status") == "done")
    return f"후보 {data.get('count', 0)}건 · 예약 {n_wait}건 · 게시 {n_done}건"
