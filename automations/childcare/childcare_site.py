"""아이사랑(childcare.go.kr) 브라우저 조작.

이 사이트는 화면을 자바스크립트로 그린 뒤 주소를 스스로 바꾼다(2026-11-10 실측).
그래서 주소로 바로 들어가면 메인으로 되돌아간다 — 반드시 "그려질 때까지 기다렸다가 누른다".

공개 저장소라서 로그인 뒤 화면은 사진으로 남기지 않고 구조(버튼·입력란 이름)만 뽑는다.
이름·생년월일·전화번호처럼 보이는 글자는 redact() 가 가린다.
"""
from __future__ import annotations

import re
from urllib.parse import quote

BASE = "https://www.childcare.go.kr/"
MENU_RESERVE = "https://www.childcare.go.kr/?menuno=242"  # 시간제보육 신청 > 기관찾기

# 로그인은 아이사랑이 아니라 유보통합포털의 통합회원 로그인에서 한다 (2026-11-10 사용자가 알려 줌).
# 아이사랑의 "로그인" 링크(?menuno=50)를 타면 sso.childcare.go.kr/sso/logout 과 메인 사이를
# 끝없이 오가며 로그인 화면이 안 뜬다. 여기로 바로 들어가면 뜬다.
LOGIN = "https://enter.childinfo.go.kr/icms/total/login/login.html"

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


def login(page, user_id: str, password: str, return_to: str = MENU_RESERVE) -> tuple[bool, str]:
    """통합회원 아이디 로그인. 끝나면 return_to 주소로 돌아온다.

    로그인 화면은 보안키패드가 꺼진 평범한 폼이다(숨은 값 `kybrdscrtyyn=N`, 2026-11-10 확인).
    아이디 `#mbrid`, 비밀번호 `#uspass`, 보내기는 `ssoLoginCheck()` 를 부르는 <a> 다.
    비밀번호 값은 어디에도 기록하지 않는다.
    """
    page.goto(f"{LOGIN}?ltype=id&returnUrl={quote(return_to, safe='')}",
              wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector("#mbrid", timeout=30000)

    page.fill("#mbrid", user_id)
    page.fill("#uspass", password)
    page.locator("a[onclick*='ssoLoginCheck']").first.click(timeout=20000)
    settle(page)

    if "childcare.go.kr" in page.url:
        return True, "로그인 성공"

    # 실패하면 화면에 뜬 안내(팝업·경고)를 가린 형태로 돌려준다
    notice = ""
    for sel in (".layer-popup:visible", ".alert:visible", ".error:visible", "#alertMsg:visible"):
        box = page.locator(sel)
        if box.count():
            notice = redact(box.first.inner_text(), limit=100)
            break
    return False, f"로그인 실패{' — ' + notice if notice else f' (머문 주소 {page.url[:60]})'}"


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
