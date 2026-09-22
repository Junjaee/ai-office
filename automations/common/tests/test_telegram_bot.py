"""텔레그램 보내기·대화방 찾기 — 가짜 세션으로 (네트워크 없음)."""
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "common"))
from telegram_bot import list_chats, send_message, telegram_env  # noqa: E402

TOKEN = "123456:SECRET-TOKEN"


class FakeResp:
    def __init__(self, status, data):
        self.status_code = status
        self._data = data

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append(("post", url, json))
        return self._next()

    def get(self, url, params=None, timeout=None):
        self.calls.append(("get", url, params))
        return self._next()

    def _next(self):
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_send_message_posts_plain_text():
    s = FakeSession(FakeResp(200, {"ok": True, "result": {"message_id": 7}}))
    send_message(TOKEN, "42", "안녕", session=s, delay=0)
    _, url, body = s.calls[0]
    assert url == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert body == {"chat_id": "42", "text": "안녕", "disable_web_page_preview": True}


def test_send_message_error_is_korean_and_never_contains_token():
    s = FakeSession(FakeResp(403, {"ok": False, "description": "Forbidden: bot can't initiate conversation with a user"}))
    with pytest.raises(RuntimeError) as e:
        send_message(TOKEN, "42", "안녕", session=s, delay=0)
    assert "텔레그램 전송 실패" in str(e.value) and "initiate" in str(e.value)
    assert TOKEN not in str(e.value)
    assert len(s.calls) == 1  # 4xx 는 다시 해도 같으니 재시도하지 않는다


def test_send_message_retries_network_error_and_hides_token():
    err = requests.exceptions.ConnectionError(f"HTTPSConnectionPool: /bot{TOKEN}/sendMessage")
    s = FakeSession(err, err, err)
    with pytest.raises(RuntimeError) as e:
        send_message(TOKEN, "42", "안녕", session=s, delay=0)
    assert len(s.calls) == 3
    assert TOKEN not in str(e.value) and "***" in str(e.value)


def test_list_chats_collects_unique_chats_from_updates():
    data = {"ok": True, "result": [
        {"update_id": 1, "message": {"chat": {"id": 42, "type": "private", "first_name": "길동", "last_name": "홍", "username": "hong"}, "text": "/start"}},
        {"update_id": 2, "message": {"chat": {"id": 42, "type": "private", "first_name": "길동"}, "text": "안녕"}},
        {"update_id": 3, "my_chat_member": {"chat": {"id": -100, "type": "group", "title": "가족방"}}},
    ]}
    chats = list_chats(TOKEN, session=FakeSession(FakeResp(200, data)))
    assert chats == [
        {"id": 42, "type": "private", "name": "길동 홍", "username": "hong"},
        {"id": -100, "type": "group", "name": "가족방", "username": ""},
    ]


def test_telegram_env_requires_both(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    with pytest.raises(RuntimeError, match="텔레그램 설정 없음"):
        telegram_env()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    assert telegram_env() == (TOKEN, "42")


def test_telegram_env_picks_named_bot_and_chat(monkeypatch):
    """자동화마다 다른 봇·받는 사람을 쓴다. 없으면 기본값으로 떨어지지 않고 실패한다."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setenv("NOTICE_530_BOT_TOKEN", "999:NOTICE")
    monkeypatch.setenv("NOTICE_530_CHAT_ID", "77")
    assert telegram_env("NOTICE_530_CHAT_ID", "NOTICE_530_BOT_TOKEN") == ("999:NOTICE", "77")

    monkeypatch.delenv("NOTICE_530_BOT_TOKEN")
    with pytest.raises(RuntimeError, match="NOTICE_530_BOT_TOKEN"):
        telegram_env("NOTICE_530_CHAT_ID", "NOTICE_530_BOT_TOKEN")
