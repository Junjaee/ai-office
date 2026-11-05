"""행정실 "질의순서" 메일의 HWP 첨부에서 그날 질의할 위원의 (순번, 이름, 정당)을 읽는다 (설계 4-2절).

- HWP 5.0(OLE). pyhwp 의 글자 변환(hwp5txt)은 표 안을 건너뛰므로 HTML 변환 뒤 <table> 을 읽는다(2026-11-05 확인).
- 파일은 드라이브 수신함이 아니라 지메일 첨부에서 바로 받는다(수신함은 sort 가 옮기고 같은 이름이 둘씩 생긴다).
- 표 내용(이름·정당)은 공개 로그·상태 파일에 쓰지 않는다 — 부르는 쪽이 건수만 남긴다.
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

from hwp5.hwp5html import HTMLTransform
from hwp5.xmlmodel import Hwp5File

# 지메일 도우미는 상임위 메일 자동화의 것을 그대로 쓴다
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mail"))
from mail_gmail import download_attachment, gmail_service, message_meta, search_messages  # noqa: E402

PARTIES = ["더불어민주당", "국민의힘", "조국혁신당", "개혁신당", "진보당", "기본소득당", "사회민주당", "무소속"]
ORDER_KEYWORD = "질의순서"
_NAME = re.compile(r"^[가-힣]{2,4}$")


def parse_order_html(xhtml: str) -> list[tuple[int, str, str]]:
    """<table> 줄마다 '숫자 | 이름' 쌍을 찾아 (순번, 이름, 정당). 한 줄에 두 단이면 둘 다."""
    import warnings

    from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)   # xhtml 을 html 파서로 읽는다 — 표만 필요해서 충분
        soup = BeautifulSoup(xhtml or "", "lxml")
    out: list[tuple[int, str, str]] = []
    for tr in soup.find_all("tr"):
        cells = [" ".join(td.get_text(" ", strip=True).split()) for td in tr.find_all(["td", "th"])]
        i = 0
        while i < len(cells) - 1:
            if cells[i].isdigit() and _NAME.match(cells[i + 1]) and cells[i + 1] not in PARTIES and cells[i + 1] != "위원":
                party = ""
                for c in cells[i + 2:i + 5]:
                    if c in PARTIES:
                        party = c
                        break
                    if c.isdigit():
                        break
                out.append((int(cells[i]), cells[i + 1], party))
                i += 2
            else:
                i += 1
    return out


def hwp_to_xhtml(hwp_bytes: bytes) -> str:
    """pyhwp 는 파일 경로(OLE 저장소)만 받으므로 임시 파일에 써서 넘긴다."""
    # Windows 에서는 pyhwp 가 OLE 파일을 열어 둔 채라 임시 폴더 삭제가 막힐 수 있다 → 닫고, 그래도 안 지워지면 무시(서버는 리눅스)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        src = Path(tmp) / "order.hwp"
        src.write_bytes(hwp_bytes)
        hwp = Hwp5File(str(src))
        try:
            HTMLTransform().transform_hwp5_to_dir(hwp, tmp)
        finally:
            close = getattr(hwp, "close", None)
            if callable(close):
                close()
        return (Path(tmp) / "index.xhtml").read_text(encoding="utf-8")


def question_order(hwp_bytes: bytes) -> list[tuple[int, str, str]]:
    return parse_order_html(hwp_to_xhtml(hwp_bytes))


def find_order_attachment(service, query: str, lookback_days: int, date_yymmdd: str = "") -> tuple[str, str] | None:
    """검색어에 맞는 최근 메일 중 첨부 이름에 '질의순서'(와 오늘 날짜 YYMMDD)가 든 가장 최근 것 → (message_id, attachment_id).

    날짜를 보는 이유: 다른 날·소위원회 질의순서를 잡으면 그날을 통째로 건너뛰거나 오늘 위원의 호명을 놓친다.
    행정실 파일 이름은 `질의순서(261103)_…`, `…질의순서(전체)_261105_…` 처럼 회의 날짜를 담는다(2026-11-05 확인).
    """
    best: tuple[int, str, str] | None = None
    for mid in search_messages(service, f"{query} newer_than:{lookback_days}d has:attachment", limit=20):
        meta = message_meta(service, mid)
        for att in meta.attachments:
            if ORDER_KEYWORD not in att.name or (date_yymmdd and date_yymmdd not in att.name):
                continue
            if best is None or meta.ts > best[0]:
                best = (meta.ts, mid, att.part_id)
    return (best[1], best[2]) if best else None


def fetch_question_order(query: str, lookback_days: int, date_yymmdd: str = "") -> list[tuple[int, str, str]] | None:
    """지메일에서 오늘 질의순서 HWP 를 받아 읽는다. 메일이 없거나 표를 못 읽으면 None(→ 명단 없이 돈다)."""
    service = gmail_service()
    found = find_order_attachment(service, query, lookback_days, date_yymmdd)
    if not found:
        return None
    try:
        rows = question_order(download_attachment(service, *found))
    except Exception:  # noqa: BLE001 - HWP 깨짐·변환 실패: 명단 없이 간다
        return None
    return rows or None
