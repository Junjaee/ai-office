import re
from bs4 import BeautifulSoup
from .base import BoardAdapter

# 목록의 제목 링크는 javascript:jsDetail('<sn>', '<beCode>') 형태.
# jsDetail 은 sn 을 #q_caCode 에 넣고 상세 폼을 submit → 실제 id 파라미터는 q_caCode.
# sn 은 숫자+영문 혼합(예: 202607081447156290C076).
_SN_RE = re.compile(r"jsDetail\('([^']+)'")


def parse_list(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for tr in soup.select("table tbody tr"):
        a = tr.select_one("a")
        if not a:
            continue
        href = (a.get("href", "") or "") + " " + (a.get("onclick", "") or "")
        m = _SN_RE.search(href)
        if not m:
            continue
        tds = tr.find_all("td")
        # post_id 는 목록 첫 칸의 단조증가 순번(숫자) → 상태/정렬용.
        # detail_key(caCode) 는 상세 페이지 조회용 실제 id.
        seq = tds[0].get_text(strip=True) if tds else ""
        rows.append({
            "post_id": seq or m.group(1),
            "detail_key": m.group(1),
            "title": a.get_text(strip=True),
            "reg_no": "",
            "dept": tds[2].get_text(strip=True) if len(tds) > 2 else "",
            "date": tds[-1].get_text(strip=True) if tds else "",
        })
    return rows


class GnewsAdapter(BoardAdapter):
    def parse_list(self, html: str) -> list[dict]:
        return parse_list(html)

    def list_url(self, board: dict, page: int) -> str:
        return f"{board['list_path']}?q_beCode={board['be_code']}&q_currPage={page}"

    def detail_url(self, board: dict, base_url: str, post_id: str) -> str:
        return (f"{base_url}{board['detail_path']}"
                f"?q_beCode={board['be_code']}&{board['id_param']}={post_id}")
