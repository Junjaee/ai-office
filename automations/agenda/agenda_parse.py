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
ROOM = re.compile(r"(본관|의원회관|국회)\s*(\d+)\s*호")
# 한글 파일을 글자로 뽑으면 생기는 찌꺼기(捤獥 汤捯, 󰠲󰠲…)를 버리고 읽을 수 있는 글자만 남긴다
KEEP = re.compile(r"[^가-힣0-9A-Za-z()\[\]., :~%·※\-/\n]")
# 표가 한 줄로 풀려 오므로 안건 번호·장소 칸·안내문 앞에서 끊는다("재경위 전체회의실"은 앞 낱말까지 묶는다).
# 셋 다 안 보이면 끊지 않는다 — 위원회마다 양식이 달라 억지로 쪼개면 엉뚱한 데가 잘린다.
BREAK = re.compile(r"\s(?=\d{1,2}\.\s)|\s(?=※)|\s(?=\S+\s+\S*회의실)")
ITEM = re.compile(r"^(\d{1,2}\.|※)")                      # 안건 줄 또는 ※ 안내
DATE_LINE = re.compile(r"^\d{1,2}\s*\.\s*\d{1,2}\s*\.\s*\(")  # "11. 30.(월)" — 안건이 아니라 날짜


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


def room_of(text: str) -> str:
    """본문에서 회의 장소("본관 430호"). 못 찾으면 빈 칸."""
    r = ROOM.search(text or "")
    return f"{r.group(1)} {r.group(2)}호" if r else ""


def title_of(label: str, m: Meeting, room: str = "") -> str:
    return f"[{label}] 제{m.n}차 전체회의" + (f" ({room})" if room else "")


def clean_body(text: str) -> str:
    """의사일정 본문을 읽을 수 있는 꼴로 — 찌꺼기를 버리고 줄을 끊는다(내용은 그대로 둔다)."""
    t = re.sub(r"[ \t]{2,}", " ", KEEP.sub(" ", text or "")).strip()
    return BREAK.sub("\n", t)


def agenda_text(text: str) -> str:
    """캘린더 설명에 넣을 안건. 번호로 시작하는 줄과 ※ 안내만 남긴다.

    표 머리글("일 시 안 건 명 비 고")·장소 칸은 뺀다(장소는 제목과 장소 칸에 따로 들어간다).
    안건을 하나도 못 찾으면 본문 전체를 그대로 — 양식이 다른 위원회에서 빈 설명이 되지 않게.
    """
    lines = [ln for ln in clean_body(text).split("\n") if ITEM.match(ln) and not DATE_LINE.match(ln)]
    return "\n".join(lines) if any(ln[0].isdigit() for ln in lines) else clean_body(text)


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


def build_event(label: str, m: Meeting, end_time: str, body: str = "") -> dict:
    """캘린더 일정 하나. 장소·안건은 의사일정 본문에서 그대로 가져온다(사용자 결정 2026-11-27)."""
    when = lambda dt: {"dateTime": dt.isoformat(), "timeZone": "Asia/Seoul"}  # noqa: E731
    room = room_of(body)
    return {"id": event_id(label, m), "summary": title_of(label, m, room), "location": room,
            "start": when(m.start), "end": when(end_of(m, end_time)), "description": agenda_text(body)}


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
