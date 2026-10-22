"""지방의회 회의록 사이트 어댑터.

틀(template)마다 클래스 하나. 공통 규칙:
  terms()           -> 대수 목록 (큰 수부터)
  iter_docs(th)     -> 그 대수의 회의록 Doc 들 (최근 회기부터)
  fetch_text(doc)   -> 본문 글자

사이트 요청은 Http 가 간격·재시도를 맡는다(1초 이상, 3회).
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Iterator

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36 ai-office-lcouncil"


@dataclass
class Doc:
    """회의록 한 건. id 는 그 의회 안에서 유일하면 된다."""
    id: str
    th: int                 # 대수
    session: int            # 회기(제N회)
    session_type: str       # 정례회·임시회·행정사무감사 …
    committee: str          # 본회의·위원회 이름
    order: str              # 차수(제N차) 또는 빈 문자열
    date: str               # YYYY-MM-DD (모르면 빈 문자열)
    title: str
    url: str
    temp: bool = False      # 임시회의록이면 True (나중에 확정본으로 바뀜)


class Http:
    def __init__(self, delay: float = 1.5, retries: int = 3, timeout: int = 60):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.delay, self.retries, self.timeout = delay, retries, timeout
        self._last = 0.0

    def _wait(self):
        gap = time.monotonic() - self._last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last = time.monotonic()

    def get(self, url: str, params: dict | None = None) -> requests.Response:
        err: Exception | None = None
        for i in range(self.retries):
            self._wait()
            try:
                r = self.s.get(url, params=params, timeout=self.timeout)
                if r.status_code >= 500:
                    raise requests.HTTPError(f"{r.status_code} {url}")
                r.raise_for_status()
                return r
            except Exception as exc:  # noqa: BLE001
                err = exc
                time.sleep(2 * (i + 1))
        raise RuntimeError(f"요청 실패({self.retries}회): {url} — {err}")

    def json(self, url: str, params: dict | None = None):
        r = self.get(url, params)
        try:
            return r.json()
        except ValueError:
            return json.loads(r.text.strip())


def _date(s: str | None) -> str:
    """'2024.06.07' '2024-06-07' '2024.06.07.' -> '2024-06-07'"""
    m = re.search(r"(\d{4})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})", s or "")
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""


def html_text(html: str, selector: str) -> str:
    """선택한 그릇 안의 글자만. 발언자(○…)마다 줄을 나눠 읽기 좋게 한다."""
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    box = soup.select_one(selector) or soup.body or soup
    text = box.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


# ───────────────────────── 전자회의록 틀 (인정보기술) ─────────────────────────

class EjournalSite:
    """/assem/… 전남광주·인천·전북 등. 본회의(B)·상임위(S)·특별위(T)·예결위(Y)·기타(K) 묶음을 모두 훑는다."""
    GROUPS = ["B", "S", "T", "Y", "K"]

    def __init__(self, base: str, http: Http):
        self.base = base.rstrip("/")
        self.http = http

    def terms(self) -> list[int]:
        html = self.http.get(f"{self.base}/assem/search/simple/session.do").text
        nums = sorted({int(x) for x in re.findall(r'csNum\s*=\s*"(\d+)"', html)}, reverse=True)
        if not nums:
            raise RuntimeError("대수 목록(csNum)을 찾지 못함")
        return nums

    def iter_docs(self, th: int) -> Iterator[Doc]:
        seen: set[str] = set()
        for group in self.GROUPS:
            sessions = self.http.json(f"{self.base}/assem/search/simple/LoadingSession_Year.json",
                                      {"searchCsDaesoo": th, "searchCtGroup": group}) or []
            for s in sorted(sessions, key=lambda x: int(x.get("csNum") or 0), reverse=True):
                sess = int(s.get("csNum") or 0)
                stype = s.get("csTypeNm") or ""
                docs = self.http.json(f"{self.base}/assem/search/simple/LoadingList.json",
                                      {"searchCsSession": sess, "searchCtGroup": group}) or []
                for d in docs:
                    uid = str(d.get("cdUid"))
                    if uid in seen:
                        continue
                    seen.add(uid)
                    order = f"제{d['cdChasoo']}차" if str(d.get("cdChasoo") or "0") != "0" else ""
                    title = f"제{sess}회 {d.get('ctNm') or ''} {order}".strip()
                    yield Doc(id=uid, th=th, session=sess, session_type=stype, committee=d.get("ctNm") or "",
                              order=order, date=_date(d.get("cdDate")), title=title,
                              url=f"{self.base}/assem/viewer.do?cdUid={uid}", temp=(d.get("cdImsi") == "Y"))

    def fetch_text(self, doc: Doc) -> str:
        return html_text(self.http.get(doc.url).text, "#bodyBox")


# ───────────────────────── 서울시의회 틀 (/record/) ─────────────────────────

class RecordSite:
    """/record/sessionList.do → committeeList.do → orderList.do → recordView.do?key= (서울·경남 등)"""

    def __init__(self, base: str, http: Http, council_id: str, session_page: str = "/kr/assembly/session.do"):
        self.base = base.rstrip("/")
        self.http = http
        self.cid = council_id
        self.session_page = session_page

    def terms(self) -> list[int]:
        html = self.http.get(self.base + self.session_page).text
        nums = sorted({int(x) for x in re.findall(r'"mode"\s*:\s*"session"[^}]*?"th"\s*:\s*(\d+)', html)}, reverse=True)
        if not nums:
            raise RuntimeError("대수 목록(th)을 찾지 못함")
        return nums

    def iter_docs(self, th: int) -> Iterator[Doc]:
        sessions = self.http.json(f"{self.base}/record/sessionList.do", {"councilId": self.cid, "th": th}) or []
        for s in sorted(sessions, key=lambda x: int(x.get("session") or 0), reverse=True):
            sess = int(s.get("session") or 0)
            m = re.search(r"\[([^\]]+)\]", s.get("title") or "")
            stype = m.group(1) if m else ""
            comms = self.http.json(f"{self.base}/record/committeeList.do",
                                   {"councilId": self.cid, "th": th, "session": sess}) or []
            for c in comms:
                orders = self.http.json(f"{self.base}/record/orderList.do",
                                        {"councilId": self.cid, "th": th, "session": sess, "code": c.get("code")}) or []
                for o in orders:
                    a = BeautifulSoup(o.get("title") or "", "lxml").find("a")
                    if not a or "key=" not in (a.get("href") or ""):
                        continue
                    key = a["href"].split("key=", 1)[1].split("&")[0]
                    label = a.get_text(" ", strip=True)
                    om = re.search(r"제\s*(\d+)\s*차", label)
                    yield Doc(id=key, th=th, session=sess, session_type=stype, committee=c.get("title") or "",
                              order=f"제{om.group(1)}차" if om else "", date=_date(label),
                              title=f"제{sess}회 {c.get('title') or ''} {label}".strip(),
                              url=f"{self.base}/record/recordView.do?key={key}",
                              temp=("임시" in label))

    def fetch_text(self, doc: Doc) -> str:
        return html_text(self.http.get(doc.url).text, "#canvas")


def build_site(council: dict, http: Http):
    """councils.yaml 항목 → 어댑터. template 가 없으면 None."""
    t = council.get("template")
    if t == "ejournal":
        return EjournalSite(council["base"], http)
    if t == "record":
        return RecordSite(council["base"], http, council["council_id"],
                          council.get("session_page", "/kr/assembly/session.do"))
    return None
