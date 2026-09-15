"""화성시 공고 전용 텔레그램 발송(동탄 전용 봇).

봇 토큰·대화방은 환경변수 HSCITY_TELEGRAM_BOT_TOKEN / HSCITY_TELEGRAM_CHAT_ID 로만 받는다.
오류 문구에는 토큰을 남기지 않는다(상태 파일에 그대로 커밋되므로).
"""
from __future__ import annotations

import os
import time

import requests

API = "https://api.telegram.org/bot{token}/{method}"


def telegram_env() -> tuple[str, str]:
    token = (os.environ.get("HSCITY_TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (os.environ.get("HSCITY_TELEGRAM_CHAT_ID") or "").strip()
    missing = [k for k, v in (("HSCITY_TELEGRAM_BOT_TOKEN", token), ("HSCITY_TELEGRAM_CHAT_ID", chat)) if not v]
    if missing:
        raise RuntimeError(f"텔레그램 설정 없음: {', '.join(missing)}")
    return token, chat


def _hide(text: str, token: str) -> str:
    return text.replace(token, "***") if token else text


def send_message(token: str, chat_id: str, text: str, *, session=None, retries: int = 3,
                 delay: float = 1.0, timeout: int = 30) -> dict:
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
            raise RuntimeError(f"텔레그램 전송 실패: {desc}")
        last = desc
        if attempt < retries - 1:
            time.sleep(delay * (attempt + 1))
    raise RuntimeError(f"텔레그램 전송 실패: {last}")


def format_message(post: dict) -> str:
    tags = []
    if post.get("is_star"):
        tags.append("⭐화성시을")
    if post.get("is_citywide"):
        tags.append("[시 전역]")
    tagline = (" " + " ".join(tags)) if tags else ""
    n_att = len(post.get("attachments", []))
    att_line = f"📎 첨부 {n_att}건 · " if n_att else ""
    summary = (post.get("summary") or "").strip()
    return (
        f"🏛️ [{post['board_name']}] 화성시청 새 공고{tagline}\n"
        f"─────────────\n"
        f"📌 {post['title']}\n"
        f"🏢 {post.get('dept', '')} · 📅 {post.get('date', '')}\n"
        + (f"📝 {summary}\n" if summary else "")
        + f"{att_line}🔗 {post['url']}"
    )
