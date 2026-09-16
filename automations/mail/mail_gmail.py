"""상임위 메일 — 지메일에서 새 메일을 찾아 라벨을 붙이고 알림 글을 만든다.

- gmail_service() · search_messages() · message_meta() · ensure_label() · file_message(): Gmail API
- build_query() · describe() · build_notice() · safe_lines(): 순수 함수 (테스트는 네트워크 없이)

**공개 저장소 주의**: 메일 제목·보낸사람은 텔레그램으로만 보낸다. 상태 파일·실행 일지에 남는 값
(safe_lines)에는 위원회 이름과 건수만 넣는다 (사용자 결정 2026-09-16).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta, timezone

KST = timezone(timedelta(hours=9))

TELEGRAM_LIMIT = 4096
CUT_NOTE = "… 너무 길어 일부만 보냈어요"
THREAD_URL = "https://mail.google.com/mail/u/0/#all/{thread_id}"


@dataclass(frozen=True)
class Mail:
    id: str
    thread_id: str
    label: str                 # 붙일 라벨(위원회 이름). 예 "재경위"
    when: str                  # "09:41" 처럼 보낸 시각(KST)
    sender: str                # 보낸 사람 이름
    subject: str
    attachments: tuple[str, ...] = field(default=())
    ts: int = 0                # 받은 시각(밀리초). 여러 위원회를 섞어 시간순으로 세울 때 쓴다


def build_query(rule: dict, days: int) -> str:
    """규칙 하나 → 지메일 검색어. 이미 라벨이 붙은 메일(=처리 끝)과 오래된 메일은 뺀다."""
    label = (rule.get("label") or "").strip()
    parts = [(rule.get("query") or "").strip()]
    if label:
        parts.append(f'-label:"{label}"')
    if days > 0:
        parts.append(f"newer_than:{days}d")
    return " ".join(p for p in parts if p)


def _clean_sender(raw: str) -> str:
    """'"재정경제기획위원회" <fec@assembly.go.kr>' → '재정경제기획위원회'."""
    raw = (raw or "").strip()
    if "<" in raw:
        raw = raw.split("<", 1)[0]
    return raw.strip().strip('"').strip() or "(보낸사람 없음)"


def describe(m: Mail) -> list[str]:
    """텔레그램에 보일 한 메일의 줄들."""
    lines = [f"[{m.label}] {m.subject or '(제목 없음)'}",
             f"· {m.when}  {_clean_sender(m.sender)}"]
    if m.attachments:
        lines.append(f"· 첨부 {len(m.attachments)}개: " + ", ".join(m.attachments))
    lines.append(THREAD_URL.format(thread_id=m.thread_id))
    return lines


def build_notice(mails: list[Mail]) -> str:
    """텔레그램으로 보낼 글. 4096자를 넘으면 메일 단위로 잘라 표시."""
    head = f"새 상임위 메일 {len(mails)}건"
    blocks = [[head]] + [describe(m) for m in mails]
    text = "\n\n".join("\n".join(b) for b in blocks)
    if len(text) <= TELEGRAM_LIMIT:
        return text
    kept = [blocks[0]]
    for b in blocks[1:]:
        if len("\n\n".join("\n".join(x) for x in kept + [b, [CUT_NOTE]])) > TELEGRAM_LIMIT:
            break
        kept.append(b)
    return "\n\n".join("\n".join(b) for b in kept + [[CUT_NOTE]])


def safe_lines(mails: list[Mail], rules: list[dict]) -> list[str]:
    """상태 파일·실행 일지에 남길 줄 — 제목·보낸사람 없이 위원회별 건수만 (저장소가 공개라서)."""
    out = []
    for rule in rules:
        label = (rule.get("label") or "").strip()
        n = sum(1 for m in mails if m.label == label)
        if n:
            out.append(f"{label} {n}건")
    return out or ["새 메일 없음"]


# ───────────────────────── Gmail API ─────────────────────────

def gmail_service():
    """공용 구글 토큰(GOOGLE_*)으로 Gmail 클라이언트.

    권한(scopes)을 따로 요청하지 않는다 — 요청한 권한이 토큰에 없으면 갱신 자체가 invalid_scope 로
    실패하므로, 토큰이 가진 권한 그대로 받고 없으면 호출 때 403 으로 알게 한다(→ '메일 읽기 실패').
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
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def search_messages(service, query: str, limit: int = 20) -> list[str]:
    """검색어에 맞는 메시지 id (최신 순, 최대 limit 개)."""
    res = service.users().messages().list(userId="me", q=query, maxResults=limit).execute()
    return [m["id"] for m in (res.get("messages") or [])]


def _attachment_names(part: dict, out: list[str]) -> None:
    name = (part.get("filename") or "").strip()
    if name:
        out.append(name)
    for child in part.get("parts") or []:
        _attachment_names(child, out)


def _hhmm(date_header: str) -> str:
    """'Wed, 16 Sep 2026 09:41:59 +0900' → '9/16 09:41' (KST). 못 읽으면 원문 앞부분."""
    from email.utils import parsedate_to_datetime

    try:
        dt = parsedate_to_datetime(date_header).astimezone(KST)
    except (TypeError, ValueError):
        return (date_header or "")[:22]
    return f"{dt.month}/{dt.day} {dt:%H:%M}"


def message_meta(service, message_id: str) -> Mail:
    """메시지 하나의 제목·보낸사람·시각·첨부 이름. 라벨은 뒤에서 채운다."""
    data = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    headers = {h["name"]: h["value"] for h in (data.get("payload") or {}).get("headers", [])}
    names: list[str] = []
    _attachment_names(data.get("payload") or {}, names)
    return Mail(
        id=message_id,
        thread_id=data.get("threadId") or message_id,
        label="",
        when=_hhmm(headers.get("Date", "")),
        sender=headers.get("From", ""),
        subject=(headers.get("Subject") or "").strip(),
        attachments=tuple(names),
        ts=int(data.get("internalDate") or 0),
    )


def ensure_label(service, name: str, cache: dict | None = None) -> str:
    """라벨 id. 없으면 만든다(지메일 왼쪽에 폴더처럼 보인다)."""
    if cache is not None and name in cache:
        return cache[name]
    for label in service.users().labels().list(userId="me").execute().get("labels", []):
        if label.get("name") == name:
            if cache is not None:
                cache[name] = label["id"]
            return label["id"]
    created = service.users().labels().create(userId="me", body={
        "name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show",
    }).execute()
    if cache is not None:
        cache[name] = created["id"]
    return created["id"]


def file_message(service, message_id: str, label_id: str) -> None:
    """라벨을 붙이고 받은편지함에서 뺀다(= 그 라벨 폴더로 정리). 읽음 표시는 건드리지 않는다."""
    service.users().messages().modify(userId="me", id=message_id, body={
        "addLabelIds": [label_id], "removeLabelIds": ["INBOX"],
    }).execute()
