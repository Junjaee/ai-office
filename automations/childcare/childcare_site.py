"""아이사랑(childcare.go.kr) 브라우저 조작.

이 사이트는 화면을 자바스크립트로 그린 뒤 주소를 스스로 바꾼다(2026-11-10 실측).
그래서 주소로 바로 들어가면 메인으로 되돌아간다 — 반드시 "그려질 때까지 기다렸다가 누른다".

공개 저장소라서 로그인 뒤 화면은 사진으로 남기지 않고 구조(버튼·입력란 이름)만 뽑는다.
이름·생년월일·전화번호처럼 보이는 글자는 redact() 가 가린다.
"""
from __future__ import annotations

import re
import time
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


def wait_ready(page, selector: str, timeout_ms: int = 40000) -> None:
    """화면에 그것이 생길 때까지 기다린다. 중간에 튕겨도 견딘다.

    이 사이트는 화면을 그린 뒤 주소를 스스로 `?menuno=1&state=…` 로 한 번 더 바꾼다.
    그 틈에 건드리면 'Execution context was destroyed' 가 난다(2026-11-11 실패).
    그래서 튕김을 무시하고 다시 보고, 두 번 연속 보일 때만 됐다고 친다.
    """
    end = time.monotonic() + timeout_ms / 1000
    last = ""
    while time.monotonic() < end:
        try:
            if page.query_selector(selector):
                time.sleep(0.3)
                if page.query_selector(selector):  # 또 튕기지 않았는지 한 번 더
                    return
        except Exception as exc:  # noqa: BLE001 - 튕기는 중이면 다시 본다
            last = str(exc).splitlines()[0][:70]
        time.sleep(0.3)
    raise RuntimeError(f"화면이 안 떠요 ({selector})" + (f" — {last}" if last else ""))


def safe_eval(page, js: str, arg=None, tries: int = 6):
    """page.evaluate 를 튕김에 견디게 감싼다.

    이 사이트는 주소를 스스로 바꾸는 버릇이 있어, 하필 그 순간 실행하면
    'Execution context was destroyed' 로 죽는다. 그럴 때만 다시 해 본다.
    """
    last = None
    for _ in range(tries):
        try:
            return page.evaluate(js, arg) if arg is not None else page.evaluate(js)
        except Exception as exc:  # noqa: BLE001 - 이동 중이면 다시, 아니면 그대로 올린다
            msg = str(exc)
            if "context was destroyed" not in msg and "Target closed" not in msg:
                raise
            last = msg.splitlines()[0][:70]
            time.sleep(0.4)
    raise RuntimeError(f"화면이 계속 바뀌어 손을 못 댔어요 — {last}")


def tap_text(page, selector: str, text: str, timeout_ms: int = 30000) -> None:
    """그 글자를 가진 항목이 생길 때까지 기다렸다 누른다.

    지역 목록은 접혀 있어 Playwright 가 클릭을 거부하고(안 보인다며),
    구·군 목록은 시·도를 고른 뒤 따로 받아 오느라 늦게 생긴다. 둘 다 여기서 처리한다.
    """
    js = """([sel, want]) => {
              const a = [...document.querySelectorAll(sel)].find(e => e.textContent.trim() === want);
              if (!a) return false;
              a.click();
              return true;
            }"""
    end = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < end:
        if safe_eval(page, js, [selector, text]):
            return
        time.sleep(0.3)
    raise RuntimeError(f"'{text}' 를 못 찾았어요 ({selector})")


def settle(page, timeout: int = 30000) -> None:
    """화면이 다 그려질 때까지 기다린다. 이 사이트는 제목이 늦게 채워진다."""
    end = time.monotonic() + timeout / 1000
    while time.monotonic() < end:
        try:
            page.wait_for_function("() => document.title && document.title.length > 0", timeout=5000)
            time.sleep(0.8)
            return
        except Exception:  # noqa: BLE001 - 튕기는 중이면 다시 본다
            time.sleep(0.3)


def login(page, user_id: str, password: str, return_to: str = MENU_RESERVE) -> tuple[bool, str]:
    """통합회원 아이디 로그인. 끝나면 return_to 주소로 돌아온다.

    로그인 화면은 보안키패드가 꺼진 평범한 폼이다(숨은 값 `kybrdscrtyyn=N`, 2026-11-10 확인).
    아이디 `#mbrid`, 비밀번호 `#uspass`, 보내기는 `ssoLoginCheck()` 를 부르는 <a> 다.
    비밀번호 값은 어디에도 기록하지 않는다.
    """
    # 거부 사유는 보통 경고창(alert)으로 온다. 자동 브라우저는 조용히 닫아 버리므로 붙잡아 둔다.
    alerts: list[str] = []
    page.on("dialog", lambda d: (alerts.append(d.message), d.accept()))

    page.goto(f"{LOGIN}?ltype=id&returnUrl={quote(return_to, safe='')}",
              wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector("#mbrid", timeout=30000)

    page.fill("#mbrid", user_id)
    page.fill("#uspass", password)
    page.locator("a[onclick*='ssoLoginCheck']").first.click(timeout=20000)
    settle(page)


    if "childcare.go.kr" in page.url:
        return True, "로그인 성공"

    if alerts:
        return False, "로그인 실패 — " + redact(" / ".join(alerts), limit=140)

    # 경고창이 없으면 화면에 박힌 안내문을 찾는다
    for sel in (".layer-popup:visible", ".alert:visible", ".error:visible", "#alertMsg:visible", ".txt_error:visible"):
        box = page.locator(sel)
        if box.count():
            return False, "로그인 실패 — " + redact(box.first.inner_text(), limit=140)
    return False, f"로그인 실패 (안내문 없음, 머문 주소 {page.url[:60]})"


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


# ───────── 예약 (2026-11-11) ─────────
# 기관찾기 화면의 예약 버튼은 <a id="occasionRes" data-stcode="11710000741"> 이고,
# 누르면 시간제보육 입소신청 화면(?menuno=605)으로 넘어간다. 거기 폼 #pfrm 에
# resdtArray(날짜)·resbgntmArray(시작)·resendtmArray(종료)·resclseqArray(반) 이 들어간다.

MENU_APPLY = "https://www.childcare.go.kr/?menuno=605"  # 시간제보육 입소신청


def is_logged_in(page) -> bool:
    """마이룸·로그아웃이 보이면 로그인 상태."""
    try:
        page.wait_for_selector("text=로그아웃", timeout=5000)
        return True
    except Exception:  # noqa: BLE001 - 안 보이면 그냥 로그아웃 상태로 본다
        return False


# 기관찾기 화면에만 있는 것. 메인에도 지역 목록(#sidoUl)이 있어서 그걸로는 구분이 안 된다
#  — 2026-11-11: 메인으로 튕긴 걸 모르고 메인의 지역 목록을 누르고 있었다.
SEARCH_MARK = "#aUnityN"


def open_search_page(page, tries: int = 5) -> None:
    """시간제보육 기관찾기 화면을 연다. 메인으로 튕기면 다시 들어간다."""
    for _ in range(tries):
        page.goto(MENU_RESERVE, wait_until="domcontentloaded", timeout=60000)
        try:
            wait_ready(page, SEARCH_MARK, timeout_ms=9000)
            return
        except RuntimeError:
            time.sleep(0.5)
    raise RuntimeError("기관찾기 화면이 안 열려요 (자꾸 메인으로 돌아가요)")


def open_reserve_page(page, center: dict) -> None:
    """기관찾기에서 그 어린이집의 예약 버튼까지 눌러 입소신청 화면으로 들어간다.

    center: {"name", "code", "sido", "gugun"}
    """
    open_search_page(page)

    # 지역 목록(#sidoUl·#gugunUl)은 접혀 있어 Playwright 가 "안 보인다"며 클릭을 거부하고,
    # 구·군은 시·도를 고른 뒤 따로 받아 와 늦게 생긴다(2026-11-11 실패로 알게 됨).
    tap_text(page, "#sidoUl li a", center["sido"])
    tap_text(page, "#gugunUl li a", center["gugun"])
    safe_eval(
        page,
        "() => { document.getElementById('aUnityN').checked = true; document.getElementById('btnSearch').click() }",
    )

    sel = f'a#occasionRes[data-stcode="{center["code"]}"]'
    page.wait_for_selector(sel, timeout=30000)
    safe_eval(page, "(sel) => document.querySelector(sel).click()", sel)
    wait_ready(page, "#tab1")
    if "menuno=605" not in page.url:
        raise RuntimeError(f"예약 화면으로 못 들어갔어요 ({page.url[:60]})")


# ───────── 장전과 발사 (2026-11-11 실측) ─────────
# 입소신청 화면(?menuno=605)에서 "이용정보 신청"(#tab1) 을 열면 날짜×시간 표가 나온다.
#   칸      a.time-option#tm_<시각>_<행번호>, 행번호 = 오늘로부터 며칠 뒤(0~14)
#   칸 글자 숫자 = 더 받을 수 있는 아동 수(0 이면 자리 없음), X = 운영 안 함
#   반      select#clname (예: 15=들꽃향기)   이용시간 수 select#rtm
#   추가    #timecareTableAddBtn → f_AddQualRow()  ← 서버를 한 번 부른다
#   예약    #timecareConfirm     → fnSave() → insertOcreqst() → 확인창 → 넷퍼넬 → 전송
#
# 추가 버튼이 실제로 하는 일은 **숨은 값 8개를 채우고 목록에 행 하나를 만드는 것**뿐이라,
# 그 값을 우리가 직접 써 넣으면 서버를 한 번도 안 부르고 장전할 수 있다(≈1ms).
# 정각에는 fnSave() 한 번만 쏜다. 넷퍼넬 대기열이 있으므로 **연타하지 않는다**.

WEEKDAYS = "월화수목금토일"


def _slot(use_date: str, begin: str, end: str, class_seq: str, class_name: str) -> dict:
    """화면이 쓰는 모양 그대로 값을 만든다. 공백 하나까지 실제 화면과 같아야 한다."""
    from datetime import datetime

    day = datetime.strptime(use_date, "%Y%m%d")
    bh, bm = begin.split(":")
    eh, em = end.split(":")
    bt, et = f"{bh} : {bm}", f"{eh} : {em}"
    return {
        "sdate": f"{day:%Y-%m-%d}({WEEKDAYS[day.weekday()]})",
        "resdt": use_date,
        "resbgntm": bt,
        "resendtm": et,
        "restime": f"{bt}  ~  {et} ",
        "rtm": str(int(eh) - int(bh)),
        "resclseq": class_seq,
        "resclname": class_name,
    }


def open_apply_tab(page, class_seq: str = "") -> tuple[str, str]:
    """아동을 고르고 '이용정보 신청' 탭을 연다. 고른 (반 코드, 반 이름)을 돌려준다.

    반 코드는 기관마다 다르다. 안 주면 화면의 첫 번째 반을 고른다(독립반은 보통 한 반).
    정각 전에 미리 해 둔다 — 여기까지가 준비다.
    """
    if not safe_eval(
        page,
        """() => {
             const r = document.querySelector('input[name=occasionChk]');
             if (!r) return false;
             r.checked = true; r.click();
             const tab = document.getElementById('tab1');
             if (tab) tab.click();
             return true;
           }"""
    ):
        raise RuntimeError("등록된 아동이 없어요 — 아이사랑에서 시간제보육 아동등록을 먼저 해 주세요")
    page.wait_for_selector("#clname", timeout=30000)
    picked = safe_eval(
        page,
        """(want) => {
             const sel = document.getElementById('clname');
             const opts = [...sel.options].filter(o => o.value);
             const o = want ? opts.find(o => o.value === want) : opts[0];
             if (!o) return null;
             sel.value = o.value;
             sel.dispatchEvent(new Event('change', {bubbles: true}));
             return [o.value, o.text.trim()];
           }""",
        class_seq,
    )
    if not picked:
        raise RuntimeError("반 목록이 비어 있어요")
    return picked[0], picked[1]


def row_index(use_date: str, today=None) -> int:
    """표에서 그 날짜가 몇 번째 줄인지. 표는 늘 오늘(0)부터 14일 뒤(14)까지다."""
    from datetime import date, datetime

    today = today or date.today()
    return (datetime.strptime(use_date, "%Y%m%d").date() - today).days


def is_open(page, use_date: str, begin: str) -> bool:
    """그 날짜·시각에 자리가 있는지 가볍게 확인한다(신청하지 않는다).

    표를 새로 받아 와서 칸 글자가 1 이상인지만 본다.
    """
    idx = row_index(use_date)
    hour = int(begin.split(":")[0])
    page.evaluate("() => { if (window.fnRefresh) window.fnRefresh() }")
    page.wait_for_timeout(500)
    text = page.evaluate(
        "(id) => { const e = document.getElementById(id); return e ? e.innerText.trim() : null }",
        f"tm_{hour}_{idx}",
    )
    return bool(text) and text.isdigit() and int(text) >= 1


_ARM_JS = """(s) => {
  const form = document.getElementById('pfrm');
  const put = (name, value) => {
    let el = form.querySelector(`input[name="${name}"]`);
    if (!el) { el = document.createElement('input'); el.type = 'hidden'; el.name = name; form.appendChild(el); }
    el.value = value;
  };
  put('sdateArray', s.sdate);
  put('restimeArray', s.restime);
  put('resdtArray', s.resdt);
  put('resbgntmArray', s.resbgntm);
  put('resendtmArray', s.resendtm);
  put('rtmArray', s.rtm);
  put('resclseqArray', s.resclseq);
  put('infoNum', '1');

  const body = document.querySelector('#INFOQUALF tbody') || document.getElementById('INFOQUALF');
  [...body.querySelectorAll('tr[id^=tId_]')].forEach(tr => tr.remove());
  const tr = document.createElement('tr');
  tr.id = 'tId_0';
  const fields = {resclname0: s.resclname, resclseq0: s.resclseq, sdate0: s.sdate, resdt0: s.resdt,
                  restime0: s.restime, resbgntm0: s.resbgntm, resendtm0: s.resendtm, rtm0: s.rtm};
  const cells = [
    `<input type="checkbox" name="rowQualChkNo" value="on">`,
    `<input type="hidden" name="resclname0" value="${s.resclname}"><input type="hidden" name="resclseq0" value="${s.resclseq}">${s.resclname}`,
    `<input type="hidden" name="sdate0" value="${s.sdate}"><input type="hidden" name="resdt0" value="${s.resdt}">${s.sdate}`,
    `<input type="hidden" name="restime0" value="${s.restime}"><input type="hidden" name="resbgntm0" value="${s.resbgntm}">` +
    `<input type="hidden" name="resendtm0" value="${s.resendtm}"><input type="hidden" name="rtm0" value="${s.rtm}">${s.restime}`,
  ];
  tr.innerHTML = cells.map(c => `<td>${c}</td>`).join('');
  body.appendChild(tr);
  return [...body.querySelectorAll('tr[id^=tId_]')].length;
}"""


def arm(page, class_seq: str, class_name: str, use_date: str, begin: str, end: str) -> dict:
    """장전 — 예약 목록 행과 숨은 값을 직접 채운다. 서버를 부르지 않는다."""
    slot = _slot(use_date, begin, end, class_seq, class_name)
    rows = page.evaluate(_ARM_JS, slot)
    if rows != 1:
        raise RuntimeError(f"장전 실패(행 {rows}개)")
    return slot


# 확인 레이어가 뜨는 즉시 누르도록 미리 걸어 두는 감시자. 사람은 0.5초, 이건 1프레임이다.
# 결과 문구는 금방 닫힐 수 있으니 뜨는 족족 받아 적어 둔다(2026-11-11 실측으로 필요했다).
_AUTO_CONFIRM_JS = """() => {
  window.__fired = [];
  window.__popups = [];
  const seen = new Set();
  const hit = () => {
    for (const id of ['layer-confirm-popup-contents', 'layer-confirm-popup-contents2']) {
      const box = document.getElementById(id);
      if (box && box.offsetParent !== null) {
        const t = box.innerText.trim();
        if (t && !seen.has(t)) { seen.add(t); window.__popups.push(t); }
      }
    }
    for (const id of ['layer-confirm-popup-confirm', 'layer-confirm-popup-confirm2']) {
      const el = document.getElementById(id);
      if (el && el.offsetParent !== null) { window.__fired.push(id); el.click(); return true; }
    }
    return false;
  };
  new MutationObserver(hit).observe(document.body, {subtree: true, attributes: true, childList: true});
  hit();
}"""

# 실제로 성공했을 때 나온 문구: "1건 예약 중 1건 예약되었습니다." (2026-11-11 실측)
_OK_WORDS = ("예약되었습니다", "예약완료", "신청이 완료", "정상적으로")


def fire(page) -> tuple[bool, str]:
    """정각 한 방. fnSave() 를 부르고 확인창을 즉시 넘긴다. 넷퍼넬 대기열은 그대로 기다린다."""
    alerts: list[str] = []
    page.on("dialog", lambda d: (alerts.append(d.message), d.accept()))
    page.evaluate(_AUTO_CONFIRM_JS)
    page.evaluate("() => window.fnSave()")

    # 넷퍼넬 대기열에 들어가면 순서가 올 때까지 기다린다. 여기서 다시 쏘면 줄 뒤로 밀린다.
    for _ in range(120):
        page.wait_for_timeout(500)
        said = alerts + (page.evaluate("() => window.__popups || []") or [])
        if said:
            msg = redact(" / ".join(said), limit=140)
            return any(w in msg for w in _OK_WORDS), msg
    return False, "응답이 없어요 (대기열이 길거나 막혔을 수 있어요)"


def reserve(page, klass: tuple[str, str], use_date: str, begin: str, end: str) -> tuple[bool, str]:
    """장전 + 발사. 화면은 이미 입소신청 탭이 열려 있어야 한다. klass = (반 코드, 반 이름)."""
    arm(page, klass[0], klass[1], use_date, begin, end)
    return fire(page)
