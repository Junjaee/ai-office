"""국회 인터넷의사중계(assembly.webcast.go.kr) 읽기 — 생중계 목록·채널 정보·위원 명단.

- parse_live_list() · channel_info() · is_live() · parse_xsami() · caption_kind() · parse_members() · meeting_title(): 순수 함수
- fetch(): 네트워크 (requests)

응답은 HTML/자바스크립트 안에 JSON 객체가 섞여 있어 정규식으로 {…} 를 뽑아 json 으로 읽는다(2026-11-05 확인).
해외 IP 차단 없음 — GitHub ubuntu 실행기에서 접속 확인(2026-11-05).
"""
from __future__ import annotations

import json
import re
import time

BASE = "https://assembly.webcast.go.kr/main/service/"
# 일반 GET 용 — Origin 은 붙이지 않는다(웹소켓 접속에만 쓴다)
GET_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Referer": "https://assembly.webcast.go.kr/main/",
}
HEADERS = {**GET_HEADERS, "Origin": "https://assembly.webcast.go.kr"}
FETCH_RETRIES = 3

_OBJ = re.compile(r"\{[^{}]*\}")
_XSAMI = re.compile(r'"xsami"\s*:\s*"([^"]+)"')
# 속기(일반) 자막 서버 — smi.webcast / smi-dw.webcast / smi-hy2.webcast … (플레이어 openos_util.js 의 smi_on 과 같은 분기)
_STT_HOST = re.compile(r"smi(-hy|-dw)?\d?\.webcast\.go\.kr")
_MEMBER = re.compile(r'"mname"\s*:\s*"([^"]+)"[^{}]*?"mdang"\s*:\s*"([^"]*)"')
_CLOCK = re.compile(r"\s*\[\d{1,2}:\d{2}(:\d{2})?\]\s*$")


def parse_live_list(text: str) -> list[dict]:
    """본문 속 {…} 객체들을 전부 json 으로 읽는다(깨진 것은 건너뜀)."""
    out: list[dict] = []
    for m in _OBJ.finditer(text or ""):
        try:
            d = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def channel_info(xcode: str, text: str) -> dict | None:
    """live_list 응답에서 xcode 가 같은 채널 하나."""
    for d in parse_live_list(text):
        if str(d.get("xcode")) == str(xcode):
            return d
    return None


def is_live(info: dict | None) -> bool:
    return bool(info) and str(info.get("xstat")) == "1"


def parse_xsami(play_html: str) -> str:
    """live_play.asp 응답의 자막 서버 주소. 없으면 ''."""
    m = _XSAMI.search(play_html or "")
    return m.group(1) if m else ""


def caption_kind(xsami: str) -> str:
    """'stt'(속기 자막, socket.io EIO=3) 또는 'ai'(AI 자막, 일반 WebSocket)."""
    return "stt" if _STT_HOST.search(xsami or "") else "ai"


def parse_members(map_html: str) -> list[tuple[str, str]]:
    """live_map.asp 의 의석 명단 → (이름, 정당)."""
    return [(m.group(1), m.group(2)) for m in _MEMBER.finditer(map_html or "")]


def meeting_title(info: dict) -> str:
    """xsubj 에서 ' [00:00]' 꼴 시계 꼬리를 뗀 회의 이름."""
    return _CLOCK.sub("", str(info.get("xsubj") or "")).strip()


def fetch(path: str, params: dict | None = None, session=None) -> str:
    """GET {BASE}{path}. 연결이 끊기면 3번까지 다시(2026-11-06 GitHub 서버 첫 실행에서 응답 없이 끊김). 4xx/5xx 는 예외."""
    import requests

    s = session or requests.Session()
    for attempt in range(FETCH_RETRIES):
        try:
            res = s.get(BASE + path, params=params, headers=GET_HEADERS, timeout=20)
            res.raise_for_status()
            return res.text
        except requests.exceptions.ConnectionError:
            if attempt == FETCH_RETRIES - 1:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")
