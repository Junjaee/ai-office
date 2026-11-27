"""의사일정 — 한글 파일 첫머리에서 회의를 읽고 캘린더 일정으로 바꾼다 (순수 함수, 네트워크 없음).

첫머리 모양이 한 가지가 아니다. 글자 규칙만으로 읽는다(AI 호출 없음).
  제11차 재정경제기획위원회 2026. 11. 26.(목) 10:00          ← 차수 바로 뒤에 날짜
  제12차 재정경제기획위원회 … 일 시 안 건 명 비 고 11. 30.(월) 14:00   ← 표 머리글이 끼고 연도가 없다
그래서 차수·회의체를 먼저 찾고 **그 뒤**에서 날짜·시각을 찾는다. 연도가 없으면 회의 폴더
이름(`20261130_전체위`)에서 가져오되, 월·일이 폴더와 다르면 읽지 않는다 — 틀린 일정보다 없는 편이 낫다.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
HEAD = re.compile(r"제\s*(\d+)\s*차\s+(\S*위원회)")
WHEN = re.compile(r"(?:(\d{4})\s*\.\s*)?(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*\(.\)\s*(\d{1,2})\s*:\s*(\d{2})")
FOLDER_DATE = re.compile(r"^(\d{8})_")


@dataclass(frozen=True)
class Meeting:
    n: int            # 차수
    body: str         # 회의체 이름 그대로 ("재정경제기획위원회")
    start: datetime   # KST


def parse_header(text: str, folder_date: str = "") -> Meeting | None:
    """본문 앞부분에서 차수·회의체·날짜·시각. 못 읽으면 None(넣지 않는다 — 틀린 일정보다 없는 편이 낫다).

    folder_date: 회의 폴더 이름의 날짜 8자리("20261130"). 본문에 연도가 없을 때만 쓴다.
    """
    head = HEAD.search(text or "")
    if not head:
        return None
    when = WHEN.search(text, head.end())
    if not when:
        return None
    y, mo, d, h, mi = when.groups()
    if not y:
        if len(folder_date) != 8 or not folder_date.isdigit():
            return None                                   # 연도를 어디서도 못 구한다
        if f"{int(mo):02d}{int(d):02d}" != folder_date[4:]:
            return None                                   # 폴더가 말하는 날과 다르다 — 엉뚱한 날짜를 넣지 않는다
        y = folder_date[:4]
    try:
        return Meeting(int(head.group(1)), head.group(2),
                       datetime(int(y), int(mo), int(d), int(h), int(mi), tzinfo=KST))
    except ValueError:
        return None


def is_sub(m: Meeting) -> bool:
    """소위원회 — 캘린더에 넣지 않는다(제목의 위원회 이름이 발언 요약을 본회의 채널로 깨운다)."""
    return "소위" in m.body


def title_of(label: str, m: Meeting) -> str:
    return f"[{label}] 제{m.n}차 전체회의"


def event_id(label: str, m: Meeting) -> str:
    """같은 회의는 늘 같은 id — 두 번 넣지 않고, 사람이 지운 일정을 되살리지도 않는다(지운 id 는 409).
    캘린더 id 는 0-9a-v 만 받는다 → 16진수."""
    key = f"{label}|{m.body}|{m.start.date().isoformat()}|{m.n}"
    return "ao" + hashlib.sha1(key.encode("utf-8")).hexdigest()


def end_of(m: Meeting, end_time: str) -> datetime:
    """끝 시각은 의사일정에 없다 → 그날 end_time("18:00")까지, 시작이 그 뒤면 2시간."""
    h, mi = (int(x) for x in end_time.split(":"))
    end = m.start.replace(hour=h, minute=mi)
    return end if end > m.start else m.start + timedelta(hours=2)


def build_event(label: str, m: Meeting, end_time: str, description: str = "") -> dict:
    when = lambda dt: {"dateTime": dt.isoformat(), "timeZone": "Asia/Seoul"}  # noqa: E731
    return {"id": event_id(label, m), "summary": title_of(label, m),
            "start": when(m.start), "end": when(end_of(m, end_time)), "description": description}


def _start(item: dict) -> datetime | None:
    raw = (item.get("start") or {}).get("dateTime")
    return datetime.fromisoformat(raw) if raw else None


def decide(label: str, m: Meeting, day_items: list[dict], also: tuple[str, ...] = ()) -> str:
    """그날 캘린더 일정을 보고 할 일을 정한다: add · same · move(시각이 바뀜) · manual(사람이 이미 넣음).
    also: 사람이 그 위원회 회의를 적을 때 쓰는 다른 말("인사청문회")."""
    eid = event_id(label, m)
    mine = next((it for it in day_items if it.get("id") == eid), None)
    if mine:
        return "same" if _start(mine) == m.start else "move"
    for it in day_items:
        title = it.get("summary") or ""
        if _start(it) == m.start and any(w in title for w in (label, m.body, *also)):
            return "manual"
    return "add"


def folder_date(name: str) -> str | None:
    """회의 폴더 이름("20261126_전체위")의 날짜 8자리. 회의 폴더가 아니면 None."""
    m = FOLDER_DATE.match(name or "")
    return m.group(1) if m else None
