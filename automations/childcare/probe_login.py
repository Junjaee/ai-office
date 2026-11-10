"""아이사랑 로그인 길 찾기 (진단 전용, 비밀값 없이 돈다).

로그인 화면이 `/logout` 으로 되돌이치는 원인을 찾으려고 만든 도구다.
들어가는 길을 몇 가지로 나눠 각각 **쿠키 없는 새 브라우저**로 열고,
주소가 어디로 어떻게 넘어가는지(통합 로그인 서버 sso.childcare.go.kr 포함) 전부 찍는다.

    python automations/childcare/probe_login.py
"""
from __future__ import annotations

from playwright.sync_api import sync_playwright

PORTAL = "https://www.childcare.go.kr/"


def trace(p, label: str, steps) -> None:
    browser = p.chromium.launch()
    ctx = browser.new_context(locale="ko-KR", timezone_id="Asia/Seoul")  # 매번 쿠키 없이 시작
    page = ctx.new_page()
    hops: list[str] = []
    page.on("framenavigated", lambda f: hops.append(f.url[:130]) if f is page.main_frame else None)

    print(f"\n===== {label} =====")
    try:
        steps(page)
    except Exception as exc:  # noqa: BLE001 - 진단 도구라 중단 사유까지 찍고 넘어간다
        print("  중단:", str(exc).splitlines()[0][:150])
    page.wait_for_timeout(6000)

    for h in hops[:25]:
        print("  →", h)
    print("  제목:", page.title())
    print("  비번칸:", page.locator("input[type=password]").count(),
          "/ '아이디 로그인':", page.get_by_text("아이디 로그인", exact=True).count())
    browser.close()


def direct(page) -> None:
    page.goto(PORTAL + "?menuno=50", wait_until="domcontentloaded", timeout=60000)


def with_return_url(page) -> None:
    page.goto(PORTAL + "?menuno=50&returnUrl=/?menuno=1", wait_until="domcontentloaded", timeout=60000)


def click_from_main(page) -> None:
    page.goto(PORTAL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    page.get_by_role("link", name="로그인", exact=True).first.click(timeout=20000)


def main() -> None:
    with sync_playwright() as p:
        trace(p, "A. 로그인 주소로 바로", direct)
        trace(p, "B. 메인에서 로그인 링크 클릭", click_from_main)
        trace(p, "C. returnUrl 붙여서", with_return_url)


if __name__ == "__main__":
    main()
