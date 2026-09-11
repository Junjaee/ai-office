"""주말 일정 — 구글 캘린더에서 토·일 일정을 읽어 텔레그램 글로 만든다.

- upcoming_weekend(): 오늘 이후 가장 가까운 토·일
- calendar_service() · fetch_events(): Calendar API (반복 일정은 하나씩 펼쳐 받는다)
- to_events() · build_message(): 순수 함수 (테스트는 네트워크 없이)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

KST = timezone(timedelta(hours=9))
WEEKDAYS = "월화수목금토일"
TELEGRAM_LIMIT = 4096
CUT_NOTE = "… 너무 길어 일부만 보냈어요"


@dataclass(frozen=True)
class Event:
    day: date      # 이 일정이 걸친 날(토 또는 일)
    start: str     # "10:00" · "종일" · "~"(전날부터 이어짐)
    end: str       # "12:00" · "~"(다음 날로 이어짐) · ""(종일)
    title: str
    location: str


def upcoming_weekend(today: date) -> tuple[date, date]:
    """오늘 이후 가장 가까운 토요일(오늘이 토요일이면 오늘)과 그다음 일요일."""
    sat = today + timedelta(days=(5 - today.weekday()) % 7)
    return sat, sat + timedelta(days=1)


def _order(e: Event) -> tuple:
    rank = 0 if e.start == "종일" else 1 if e.start == "~" else 2
    return (e.day, rank, e.start)


def to_events(items: list[dict], days: tuple[date, ...]) -> list[Event]:
    """Calendar API 일정 → 날짜별 한 줄. 여러 날에 걸친 일정은 걸친 날마다 한 줄, 취소된 일정은 뺀다."""
    out: list[Event] = []
    for it in items:
        if it.get("status") == "cancelled":
            continue
        title = (it.get("summary") or "").strip() or "(제목 없음)"
        loc = (it.get("location") or "").strip()
        s, e = it.get("start") or {}, it.get("end") or {}
        if "date" in s:  # 종일 — 끝 날짜는 포함하지 않는다
            sd = date.fromisoformat(s["date"])
            ed = date.fromisoformat(e.get("date") or s["date"])
            if ed <= sd:
                ed = sd + timedelta(days=1)
            out += [Event(d, "종일", "", title, loc) for d in days if sd <= d < ed]
            continue
        if "dateTime" not in s:
            continue
        sdt = datetime.fromisoformat(s["dateTime"]).astimezone(KST)
        edt = datetime.fromisoformat(e.get("dateTime") or s["dateTime"]).astimezone(KST)
        for d in days:
            day_start = datetime.combine(d, time.min, KST)
            day_end = day_start + timedelta(days=1)
            if sdt < day_end and edt > day_start:  # 이 날에 걸친다
                st = sdt.strftime("%H:%M") if sdt >= day_start else "~"
                en = edt.strftime("%H:%M") if edt < day_end else ("24:00" if edt == day_end else "~")
                out.append(Event(d, st, en, title, loc))
    return sorted(out, key=_order)


def _when(e: Event) -> str:
    if e.start == "종일":
        return "종일"
    return f"{'' if e.start == '~' else e.start}~{'' if e.end == '~' else e.end}"


# 제목을 가릴 때 보여 줄 일정 종류 — 앞에서부터 먼저 맞는 것. 식사는 시작 시각으로 아침·점심·저녁
KINDS = [
    (("등산", "산행", "둘레길", "트레킹"), "등산"),
    (("골프",), "골프"),
    (("운동", "헬스", "축구", "야구", "배드민턴", "마라톤"), "운동"),
    (("결혼", "예식", "웨딩"), "결혼식"),
    (("장례", "조문", "빈소", "발인", "추모"), "조문"),
    (("식사", "오찬", "만찬", "조찬", "회식", "식당", "저녁", "점심", "밥"), "식사"),
    (("회의", "간담회", "면담", "미팅", "협의", "회동", "보고"), "회의"),
    (("촬영", "방송", "인터뷰", "녹화", "라디오", "유튜브"), "방송·촬영"),
    (("축제", "행사", "대회", "기념식", "발대식", "개막", "시상", "축사", "포럼", "토론회", "세미나", "박람회"), "행사"),
]


def _meal(e: Event) -> str:
    hhmm = e.start if e.start[:1].isdigit() else (e.end if e.end[:1].isdigit() else "")
    if not hhmm:
        return "식사"
    h = int(hhmm[:2])
    return "아침 식사" if h < 10 else "점심 식사" if h < 15 else "저녁 식사"


def describe(e: Event, reveal_keywords: list[str] | None) -> str:
    """보낼 한 줄의 내용.

    reveal_keywords 가 None 이면 그대로. 목록이면 그 단어가 제목·장소에 든 일정만 그대로 보여 주고,
    나머지는 누구와 무엇을 하는지 빼고 종류만("등산 일정", "저녁 식사 일정") — 사용자 결정 2026-09-11.
    """
    if reveal_keywords is None or any(k and (k in e.title or k in e.location) for k in reveal_keywords):
        return e.title + (f" @ {e.location}" if e.location else "")
    for words, kind in KINDS:
        if any(w in e.title for w in words):
            return f"{_meal(e) if kind == '식사' else kind} 일정"
    return "기타 일정"


def build_message(title: str, days: tuple[date, date], events: list[Event],
                  reveal_keywords: list[str] | None = None) -> str:
    """텔레그램으로 보낼 글. 날짜마다 제목 줄, 일정이 없으면 '일정 없음'. 4096자를 넘으면 잘라 표시.
    일정 내용은 describe() 규칙(reveal_keywords)으로 가린다."""
    sat, sun = days
    # 첫 줄: "이준석 주말 일정(9/12 토 ~ 9/13 일)" (사용자 지정 2026-09-11)
    lines = [f"{title}({sat.month}/{sat.day} {WEEKDAYS[sat.weekday()]} ~ {sun.month}/{sun.day} {WEEKDAYS[sun.weekday()]})"]
    for d in days:
        lines += ["", f"■ {d.month}월 {d.day}일 ({WEEKDAYS[d.weekday()]})"]
        todays = [e for e in events if e.day == d]
        if not todays:
            lines.append("· 일정 없음")
        for e in todays:
            lines.append(f"· {_when(e)}  {describe(e, reveal_keywords)}")
    text = "\n".join(lines)
    if len(text) <= TELEGRAM_LIMIT:
        return text
    kept: list[str] = []
    for ln in lines:
        if len("\n".join(kept + [ln, CUT_NOTE])) > TELEGRAM_LIMIT:
            break
        kept.append(ln)
    return "\n".join(kept + [CUT_NOTE])


def calendar_service():
    """공용 구글 토큰(GOOGLE_*)으로 Calendar API 클라이언트.

    권한(scopes)을 따로 요청하지 않는다 — 요청한 권한이 토큰에 없으면 갱신 자체가 invalid_scope 로 실패하므로,
    토큰이 가진 권한 그대로 받고 캘린더 권한이 없으면 호출 때 403 으로 알게 한다(→ '캘린더 읽기 실패').
    """
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    from errors import MissingGoogleToken

    keys = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")
    missing = [k for k in keys if not (os.environ.get(k) or "").strip()]
    if missing:
        raise MissingGoogleToken(f"Google 인증 환경변수가 없습니다: {', '.join(missing)}")
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def fetch_events(service, calendar_id: str, days: tuple[date, ...]) -> list[dict]:
    """days 첫날 0시 ~ 마지막 날 다음 0시(KST) 사이 일정. 반복 일정은 하나씩, 시작 순."""
    start = datetime.combine(days[0], time.min, KST)
    end = datetime.combine(days[-1] + timedelta(days=1), time.min, KST)
    items: list[dict] = []
    token = None
    while True:
        res = service.events().list(
            calendarId=calendar_id, timeMin=start.isoformat(), timeMax=end.isoformat(),
            singleEvents=True, orderBy="startTime", maxResults=250, pageToken=token,
        ).execute()
        items += res.get("items", [])
        token = res.get("nextPageToken")
        if not token:
            return items
