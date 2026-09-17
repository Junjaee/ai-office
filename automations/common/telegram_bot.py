"""텔레그램 봇으로 글 보내기·대화방 찾기 (자동화 공통).

봇 토큰은 환경변수로만 받고, 오류 문구에도 남기지 않는다(`***` 로 가림) —
오류 문구는 상태 파일·실행 기록에 그대로 남기 때문이다.
"""
from __future__ import annotations

import os
import time

import requests

API = "https://api.telegram.org/bot{token}/{method}"


def telegram_env(chat_key: str = "TELEGRAM_CHAT_ID",
                 token_key: str = "TELEGRAM_BOT_TOKEN") -> tuple[str, str]:
    """(봇 토큰, 받는 분 대화방 번호). 하나라도 없으면 RuntimeError.

    보내는 봇과 받는 사람이 자동화마다 다르므로 환경변수 이름을 골라 쓴다
    (주말 일정=TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID — 캘린더 전송 전용 봇,
     상임위 메일=MAIL_TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID_MAIL). 폴백은 없다 — 엉뚱한 봇·사람으로 갈 수 있다.
    """
    token = (os.environ.get(token_key) or "").strip()
    chat = (os.environ.get(chat_key) or "").strip()
    missing = [k for k, v in ((token_key, token), (chat_key, chat)) if not v]
    if missing:
        raise RuntimeError(f"텔레그램 설정 없음: {', '.join(missing)}")
    return token, chat


def _hide(text: str, token: str) -> str:
    return text.replace(token, "***") if token else text


def send_message(token: str, chat_id: str, text: str, *, session=None, retries: int = 3,
                 delay: float = 1.0, timeout: int = 30) -> dict:
    """글 보내기. 텔레그램이 거절(4xx)하면 바로, 연결 문제·5xx 는 재시도한 뒤 RuntimeError."""
    s = session or requests.Session()
    url = API.format(token=token, method="sendMessage")
    body = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    last = ""
    for attempt in range(retries):
        try:
            res = s.post(url, json=body, timeout=timeout)
        except requests.exceptions.RequestException as exc:
            last = _hide(f"{type(exc).__name__}: {exc}", token)
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
            continue
        try:
            data = res.json()
        except ValueError:
            data = {}
        if res.status_code == 200 and data.get("ok"):
            return data.get("result") or {}
        desc = _hide(str(data.get("description") or f"HTTP {res.status_code}"), token)
        if res.status_code < 500 and res.status_code != 429:
            raise RuntimeError(f"텔레그램 전송 실패: {desc}")  # 받는 분이 '시작' 안 누름·번호 틀림 — 다시 해도 같다
        last = desc
        if attempt < retries - 1:
            time.sleep(delay * (attempt + 1))
    raise RuntimeError(f"텔레그램 전송 실패: {last}")


def list_chats(token: str, *, session=None, timeout: int = 30) -> list[dict]:
    """봇에게 최근 말을 건 대화방 목록(getUpdates). 받는 분이 봇에서 '시작'을 누른 뒤에 쓴다."""
    s = session or requests.Session()
    try:
        res = s.get(API.format(token=token, method="getUpdates"), params={"limit": 100}, timeout=timeout)
        data = res.json()
    except (requests.exceptions.RequestException, ValueError) as exc:
        raise RuntimeError(f"텔레그램 전송 실패: 대화방 목록을 받지 못했어요 ({type(exc).__name__})") from None
    if not data.get("ok"):
        raise RuntimeError(f"텔레그램 전송 실패: {_hide(str(data.get('description')), token)}")
    seen: set = set()
    out: list[dict] = []
    for upd in data.get("result") or []:
        for key in ("message", "edited_message", "channel_post", "my_chat_member", "chat_member"):
            chat = (upd.get(key) or {}).get("chat")
            if not chat or chat.get("id") in seen:
                continue
            seen.add(chat["id"])
            name = chat.get("title") or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x)
            out.append({"id": chat["id"], "type": chat.get("type", ""), "name": name or "", "username": chat.get("username") or ""})
    return out
