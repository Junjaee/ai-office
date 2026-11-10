"""아이사랑(childcare.go.kr) 브라우저 조작.

이 사이트는 화면을 자바스크립트로 그린 뒤 주소를 스스로 바꾼다(2026-11-10 실측).
그래서 주소로 바로 들어가면 메인으로 되돌아간다 — 반드시 "그려질 때까지 기다렸다가 누른다".

공개 저장소라서 로그인 뒤 화면은 사진으로 남기지 않고 구조(버튼·입력란 이름)만 뽑는다.
이름·생년월일·전화번호처럼 보이는 글자는 redact() 가 가린다.
"""
from __future__ import annotations

import re

BASE = "https://www.childcare.go.kr/"
MENU_RESERVE = "https://www.childcare.go.kr/?menuno=242"  # 시간제보육 신청 > 기관찾기

# 개인정보로 보일 수 있는 것 — 기록에 남기기 전에 가린다
_PATTERNS = [
    (re.compile(r"\d{6}[-\s]?\d{7}"), "<주민번호>"),
    (re.compile(r"01\d[-\s]?\d{3,4}[-\s]?\d{4}"), "<전화번호>"),
    (re.compile(r"\d{4}[-.]\d{2}[-.]\d{2}"), "<날짜>"),
    (re.compile(r"\d{6,}"), "<숫자>"),
]


def redact(text: str, limit: int = 60) -> str:
    """기록에 남겨도 되는 형태로 줄인다."""
    out = " ".join((text or "").split())
    for pat, mask in _PATTERNS:
        out = pat.sub(mask, out)
    return out[:limit]


def settle(page, timeout: int = 30000) -> None:
    """화면이 다 그려질 때까지 기다린다. 이 사이트는 제목이 늦게 채워진다."""
    page.wait_for_load_state("domcontentloaded", timeout=timeout)
    try:
        page.wait_for_function("() => document.title && document.title.length > 0", timeout=timeout)
    except Exception:  # noqa: BLE001 - 제목이 끝내 안 채워져도 진행은 해 본다
        pass
    page.wait_for_timeout(1500)


def open_main(page) -> None:
    page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
    settle(page)


def go_login(page) -> None:
    """메인에서 로그인 버튼을 눌러 통합회원 로그인 화면으로 간다."""
    open_main(page)
    page.get_by_role("link", name="로그인", exact=True).first.click(timeout=30000)
    settle(page)


def login(page, user_id: str, password: str) -> tuple[bool, str]:
    """아이디·비밀번호로 로그인. 성공 여부와 한 줄 설명을 돌려준다.

    비밀번호는 Playwright 가 입력란에 직접 넣는다. 값은 어디에도 기록하지 않는다.
    """
    go_login(page)

    tab = page.get_by_text("아이디 로그인", exact=True)
    if tab.count():
        tab.first.click()
        page.wait_for_timeout(1500)

    pw = page.locator("input[type=password]:visible").first
    if not pw.count():
        return False, "비밀번호 칸을 못 찾음 — 보안키패드가 막았거나 화면이 다름"

    # 비밀번호 칸 바로 앞의 보이는 글자 입력칸이 아이디 칸이다
    ids = page.locator("input[type=text]:visible, input[type=tel]:visible")
    if not ids.count():
        return False, "아이디 칸을 못 찾음"
    ids.last.fill(user_id)
    pw.fill(password)

    page.get_by_role("button", name=re.compile("로그인")).first.click(timeout=15000)
    settle(page)

    if page.get_by_role("link", name="로그아웃", exact=True).count():
        return True, "로그인 성공"
    alert = redact(page.locator(".alert, .error, #alertMsg").first.inner_text()) if page.locator(".alert, .error, #alertMsg").count() else ""
    return False, f"로그인 실패{' — ' + alert if alert else ''}"


def describe(page, limit: int = 40) -> list[str]:
    """지금 화면의 구조를 사람이 읽을 수 있게 뽑는다(값은 넣지 않는다)."""
    rows = page.evaluate(
        """() => [...document.querySelectorAll('a,button,input,select,label,h1,h2,h3,th')]
             .filter(e => e.offsetParent !== null)
             .map(e => [e.tagName.toLowerCase(), e.id || e.name || '', (e.className || '').toString().slice(0, 30),
                        (e.tagName === 'INPUT' || e.tagName === 'SELECT') ? (e.type || 'select') : (e.textContent || '')])"""
    )
    out = []
    for tag, ident, cls, text in rows[:limit]:
        out.append(f"{tag}#{ident or '-'}.{cls or '-'} :: {redact(text)}")
    return out


def open_reserve(page) -> list[str]:
    """시간제보육 신청(기관찾기) 화면으로 가서 구조를 뽑는다."""
    page.goto(MENU_RESERVE, wait_until="domcontentloaded", timeout=60000)
    settle(page)
    return [f"주소: {page.url}", f"제목: {page.title()}"] + describe(page)
