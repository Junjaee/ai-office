import re
from bs4 import BeautifulSoup
from .base import BoardAdapter

_ID_RE = re.compile(r"opGosiView\('(\d+)'\)")


def parse_list(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for tr in soup.select("table tbody tr"):
        a = tr.select_one("a[href*=opGosiView]")
        if not a:
            continue
        m = _ID_RE.search(a.get("href", ""))
        if not m:
            continue
        tds = tr.find_all("td")
        rows.append({
            "post_id": m.group(1),
            "title": a.get_text(strip=True),
            "reg_no": tds[0].get_text(strip=True) if len(tds) > 0 else "",
            "dept": tds[2].get_text(strip=True) if len(tds) > 2 else "",
            "date": tds[3].get_text(strip=True) if len(tds) > 3 else "",
        })
    return rows


class GosiAdapter(BoardAdapter):
    def parse_list(self, html: str) -> list[dict]:
        return parse_list(html)

    def list_url(self, board: dict, page: int) -> str:
        # 고시 목록은 q_currPage 만으로는 페이지가 넘어가지 않는다(서버가 무시).
        # 목록 페이징 JS(opSearch)는 q_currPage 와 q_cp 를 함께 세팅하며,
        # 서버가 실제로 읽는 페이지 파라미터는 q_cp 다.
        return f"{board['list_path']}?q_currPage={page}&q_cp={page}"

    def detail_url(self, board: dict, base_url: str, post_id: str) -> str:
        return f"{base_url}{board['detail_path']}?{board['id_param']}={post_id}"
