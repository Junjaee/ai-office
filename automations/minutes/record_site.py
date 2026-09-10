"""record.assembly.go.kr 접근: HTML 파서(순수 함수) + RecordSite HTTP 클라이언트."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

BASE = "https://record.assembly.go.kr/assembly"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)

CLASS_NAMES = {
    1: "국회본회의",
    2: "상임위원회",
    3: "특별위원회",
    4: "예산결산특별위원회",
    5: "국정감사",
    6: "국정조사",
}


@dataclass(frozen=True)
class Committee:
    code: str
    name: str


@dataclass(frozen=True)
class Session:
    key: str      # 회기 번호("438") 또는 국정감사 연도("2025")
    label: str


@dataclass(frozen=True)
class Meeting:
    id: int
    title: str
    temp: bool
    has_pdf: bool


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def _attr(node, name: str) -> str:
    """속성값을 문자열로. bs4는 일부 속성을 리스트로 주므로 합쳐서 돌려준다."""
    value = node.get(name)
    if value is None:
        return ""
    if isinstance(value, list):
        value = " ".join(value)
    return str(value).strip()


def parse_committees(html: str) -> list[Committee]:
    out: list[Committee] = []
    for a in _soup(html).select("a.tit.cmit[data-cmit]"):
        code = _attr(a, "data-cmit")
        name = _text(a)
        if code and name:
            out.append(Committee(code, name))
    return out


def parse_sessions(html: str) -> list[Session]:
    out: list[Session] = []
    for a in _soup(html).select("a.tit"):
        # 회기는 data-sess, 국정감사 연도는 data-dt (일부 페이지는 data-year)
        key = _attr(a, "data-sess") or _attr(a, "data-dt") or _attr(a, "data-year")
        if not key:
            continue
        out.append(Session(key, _text(a)))
    return out


def parse_meetings(html: str) -> list[Meeting]:
    out: list[Meeting] = []
    for a in _soup(html).select("a.ord_num[data-id]"):
        try:
            mid = int(_attr(a, "data-id"))
        except ValueError:
            continue
        li = a.find_parent("li")
        temp = bool(a.select_one("span.temp"))
        title = _attr(a, "title")
        if not title:
            strong = a.select_one("strong")
            for span in (strong.select("span") if strong else []):
                span.decompose()
            title = _text(strong) if strong else ""
        has_pdf = bool(li and li.select_one('a[href*="download/pdf.do"]'))
        out.append(Meeting(mid, title, temp, has_pdf))
    return out


def filename_from_disposition(header: str | None) -> str | None:
    if not header:
        return None
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', header)
    if not m:
        return None
    return unquote(m.group(1)).strip() or None


class RecordSite:
    """요청 간격·재시도·쿠키를 관리하는 HTTP 클라이언트."""

    def __init__(self, delay: float = 1.0, retries: int = 3, timeout: int = 90):
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self._last = 0.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    # --- 저수준 ---
    def _throttle(self) -> None:
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def _request(self, method: str, path: str, *, referer: str, **kw) -> requests.Response:
        url = BASE + path
        headers = {"Referer": referer}
        if method == "POST":
            headers["X-Requested-With"] = "XMLHttpRequest"
        last_exc: Exception | None = None
        for attempt in range(self.retries):
            self._throttle()
            try:
                r = self.session.request(method, url, headers=headers, timeout=self.timeout, **kw)
                if r.status_code >= 500:
                    raise requests.HTTPError(f"{r.status_code} for {url}")
                r.raise_for_status()
                return r
            except (requests.RequestException, requests.HTTPError) as exc:
                last_exc = exc
                time.sleep(2 ** attempt)
        raise RuntimeError(f"요청 실패 {method} {url}: {last_exc}")

    # --- 목록 ---
    def tree_page(self, th: int, cls: int) -> str:
        r = self._request("GET", f"/mnts/total/{th}.do", referer=f"{BASE}/mnts/main.do",
                          params={"class_id_sch": cls, "cmit_chk": "all"})
        return r.text

    def committees(self, th: int, cls: int) -> list[Committee]:
        if cls == 1:
            return [Committee("", CLASS_NAMES[1])]
        if cls == 4:
            return [Committee("G1", CLASS_NAMES[4])]
        return parse_committees(self.tree_page(th, cls))

    def sessions(self, th: int, cls: int, code: str) -> list[Session]:
        if cls in (1, 4):
            return parse_sessions(self.tree_page(th, cls))
        r = self._request("POST", "/mnts/async/sessCmit.do", referer=f"{BASE}/mnts/total/{th}.do",
                          data={"th_sch": th, "class_id_sch": cls, "cmit_id_sch": code, "cmit_chk": "all"})
        return parse_sessions(r.text)

    def meetings(self, th: int, cls: int, code: str, key: str) -> list[Meeting]:
        referer = f"{BASE}/mnts/total/{th}.do"
        if cls == 1:
            r = self._request("POST", "/mnts/async/sess.do", referer=referer,
                              data={"th_sch": th, "class_id_sch": 1, "sess_sch": key, "chk": "all"})
        else:
            data = {"th_sch": th, "class_id_sch": cls, "cmit_cd_sch": code, "cmit_chk": "all"}
            if cls == 5:
                data["conf_year"] = key
            else:
                data["sess_sch"] = key
            r = self._request("POST", "/mnts/async/cmit.do", referer=referer, data=data)
        return parse_meetings(r.text)

    # --- 다운로드 ---
    def download_pdf(self, minutes_id: int) -> tuple[str | None, bytes]:
        referer = f"{BASE}/viewer/minutes/xml.do?id={minutes_id}&type=view"
        r = self._request("GET", "/viewer/minutes/download/pdf.do", referer=referer,
                          params={"id": minutes_id})
        data = r.content
        if not data.startswith(b"%PDF"):
            raise RuntimeError(f"PDF가 아닌 응답 (id={minutes_id}, {len(data)} bytes)")
        return filename_from_disposition(r.headers.get("Content-Disposition")), data
