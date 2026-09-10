"""열린국회정보 Open API로 회의록 목록을 받는다.

지원 범위 (2026-09-09 확인): 국회본회의, 상임위원회(소위 포함), 특별위원회, 예산결산특별위원회.
국정감사·국정조사 API는 데이터를 주지 않아 사이트 직접 조회(record_site)로 보완한다.
API 응답은 안건 단위 행이라 회의번호(CONFER_NUM)로 중복을 없앤다. 임시/확정 여부는 주지 않는다.
"""
from __future__ import annotations

import re
import time

import requests

from catalog import MinutesEntry
from record_site import USER_AGENT

BASE = "https://open.assembly.go.kr/portal/openapi/"
API_PLENARY = "nzbyfwhwaoanttzje"      # 본회의 회의록
API_COMMITTEE = "ncwgseseafwbuheph"    # 위원회 회의록 (상임위·특위·예결위·소위)
CLASS_BY_NAME = {"국회본회의": 1, "상임위원회": 2, "특별위원회": 3, "예산결산특별위원회": 4}
PAGE_SIZE = 1000
_SESS_RE = re.compile(r"제(\d+)회")


def parent_committee(comm_name: str) -> str:
    """'국방위원회 예산결산심사소위원회' -> '국방위원회'. 소위 없는 이름은 그대로."""
    return (comm_name or "").strip().split(" ")[0]


def rows_to_entries(rows: list[dict], th: int) -> list[MinutesEntry]:
    seen: set[int] = set()
    out: list[MinutesEntry] = []
    for r in rows:
        try:
            mid = int(r["CONFER_NUM"])
        except (KeyError, TypeError, ValueError):
            continue
        if mid in seen:
            continue
        seen.add(mid)
        cls = CLASS_BY_NAME.get((r.get("CLASS_NAME") or "").strip())
        if cls is None:
            continue
        committee = "국회본회의" if cls == 1 else parent_committee(r.get("COMM_NAME") or "")
        m = _SESS_RE.search(r.get("TITLE") or "")
        out.append(MinutesEntry(
            id=mid, th=th, cls=cls, committee=committee, sess=m.group(1) if m else "",
            title=(r.get("TITLE") or "").strip(), temp=None, has_pdf=bool(r.get("PDF_LINK_URL")),
        ))
    return out


class OpenApi:
    def __init__(self, key: str, delay: float = 0.5, timeout: int = 60):
        self.key = key
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})  # 기본 UA는 400으로 거절된다

    def rows(self, api: str, **params) -> list[dict]:
        """모든 페이지를 합쳐 행 목록을 돌려준다. 데이터 없음(INFO-200)은 빈 목록."""
        out: list[dict] = []
        page = 1
        while True:
            q = {"KEY": self.key, "Type": "json", "pIndex": page, "pSize": PAGE_SIZE, **params}
            r = self.session.get(BASE + api, params=q, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            if "RESULT" in data:
                code = data["RESULT"].get("CODE", "")
                if code == "INFO-200":
                    break
                raise RuntimeError(f"Open API 오류 {code}: {data['RESULT'].get('MESSAGE')}")
            body = data[api]
            rows = body[1]["row"] if len(body) > 1 else []
            out.extend(rows)
            total = int(body[0]["head"][0]["list_total_count"])
            if len(out) >= total or not rows:
                break
            page += 1
            time.sleep(self.delay)
        return out

    def entries(self, th: int, date_prefix: str) -> list[MinutesEntry]:
        """대수 th, 회의날짜가 date_prefix(예: '2026-09')로 시작하는 회의록 목록."""
        rows: list[dict] = []
        for api in (API_PLENARY, API_COMMITTEE):
            rows += self.rows(api, DAE_NUM=th, CONF_DATE=date_prefix)
        return rows_to_entries(rows, th)
