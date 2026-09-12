"""주제 검토 파일 — 매일 뽑은 후보와 사용자가 고른 예약(큐)을 한 파일에 둔다. 표준 라이브러리만 쓴다(예약 확인 단계가 의존성 설치 없이 부른다).

파일: public/review/<사무실>/<자동화>.json  (대시보드 /api/review 가 읽는다)
{
  "date": "2026-09-12", "generated_at": "...", "count": 10,
  "candidates": [{"id", "key", "title", "link", "source", "published", "summary", "reason", "angle"}],
  "queue":      [{"id", "key", "title", "link", "source", "summary", "angle", "due", "status", "added_at", "permalink", "error"}]
}
status: queued(예약) → making(만드는 중) → done(게시됨) | failed(실패)

예약 시각(사용자 결정 2026-09-12): 고정 시간대 SLOTS(07:30 · 12:30 · 18:30 KST). 고른 주제는 **다음 빈 시간대부터 차례로** 들어간다(하루 3건이 자연히 상한).
  (구버전 24÷N 간격 방식은 schedule_times 로 남겨 두었고, slots 를 안 주면 그 방식으로 돈다.)
자동 선택(사용자 결정 2026-09-12): 매일 첫 시간대(07:30)에 예약이 하나도 없으면 편집장 1순위 후보를 바로 만들어 게시한다(auto_pick).
  사용자가 미리 골라 뒀으면(예약 있음) 자동 선택은 건너뛴다.
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


def schedule_times(n: int, now: datetime, *, max_per_day: int = 0, start: datetime | None = None) -> list[datetime]:
    """N개를 24÷N 시간 간격으로. 첫 개는 지금(start 가 있으면 그 시각), 나머지는 다음 정각으로 올림.
    max_per_day(>0)가 있으면 간격이 24÷max_per_day 보다 좁아지지 않아 남는 것은 다음 날로 넘어간다 (하루 상한)."""
    if n <= 0:
        return []
    step = 24.0 / n
    if max_per_day > 0:
        step = max(step, 24.0 / max_per_day)
    now = start or now
    out = [now]
    for i in range(1, n):
        t = now + timedelta(hours=step * i)
        t = t.replace(minute=0, second=0, microsecond=0)
        if t < now + timedelta(hours=step * i):
            t += timedelta(hours=1)
        out.append(t)
    return out


DEFAULT_SLOTS = ("07:30", "12:30", "18:30")


def slot_times(n: int, now: datetime, *, slots=DEFAULT_SLOTS, taken: list[datetime] | None = None, grace_min: int = 5) -> list[datetime]:
    """오늘부터 날짜를 넘겨 가며 아직 안 지난(지금+grace 분 이후) 빈 시간대를 n개 고른다. taken(이미 예약된 시각)과 겹치면 건너뛴다."""
    if n <= 0:
        return []
    base = now.astimezone(KST)
    used = {t.astimezone(KST).replace(second=0, microsecond=0) for t in (taken or [])}
    out: list[datetime] = []
    for day in range(0, 60):
        d = (base + timedelta(days=day)).date()
        for hm in slots:
            h, m = (int(x) for x in str(hm).split(":"))
            t = datetime(d.year, d.month, d.day, h, m, tzinfo=KST)
            if t < base + timedelta(minutes=grace_min) or t in used:
                continue
            out.append(t)
            if len(out) == n:
                return out
    return out


def active_dues(data: dict) -> list[datetime]:
    ts = [_parse(q.get("due")) for q in data.get("queue", []) if q.get("status") in ACTIVE]
    return [t for t in ts if t]


def last_due(data: dict) -> datetime | None:
    """예약·진행 중인 항목 중 가장 늦은 시각."""
    ts = [_parse(q.get("due")) for q in data.get("queue", []) if q.get("status") in ACTIVE]
    ts = [t for t in ts if t]
    return max(ts) if ts else None


def enqueue(data: dict, pick_ids: list[str], *, now: datetime, max_per_day: int = 0, slots=None) -> tuple[dict, list[dict]]:
    """고른 후보 id 들을 예약에 넣는다. 이미 예약·진행 중이거나 없는 id 는 건너뛴다. (파일, 새로 넣은 항목) 반환.
    slots(고정 시간대)가 있으면 다음 빈 시간대부터 차례로 배정한다(기본 운영 방식). 없으면 24÷N 간격(max_per_day 상한)."""
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
    start = None
    if max_per_day > 0:
        tail = last_due(data)
        if tail:
            start = max(now, tail + timedelta(hours=24.0 / max_per_day))
            if start > now:                                   # 정각으로 올림 (이미 정각이면 그대로)
                r = start.replace(minute=0, second=0, microsecond=0)
                start = r if r == start else r + timedelta(hours=1)
    times = slot_times(len(chosen), now, slots=slots, taken=active_dues(data)) if slots else \
        schedule_times(len(chosen), now, max_per_day=max_per_day, start=start)
    added = []
    for c, t in zip(chosen, times):
        item = {"id": c["id"], "key": c["key"], "title": c["title"], "link": c["link"], "source": c.get("source", ""),
                "summary": c.get("summary", ""), "angle": c.get("angle", ""), "due": t.isoformat(timespec="seconds"),
                "status": "queued", "added_at": now.isoformat(timespec="seconds")}
        added.append(item)
    data = {**data, "queue": list(data.get("queue", [])) + added,
            "interval_hours": round(max(24.0 / len(chosen), 24.0 / max_per_day if max_per_day > 0 else 0), 2) if chosen else data.get("interval_hours")}
    return data, added


def auto_pick(data: dict, *, exclude_keys: set[str], now: datetime, n: int = 1, max_age_days: int = 2, max_per_day: int = 0,
              slots=None) -> tuple[dict, list[dict]]:
    """아무도 안 골랐으면 후보 앞에서 n개를 예약(첫 개는 지금). 예약·진행 중이 있거나 후보가 오래됐으면 아무것도 안 한다."""
    if n <= 0 or active_keys(data) or not data.get("candidates"):
        return data, []
    made = _parse(data.get("generated_at"))
    if made and now - made > timedelta(days=max_age_days):
        return data, []
    ids = [c["id"] for c in data["candidates"] if c.get("key") not in exclude_keys][:n]
    data, added = enqueue(data, ids, now=now, max_per_day=max_per_day, slots=slots)
    for q in added[:1]:                      # 자동 선택의 첫 개는 지금 시간대 것이므로 바로 만든다
        q["due"] = now.isoformat(timespec="seconds")
    return data, added


def is_first_slot(now: datetime, slots=DEFAULT_SLOTS, window_min: int = 59) -> bool:
    """지금이 하루 첫 시간대(07:30) 창 안인가 — 매시 확인 실행이 이때 자동 선택을 한다."""
    h, m = (int(x) for x in str(slots[0]).split(":"))
    t = now.astimezone(KST)
    start = t.replace(hour=h, minute=m, second=0, microsecond=0)
    return start <= t < start + timedelta(minutes=window_min)


def parse_edits(text: str) -> list[tuple[str, str]]:
    """'id=cancel,id=15:30,id=2026-09-13T07:30' → [(id, 값)]. 형식이 이상한 조각은 버린다."""
    out = []
    for part in (text or "").split(","):
        if "=" not in part:
            continue
        pid, val = part.split("=", 1)
        pid, val = pid.strip(), val.strip()
        if len(pid) == 8 and val:
            out.append((pid, val))
    return out


def resolve_time(val: str, now: datetime) -> datetime | None:
    """'HH:MM' → 다음에 오는 그 시각(KST, 지났으면 내일). ISO 시각은 그대로(시간대 없으면 KST). 못 읽으면 None."""
    import re

    m = re.fullmatch(r"(\d{1,2}):(\d{2})", val)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if not (0 <= h < 24 and 0 <= mi < 60):
            return None
        base = now.astimezone(KST)
        t = base.replace(hour=h, minute=mi, second=0, microsecond=0)
        if t <= base:
            t += timedelta(days=1)
        return t
    try:
        t = datetime.fromisoformat(val)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=KST)


def apply_edits(data: dict, edits: list[tuple[str, str]], *, now: datetime) -> tuple[dict, list[str]]:
    """예약 항목 취소('cancel') 또는 시각 변경. queued 인 항목만 바꾼다. (파일, 바뀐 내용 설명들) 반환."""
    changed: list[str] = []
    queue = list(data.get("queue", []))
    for pid, val in edits:
        for i, q in enumerate(queue):
            if q.get("id") != pid or q.get("status") != "queued":
                continue
            if val == "cancel":
                queue[i] = {**q, "status": "cancelled", "finished_at": now.isoformat(timespec="seconds")}
                changed.append(f"취소 — {q.get('title', '')[:40]}")
            else:
                t = resolve_time(val, now)
                if t is None:
                    continue
                queue[i] = {**q, "due": t.isoformat(timespec="seconds")}
                changed.append(f"{t.astimezone(KST):%m/%d %H:%M} 로 변경 — {q.get('title', '')[:40]}")
            break
    return ({**data, "queue": queue} if changed else data), changed


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
